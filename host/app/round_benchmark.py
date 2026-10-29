"""Fixed-material sequential ARM/FPGA audiovisual playback measurements."""
import hashlib,json,threading,time
from pathlib import Path
import numpy as np

def cpu_ticks(text=None):
    fields=(Path('/proc/stat').read_text() if text is None else text).splitlines()[0].split()
    if fields[0]!='cpu' or len(fields)<9:raise ValueError('Invalid /proc/stat CPU line')
    values=list(map(int,fields[1:9])) # guest/guest_nice already counted in user/nice
    return sum(values),values[3]+values[4]

def cpu_percent(before,after):
    total=after[0]-before[0];idle=after[1]-before[1]
    if total<=0:return 0.0
    return max(0.0,min(100.0,100*(total-idle)/total))

def summarize(backend,video,audio,records,cpu_before,cpu_after,wall_seconds,mode='smooth'):
    clock=audio['clock'];duration=clock['seconds']
    if not records or duration<=0:raise ValueError('No measured frames or audio clock')
    if any(r['backend']!=backend or r['mode']!=mode for r in records):raise ValueError('Video settings changed during test')
    values=[r['filter_ms'] for r in records]
    return dict(backend=backend,rendered_frames=len(records),source_frames=video['frames_total'],
        fps=len(records)/duration,filter_mean_ms=float(np.mean(values)),
        filter_p95_ms=float(np.percentile(values,95)),
        display_mean_ms=float(np.mean([r['display_ms'] for r in records])),
        prepare_mean_ms=float(np.mean([r['prepare_ms'] for r in records])),
        cpu_percent=cpu_percent(cpu_before,cpu_after),
        dropped_frames=max(0,video['frames_total']-len(records)),
        audio_underruns=clock['underruns'],audio_played=clock['played'],
        audio_seconds=duration,wall_seconds=wall_seconds,audio_log=audio.get('last_log',''))

