"""Video routes layered over the verified integrated audio/image application."""
import json
import io
import os
import tempfile
import threading
import wave
from pathlib import Path
from urllib.parse import urlsplit, unquote

from integrated_app import IntegratedApplication
from console_app import handler_for
from video_engine import VideoEngine, MAX_BYTES

class VideoApplication(IntegratedApplication):
    def __init__(self,root,engine):
        super().__init__(root,engine)
        self.video_accelerator=None
        if getattr(getattr(engine,'driver',None),'video_control',None) is not None:
            from pynq import allocate
            from video_fpga import VideoFpga
            self.video_accelerator=VideoFpga(engine.driver,allocate)
            from image_fpga import ImageFpga
            self.image.accelerator=ImageFpga(self.video_accelerator)
        self.video=VideoEngine(root,self.display,self.video_accelerator)
        from live_monitor import LiveMonitor
        self.monitor=LiveMonitor(self)
        self.audio.engine.live_monitor=self.monitor
        from usb_capture import USBCapture
        self.usb_capture=USBCapture(self.monitor)
        self.video_measurement=None
        self.video_measurements={}
        self.effect_validation=None
        from round_benchmark import RoundBenchmark
        self.rounds=RoundBenchmark(self)
    def status(self):
        state=super().status()
        state.update(version='0.4.0',video_available=True,video=self.video.snapshot())
        state['video_fpga_available']=self.video_accelerator is not None
        state['video_fpga_modes']=list(self.video_accelerator.modes) if self.video_accelerator else []
        state['image_fpga_available']=self.image.accelerator is not None
        state['video_measurements']=dict(self.video_measurements)
        state['effect_validation']=self.effect_validation
        state['video_measurement']=self.video_measurement
        state['round_benchmark']=self.rounds.snapshot()
        state['live_monitor']=self.monitor.snapshot()
        state['usb_capture']=self.usb_capture.snapshot()
        state['live_monitor']['error'] = state['usb_capture'].get('error') or state['live_monitor'].get('error', '')
        state['avsync_available']=getattr(self.audio.engine,'fifo_mmio',None) is not None
        media_path=self.root/'media.json'
        if media_path.exists():state['media']=json.loads(media_path.read_text(encoding='utf-8'))
        return state
    def action(self,route,data):
        with self.gate:return self._action(route,data)

    def _action(self,route,data):
        if route=='/api/monitor/stop':
            if self.usb_capture.snapshot()['active']:return self.usb_capture.stop()
            return self.monitor.stop()
        if route=='/api/audio/source/default':
            self.require_audio_idle()
            self.audio.engine.restore_default_source()
            return {'ok':True}
        if route=='/api/benchmark/rounds/stop':
            if self.rounds.running():self.rounds.stop()
            return {'ok':True}
        if self.rounds.running():
            if route=='/api/av/stop':self.rounds.stop();return {'ok':True}
            raise ValueError('分轮测试正在运行，参数已锁定；请先停止测试')
        if self.benchmark_state['status']=='running' or self.audio_measurement['status']=='running':
            if route not in ('/api/av/stop','/api/audio/stop','/api/video/stop',
                             '/api/monitor/stop','/api/monitor/usb/stop'):
                raise ValueError('正在测量，请等待完成')
        if route=='/api/monitor/start':
            if getattr(self.video,'file',None) is None:
                raise ValueError('请先在首页上传现场视频，再进入实时监控。')
            return self.monitor.start()
        if route=='/api/monitor/usb/start':
            if getattr(self.video,'file',None) is None:
                raise ValueError('请先在首页上传现场视频，再进入实时监控。')
            if self.rounds.running():raise ValueError('请等待分轮测试结束。')
            return self.usb_capture.start()
        if route in ('/api/monitor/usb/stop','/api/monitor/stop'):
            if self.usb_capture.snapshot()['active']:return self.usb_capture.stop()
            return self.monitor.stop()
        if route=='/api/monitor/audio_output':
            return self.usb_capture.set_audio_output(bool(data.get('enabled',True)))
        if route=='/api/monitor/preset':
            return self.monitor.preset(data)
        if self.monitor.snapshot()['active'] and route in (
                '/api/audio/start','/api/video/start','/api/av/start',
                '/api/benchmark/audio','/api/benchmark/image','/api/benchmark/arm',
                '/api/benchmark/video','/api/benchmark/video-upload',
                '/api/benchmark/video-effects',
                '/api/benchmark/rounds/start'):
            raise ValueError('请先停止实时监控，再启动歌曲、视频或性能测试。')
        if route in ('/api/image/backend','/api/benchmark/image','/api/benchmark/arm'):
            self.require_audio_idle()
            if self.video.snapshot()['status']=='playing':raise ValueError('请先停止视频')
            if route=='/api/image/backend':
                self.image.select_backend(data.get('backend'))
                if self.display:self.display.refresh(self.image)
                return {'ok':True}
            if route=='/api/benchmark/image':
                if self.image.accelerator is None:raise ValueError('图片 FPGA 未接入')
                same_input=data.get('same_input',False)
                if type(same_input) is not bool:raise ValueError('same_input 必须为布尔值')
                self.benchmark_state={'status':'running','error':''}
                self.image.metrics=None
                threading.Thread(target=self._compare_image,args=(same_input,),daemon=True).start()
                return {'ok':True}
        if route=='/api/benchmark/rounds/start':
            if self.audio_measurement['status']=='running' or self.benchmark_state['status']=='running':raise ValueError('请等待当前测量结束')
            self.rounds.start(data.get('mode','smooth'));return {'ok':True}
        if route=='/api/benchmark/video-effects':
            self.require_audio_idle()
            if self.video.snapshot()['status']=='playing':raise ValueError('请先停止视频')
            if self.audio_measurement['status']=='running' or self.benchmark_state['status']=='running':raise ValueError('请等待当前测量结束')
            if self.video_accelerator is None:raise ValueError('当前硬件不支持视频滤波')
            from video_effects_check import validate_effects
            self.effect_validation=validate_effects(self.video_accelerator,self.root,self.video.file)
            return self.effect_validation
        if route=='/api/benchmark/video':
            with self.gate:
                self.require_audio_idle()
                if self.video.snapshot()['status']=='playing':raise ValueError('请先停止视频')
                if self.audio_measurement['status']=='running' or self.benchmark_state['status']=='running':raise ValueError('请等待当前测量结束')
                if self.video_accelerator is None:raise ValueError('未包含 FPGA 视频滤波')
                from video_measure import measure_video
                self.video_measurement=measure_video(self.video_accelerator,self.root,data.get('mode','smooth'))
                self.video_measurements[self.video_measurement['mode']]=self.video_measurement
                return self.video_measurement
        if route=='/api/benchmark/video-upload':
            self.require_audio_idle()
            if self.video.snapshot()['status']=='playing':raise ValueError('请先停止视频，再进行对比')
            if self.audio_measurement['status']=='running' or self.benchmark_state['status']=='running':raise ValueError('请等待当前性能测量结束')
            if self.video_accelerator is None:raise ValueError('当前硬件未包含 FPGA 视频滤波')
            if self.video.file is None:raise ValueError('请先上传视频，再进行 ARM / FPGA 对比')
            from video_measure import measure_uploaded_video
            self.video_measurement=measure_uploaded_video(
                self.video_accelerator,self.root,self.video.file,
                self.video.snapshot()['sha256'],data.get('mode','smooth'))
            self.video_measurements['uploaded_'+self.video_measurement['mode']]=self.video_measurement
            return self.video_measurement
        if route=='/api/video/backend':self.video.select_backend(data.get('backend'));return {'ok':True}
        if route=='/api/av/start':
            with self.gate:
                if self.audio_measurement['status']=='running' or self.benchmark_state['status']=='running':raise ValueError('请等待性能测量结束')
                engine=self.audio.engine
                if getattr(engine,'fifo_mmio',None) is None:raise ValueError('请使用音画同步硬件版本')
                if self.video.snapshot()['status']=='playing':raise ValueError('请先停止当前视频')
                if self.video.file is None:raise ValueError('请先准备视频')
                media_path=self.root/'media.json'
                if media_path.exists() and not getattr(engine,'uploaded_source',False):
                    media=json.loads(media_path.read_text(encoding='utf-8'))
                    if self.video.snapshot()['sha256']!=media['video_sha256']:raise ValueError('此视频与内置音轨不配套；请用同一 MV 重新生成同步包')
                engine.command({'action':'play'})
                try:self.video.start(clock=engine.playback_clock)
                except Exception:
                    engine.command({'action':'stop'});raise
                return {'ok':True}
        if route=='/api/av/stop':
            self.audio.stop();self.video.stop();return {'ok':True}
        if route=='/api/video/start':self.video.start();return {'ok':True}
        if route=='/api/video/stop':self.video.stop();return {'ok':True}
        if route=='/api/video/mode':self.video.select(data.get('mode'));return {'ok':True}
        if route in ('/api/image/mode','/api/hdmi/refresh') and self.video.snapshot()['status']=='playing':
            raise ValueError('请先停止视频，再更新静态画面')
        return super().action(route,data)
    def _compare_image(self,same_input=False):
        try:
            self.image.benchmark_compare(same_input=same_input)
            self.benchmark_state={'status':'done','error':''}
        except Exception as error:self.benchmark_state={'status':'error','error':str(error)}

    def upload(self,raw):
        with self.gate:
            if self.rounds.running():raise ValueError('请等待分轮测试结束')
            if self.video.snapshot()['status']=='playing':raise ValueError('请先停止视频，再更换图片')
            return super().upload(raw)
    def install_video(self,path,name):
        with self.gate:
            if self.rounds.running():raise ValueError('请等待分轮测试结束')
            return self.video.install(path,name)
    def close(self):
        self.usb_capture.stop()
        self.monitor.stop()
        self.rounds.close()
        self.video.stop()
        if self.video_accelerator:self.video_accelerator.close()
    def export(self):
        report=super().export()
        report['version']='0.4.0'
        report['video']=self.video.snapshot()
        report['video_measurement']=self.video_measurement
        report['video_measurements']=dict(self.video_measurements)
        report['video_measurement_history']=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((self.root/'data').glob('video_*.json'))[-30:]]
        report['round_history']=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((self.root/'data').glob('rounds_*.json'))[-10:]]
        report['effect_validation']=self.effect_validation
        report['round_benchmark']=self.rounds.report
        report['limitations']='Uploaded video is decoded and filtered live on ARM; FPGA scans the RGB332 HDMI canvas. Audio FIR can use ARM or FPGA. Video filter has no FPGA acceleration. Audio and video have separate playback clocks and are not synchronized. Reported FPS includes decode, filter, JPEG encoding, and HDMI refresh; filter_ms covers only filtering.'
        if getattr(self.audio.engine,'fifo_mmio',None) is not None:
            report['limitations']='Audio uses a 48kHz hardware FIFO clock. Synchronized video follows played samples, with late video frames skipped. Images remain ARM-filtered. Current demo combines independent Closer audio and generated test video; a same-source MV has not yet been supplied. Video timestamp error is measured at HDMI submission, not optical/acoustic end-to-end latency.'
            if getattr(self.audio.engine,'uploaded_source',False):
                report['limitations']='The uploaded video soundtrack is decoded by the browser, converted to 48kHz mono PCM, and processed by the board audio FIR. Synchronized playback follows the hardware audio clock and drops late video frames. Browser codec support is required; uploads are limited to three minutes. HDMI timestamps are measured at board submission, not optical/acoustic end-to-end latency.'
            if (self.root/'media.json').exists() and not getattr(self.audio.engine,'uploaded_source',False):
                report['limitations']='Audio and video use the same MV segment. Audio uses a 48kHz hardware FIFO clock; synchronized ARM video follows played samples, dropping late frames. Audio FIR can run on ARM or FPGA. Video timestamp error is measured at HDMI submission, not optical/acoustic end-to-end latency. Browser preview has additional network/polling latency.'
        if self.video_accelerator:
            report['limitations']='Video smooth mode supports ARM or FPGA; other video effects remain ARM. FPGA video timing includes padding, packing, shared DMA and result copying. Audio and video share DMA under a lock. Decode, composition, JPEG and HDMI remain outside the filter measurement. Playback follows the 48kHz hardware audio clock, dropping late video frames. HDMI register acknowledgments do not verify physical screen reception.'
            if 'edge' in self.video_accelerator.modes:
                report['limitations']=report['limitations'].replace('Video smooth mode supports ARM or FPGA; other video effects remain ARM.','Video smooth, edge and sharpen support ARM or FPGA; decode and composition remain on ARM.')
                report['limitations']+=' Static images also support ARM/FPGA with halo tiling at the original working size; timings include tile assembly and DMA. All comparison reports identify their fixed mode.'
        if getattr(self.audio.engine,'uploaded_source',False):
            report['limitations']+=' The uploaded video soundtrack is browser-decoded, converted to 48kHz mono PCM, and processed on the board; codec support is required and the accepted soundtrack duration is at most three minutes. Synchronized playback follows the hardware audio clock and drops late frames. HDMI timing is measured at board submission, not at the physical display.'
        report['limitations'] += ' Board-side USB camera/microphone capture uses usb_capture.py/usb_audio.py; the browser camera/microphone endpoints remain only as a legacy fallback. USB device format, microphone enumeration, board-side audio output and sustained performance require validation on the target board. File batches run sequentially and are not multi-channel parallel tests.'
        return report

