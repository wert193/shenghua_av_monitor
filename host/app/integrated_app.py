"""Adapter between the verified live audio engine and the image console."""
import json
import time
import threading
from audio_benchmark import measure
from pathlib import Path
from console_app import Application, handler_for

class AudioAdapter:
    def __init__(self, engine): self.engine=engine
    def snapshot(self):
        state=self.engine.snapshot()
        return dict(state, requested_mode=state['mode'],mode=state['applied_mode'],
                    duration=30,events=state.get('events',[]),last_log=state.get('last_log',''))
    def start(self): self.engine.command({'action':'play'})
    def stop(self): self.engine.command({'action':'stop'})
    def mode(self, value): self.engine.command({'mode':value})

class IntegratedApplication(Application):
    def __init__(self, root, engine):
        super().__init__(root=root,audio=AudioAdapter(engine))
        self.audio_measurement={'status':'idle','progress':'','error':'','result':None}
        self.display=None
        overlay=getattr(engine,'overlay',None)
        if overlay is not None and 'screen_control' in overlay.ip_dict and (
                'screen_bram' in overlay.ip_dict or
                any(name.startswith('screen_bram') for name in overlay.mem_dict)):
            from hdmi_display import HdmiDisplay
            self.display=HdmiDisplay(engine.overlay)
            self.display.refresh(self.image)
    def status(self):
        state=super().status()
        state.update(version='0.3.0',fpga_available=True,audio_fpga_available=True,image_fpga_available=False)
        state['audio_measurement']=dict(self.audio_measurement)
        state['hdmi_available']=self.display is not None
        state['hdmi']=self.display.snapshot() if self.display else {'status':'unavailable','error':''}
        return state
    def action(self, route, data):
        with self.gate:
            if self.audio_measurement['status']=='running':
                raise ValueError('正在测量音频，请等待完成')
            if route=='/api/hdmi/refresh':
                self.require_audio_idle()
                if self.benchmark_state['status']=='running': raise ValueError('请等待图片测量结束')
                if self.display is None: raise ValueError('此配置未包含 HDMI')
                self.display.refresh(self.image)
                if self.display.state['error']: raise ValueError(self.display.state['error'])
                return {'ok':True}
            if route=='/api/benchmark/audio':
                if self.benchmark_state['status']=='running': raise ValueError('请等待图片测量结束')
                engine=self.audio.engine
                with engine.lock:
                    if engine.thread and engine.thread.is_alive(): raise ValueError('请先停止歌曲并等待播放结束')
                    engine.stop_event.clear()
                    self.audio_measurement={'status':'running','progress':'准备中','error':'','result':None}
                    engine.update(status='measuring')
                    engine.thread=threading.Thread(target=self._measure_audio,daemon=True)
                    engine.thread.start()
                return {'ok':True}
            if route=='/api/audio/backend':
                self.audio.engine.command({'backend':data.get('backend')})
                return {'ok':True}
            if route=='/api/image/mode': self.require_audio_idle()
            result=super().action(route,data)
            if route=='/api/image/mode' and self.display: self.display.refresh(self.image)
            return result
    def _measure_audio(self):
        try:
            result=measure(self.audio.engine,self.root,lambda message:self.audio_measurement.update(progress=message))
            self.audio_measurement.update(status='done',progress='四种模式测量完成',result=result)
        except Exception as error:
            self.audio_measurement.update(status='error',error=str(error),progress='测量未通过')
        finally:
            self.audio.engine.update(status='idle')
    def require_audio_idle(self):
        if self.audio.snapshot()['status'] in ('starting','running','stopping'):
            raise ValueError('请先停止歌曲，再更换或处理图片，避免影响连续播放。')
    def upload(self, raw):
        with self.gate:
            if self.audio_measurement['status']=='running': raise ValueError('请等待音频测量完成')
            self.require_audio_idle()
            result=super().upload(raw)
            if self.display: self.display.refresh(self.image)
            return result
    def export(self):
        report=super().export()
        report['version']='0.3.0'
        report['audio_sessions']=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(self.root.glob('session_*.json'))[-30:]]
        report['audio_measurements']=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((self.root/'data').glob('audio_benchmark_*/report.json'))[-30:]]
        report['image_measurements']=[r for r in report['image_measurements'] if not r['id'].startswith('audio_benchmark_')]
        report['limitations']='Live ARM/FPGA audio FIR; static ARM image filtering. No FPGA image processing, HDMI, video, or audio/video synchronization. Block timings are not end-to-end latency or a controlled speed benchmark.'
        if self.display:
            report['limitations']='Live ARM/FPGA audio FIR; static ARM image filtering with HDMI 720p scanout of a 640x360 RGB332 canvas. No FPGA image filtering, video, or audio/video synchronization. HDMI status does not confirm monitor connection.'
        return report

def make_handler(root, engine):
    return handler_for(IntegratedApplication(root,engine))