class RoundBenchmark:
    def __init__(self,app):
        self.app=app;self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None
        self.state={'status':'idle','progress':'固定同源 MV，依次播放 ARM、FPGA 两轮，每轮 30 秒。','result':None,'error':''}
        self.report=None
        reports=sorted((app.root/'data').glob('rounds_*.json'))
        if reports:
            try:
                self.report=json.loads(reports[-1].read_text(encoding='utf-8'))
                if self.report.get('status')=='done':self.state.update(status='done',result=self.report['summary'],progress='已加载上次分轮记录')
            except (OSError,ValueError,KeyError):pass

    def snapshot(self):
        with self.lock:return json.loads(json.dumps(self.state))

    def running(self):
        with self.lock:return self.state['status']=='running'

    def start(self,mode='smooth'):
        if mode not in ('smooth','edge','sharpen'):raise ValueError('未知视频测量模式')
        app=self.app;engine=app.audio.engine
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('分轮测试正在运行')
            if app.video_accelerator is None:raise ValueError('需要 FPGA 视频版本')
            if mode not in getattr(app.video_accelerator,'modes',{'smooth':0}):raise ValueError('硬件不支持此模式')
            self.mode=mode
            if app.video.snapshot()['status']=='playing':raise ValueError('请先停止视频')
            media_path=app.root/'media.json'
            if not media_path.exists():raise ValueError('需要同源 MV 包')
            media=json.loads(media_path.read_text(encoding='utf-8'))
            if app.video.snapshot()['sha256']!=media['video_sha256']:raise ValueError('视频与内置音轨不配套')
            with engine.lock:
                if engine.thread and engine.thread.is_alive():raise ValueError('请等待音频结束')
                self.previous=(engine.state['mode'],engine.state['backend'],app.video.state['mode'],app.video.requested_backend)
                engine.controls_locked=True;engine.stop_event.clear()
            self.cancel.clear();self.state.update(status='running',progress='校验算法结果并预热',result=None,error='')
            self.thread=threading.Thread(target=self._run,args=(media,),daemon=True);self.thread.start()

    def stop(self):
        self.cancel.set()
        self.app.audio.engine.command({'action':'stop'},internal=True)

    def close(self):
        if self.thread and self.thread.is_alive():
            self.stop();self.thread.join(timeout=12)
            if self.thread.is_alive():raise RuntimeError('分轮测试尚未退出')

    def _progress(self,text):
        with self.lock:self.state['progress']=text

    def _run(self,media):
        app=self.app;engine=app.audio.engine;video=app.video
        report={'status':'running','media':media,'rounds':[],
            'settings':{'video_mode':'smooth','video_kernel':[[1,2,1],[2,4,2],[1,2,1]],
                'video_divisor':16,'border':'replicate','audio_mode':0,'audio_cutoff_hz':800,
                'audio_taps':255,'sample_rate':48000,'order':['ARM','FPGA'],
                'coefficients_sha256':hashlib.sha256(engine.coeff[0].tobytes()).hexdigest()},
            'scope':{'cpu':'Whole board /proc/stat busy percentage, normalized across all CPU cores; includes other processes. Iowait counted idle.',
                'filter_ms':'Actual per-displayed-frame filter call; includes FPGA packing/DMA/copy and shared-DMA lock wait.',
                'fps':'Displayed frames divided by hardware audio duration; includes full decode/composition/HDMI pipeline.',
                'dropped':'Source frame count minus displayed frames, including skipped startup/end frames.',
                'limitations':'One ARM then one FPGA run; thermal/order/background load may affect results. Not optical/acoustic end-to-end latency. These rounds fix smooth video; other effects are validated separately.'}}
        report['settings']['video_mode']=self.mode
        report['settings']['video_algorithm']={'smooth':'binomial 3x3 /16, rounded','edge':'integer luminance, Sobel abs X+Y /4, rounded and clipped','sharpen':'5*center - four neighbors, clipped'}[self.mode]
        if self.mode!='smooth':
            report['settings'].pop('video_kernel');report['settings'].pop('video_divisor')
        report['scope']['limitations']='One ARM then one FPGA run with fixed selected video mode; thermal/order/background load may affect results. Not optical/acoustic end-to-end latency.'
        try:
            from video_measure import measure_video
            from audio_benchmark import measure
            report['video_correctness']=measure_video(app.video_accelerator,app.root,self.mode)
            app.video_measurement=report['video_correctness']
            if self.cancel.is_set():raise InterruptedError('测试已停止')
            report['audio_correctness']=measure(engine,app.root,self._progress,repeats=3)
            for backend in ('ARM','FPGA'):
                if self.cancel.is_set():raise InterruptedError('测试已停止')
                video.select(self.mode);video.select_backend(backend)
                engine.command({'mode':0,'backend':backend},internal=True)
                before=cpu_ticks();previous=before;cpu_samples=[];began=time.monotonic()
                engine.command({'action':'play'},internal=True);video.start(clock=engine.playback_clock)
                while True:
                    if self.cancel.is_set():raise InterruptedError('测试已停止')
                    a=engine.snapshot();v=video.snapshot();wall=time.monotonic()-began
                    if a['status']=='error' or v['status']=='error':raise RuntimeError(a['error'] or v['error'])
                    ticks=cpu_ticks();cpu_samples.append({'wall_seconds':wall,'percent':cpu_percent(previous,ticks)});previous=ticks
                    self._progress(f'{backend} 分轮播放：{a["clock"]["seconds"]:.1f} / 30 秒，测试中锁定参数')
                    if a['status']=='idle' and v['status']=='ended':break
                    if wall>45:raise TimeoutError('分轮播放未按时结束')
                    self.cancel.wait(.5)
                if engine.thread:engine.thread.join(timeout=3)
                if video.thread:video.thread.join(timeout=3)
                a=engine.snapshot();v=video.snapshot();records=video.frame_records()
                expected=int(media['duration_seconds']*48000)+127
                if a['clock']['played']!=expected or a['clock']['underruns']:raise ValueError('音频未完整播放或存在欠载')
                row=summarize(backend,v,a,records,before,cpu_ticks(),time.monotonic()-began,self.mode)
                report['rounds'].append({'summary':row,'frames':records,'cpu_samples':cpu_samples})
                if self.cancel.wait(.5):raise InterruptedError('测试已停止')
            report['summary']={'rounds':[r['summary'] for r in report['rounds']],
                'video_max_error':report['video_correctness']['max_error'],
                'audio_max_error':max(r['max_error'] for r in report['audio_correctness']['modes']),
                'parameters':report['settings']}
            report['status']='done'
        except Exception as error:
            report.update(status='cancelled' if self.cancel.is_set() else 'error',error=str(error))
        finally:
            try:
                engine.command({'action':'stop'},internal=True);video.stop()
                if engine.thread:engine.thread.join(timeout=6)
                mode,backend,video_mode,video_backend=self.previous
                engine.command({'mode':mode,'backend':backend},internal=True)
                video.select_backend(video_backend);video.select(video_mode)
            except Exception as error:report.update(status='error',error=str(error))
            finally:engine.controls_locked=False
            path=app.root/'data'/('rounds_'+str(time.time_ns())+'.json');path.parent.mkdir(exist_ok=True)
            report['path']=str(path)
            try:path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as error:report.update(status='error',error='保存报告失败：'+str(error))
            with self.lock:
                self.report=report
                self.state.update(status=report['status'],result=report.get('summary'),error=report.get('error',''),
                    progress='两轮测试完成，记录已保存' if report['status']=='done' else report.get('error','测试结束'))