def make_handler(root,engine):
    app=VideoApplication(root,engine)
    base=handler_for(app)
    class Handler(base):
        application=app
        def do_GET(self):
            route=urlsplit(self.path).path
            if route=='/monitor':
                if getattr(app.video,'file',None) is None:
                    self.send_response(303)
                    self.send_header('Location','/?need_video=1')
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
                self.reply((app.root/'web'/'monitor.html').read_bytes(),'text/html; charset=utf-8')
                return
            if route=='/analysis':
                self.reply((app.root/'web'/'analysis.html').read_bytes(),'text/html; charset=utf-8')
                return
            if route=='/api/monitor/devices':
                self.reply(app.usb_capture.devices())
                return
            if route=='/api/monitor/waveform':
                self.reply(app.monitor.waveform())
                return
            if route=='/video/live.jpg':
                query=urlsplit(self.path).query
                if 'raw=1' in query:
                    data=app.monitor.last_camera_jpeg()
                elif app.monitor.snapshot()['active']:
                    data=app.monitor.last_result_jpeg()
                else:
                    data=app.video.jpeg()
                if data:self.reply(data,'image/jpeg')
                else:self.reply({'error':'暂无视频帧'},status=404)
                return
            super().do_GET()
        def do_POST(self):
            route=urlsplit(self.path).path
            if route=='/api/audio/source':
                try:
                    origin=self.headers.get('Origin')
                    if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                        self.reply({'error':'Origin mismatch'},status=403);return
                    length=int(self.headers.get('Content-Length','0'))
                    if not 44<length<=20*1024*1024:
                        self.reply({'error':'解码后的音轨为空或超过 20 MB（约 3 分钟）'},status=413);self.close_connection=True;return
                    raw=self.rfile.read(length)
                    if len(raw)!=length:raise ValueError('音轨上传不完整。')
                    with wave.open(io.BytesIO(raw),'rb') as source:
                        if (source.getnchannels()!=1 or source.getsampwidth()!=2 or
                                source.getframerate()!=48000 or source.getcomptype()!='NONE'):
                            raise ValueError('音轨格式需为 48 kHz、单声道、16 位 PCM。')
                        frames=source.getnframes()
                        if not frames:raise ValueError('视频中没有可用音轨。')
                        pcm=source.readframes(frames)
                        if len(pcm)!=frames*2:raise ValueError('WAV 音轨数据不完整。')
                    with app.gate:
                        app.require_audio_idle()
                        if app.audio_measurement['status']=='running' or app.benchmark_state['status']=='running':
                            raise ValueError('请等待当前测量结束。')
                        target=app.root/'data'/'uploaded_video_audio.s16le'
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(pcm)
                        app.audio.engine.use_uploaded_source(target,'上传视频内嵌音轨')
                    self.reply({'ok':True,'sample_count':frames,'duration_seconds':round(frames/48000,3)})
                except (ValueError,OSError,wave.Error) as error:self.reply({'error':str(error)},status=400)
                return
            if route in ('/api/monitor/frame','/api/monitor/audio'):
                limit=app.monitor.MAX_VIDEO_BYTES if route.endswith('/frame') else app.monitor.MAX_AUDIO_SAMPLES*2
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=limit:
                        self.reply({'error':'实时数据块为空或超过大小限制。'},status=413)
                        self.close_connection=True
                        return
                    raw=self.rfile.read(length)
                    if len(raw)!=length:raise ValueError('实时数据接收不完整。')
                    if route.endswith('/frame'):
                        self.reply(app.monitor.process_video(raw),'image/jpeg')
                    else:
                        self.reply(app.monitor.process_audio(raw),'application/octet-stream')
                except (ValueError,OSError) as error:self.reply({'error':str(error)},status=400)
                except Exception as error:self.reply({'error':str(error)},status=500)
                return
            if route in ('/api/monitor/usb/start','/api/monitor/usb/stop'):
                try:
                    result=app.action(route,{})
                    self.reply(result)
                except (ValueError,OSError,RuntimeError) as error:
                    self.reply({'error':str(error)},status=400)
                return
            if route=='/api/analysis/upload':
                temp=None
                try:
                    origin=self.headers.get('Origin')
                    if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                        self.reply({'error':'Origin mismatch'},status=403);return
                    name=unquote(self.headers.get('X-Analysis-Name','upload'))
                    name=Path(name).name
                    suffix=Path(name).suffix.lower()
                    limits={'.jpg':10*1024*1024,'.jpeg':10*1024*1024,'.png':10*1024*1024,
                            '.mp4':MAX_BYTES,'.avi':MAX_BYTES,'.mov':MAX_BYTES,'.mkv':MAX_BYTES,
                            '.wav':20*1024*1024}
                    if suffix not in limits:
                        raise ValueError('支持 JPEG、PNG 图片，MP4、AVI、MOV、MKV 视频，以及 WAV 音频。')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=limits[suffix]:
                        self.reply({'error':'文件为空或超过类型对应的大小限制'},status=413);self.close_connection=True;return
                    fd,temp=tempfile.mkstemp(prefix='analysis_upload_',suffix=suffix,dir=str(app.root))
                    with os.fdopen(fd,'wb') as out:
                        remaining=length
                        self.connection.settimeout(180)
                        while remaining:
                            chunk=self.rfile.read(min(1024*1024,remaining))
                            if not chunk:raise ValueError('文件上传中断')
                            out.write(chunk);remaining-=len(chunk)
                    with app.gate:
                        if app.rounds.running():raise ValueError('分轮测试正在运行，请结束后再分析文件。')
                        app.require_audio_idle()
                        if app.video.snapshot()['status']=='playing':raise ValueError('请先停止视频播放。')
                        if app.benchmark_state['status']=='running' or app.audio_measurement['status']=='running':
                            raise ValueError('请等待当前性能测量结束。')
                        from file_analysis import analyze_file
                        result=analyze_file(temp,name,app.image.accelerator,app.root,app.audio.engine)
                    self.reply(result)
                except (ValueError,OSError) as error:self.reply({'error':str(error)},status=400)
                except Exception as error:self.reply({'error':str(error)},status=500)
                finally:
                    if temp and os.path.exists(temp):os.unlink(temp)
                return
            if route!='/api/video/upload':return super().do_POST()
            temp=None
            try:
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                    self.reply({'error':'Origin mismatch'},status=403);return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_BYTES:
                    self.reply({'error':'视频不能为空或超过 100 MB'},status=413);self.close_connection=True;return
                name=self.headers.get('X-Video-Name','video.mp4')
                name=Path(name).name
                suffix=Path(name).suffix.lower()
                if suffix not in ('.mp4','.avi','.mov','.mkv'):
                    raise ValueError('请选择 MP4、AVI、MOV 或 MKV 视频')
                fd,temp=tempfile.mkstemp(prefix='video_upload_',suffix=suffix,dir=str(app.root))
                with os.fdopen(fd,'wb') as out:
                    remaining=length
                    self.connection.settimeout(30)
                    while remaining:
                        chunk=self.rfile.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('视频上传中断')
                        out.write(chunk);remaining-=len(chunk)
                state=app.install_video(temp,name)
                temp=None
                self.reply({'ok':True,'video':state})
            except Exception as error:
                self.reply({'error':str(error)},status=400)
            finally:
                if temp and os.path.exists(temp):os.unlink(temp)
    return Handler
