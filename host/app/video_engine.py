"""Decode uploaded video on the board and filter each displayed frame live on ARM."""
import hashlib
import json
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from image_filters import arm_filter
from hdmi_display import canvas_for_video

MODES=('original','smooth','edge','sharpen')
MAX_BYTES=100*1024*1024

class VideoEngine:
    def __init__(self,root,display=None,accelerator=None):
        self.root=Path(root)
        self.display=display
        self.accelerator=accelerator
        self.requested_backend='ARM'
        self.records=deque(maxlen=10000)
        self.lock=threading.RLock()
        self.changed=threading.Condition(self.lock)
        self.stop_event=threading.Event()
        self.thread=None
        self.clock=None
        self.file=None
        self.jpeg_bytes=b''
        self.state=dict(status='idle',mode='smooth',backend='ARM',source='',sha256='',
                        frame=0,frames_total=0,source_fps=0.0,fps=0.0,
                        filter_ms=0.0,display_ms=0.0,dropped=0,error='',version=0)
        marker=self.root/'video_current.json'
        saved=None
        if marker.exists():
            try:
                filename=json.loads(marker.read_text(encoding='utf-8'))['file']
                if filename==Path(filename).name:saved=self.root/filename
            except (ValueError,KeyError,TypeError):pass
        if saved:
            try:self.install(saved,saved.name)
            except Exception as error:self.state.update(status='error',error='已保存的视频无法打开：'+str(error))
        elif (self.root/'demo_motion.avi').exists():
            import shutil
            demo=self.root/'demo_input.avi'
            shutil.copyfile(self.root/'demo_motion.avi',demo)
            media=self.root/'media.json'
            info=json.loads(media.read_text(encoding='utf-8')) if media.exists() else {}
            label=info.get('title',info.get('source',''))+'（同源 MV 片段）' if info else '内置动态测试视频（30 秒）'
            self.install(demo,label)

    def snapshot(self):
        with self.lock:return dict(self.state)

    def frame_records(self):
        with self.lock:return list(self.records)

    def jpeg(self):
        with self.lock:return self.jpeg_bytes

    def wait_frame(self,version,timeout=2):
        with self.changed:
            self.changed.wait_for(lambda:self.state['version']!=version or self.state['status']!='playing',timeout)
            return self.state['version'],self.jpeg_bytes,self.state['status']

    def select(self,mode):
        if mode not in MODES:raise ValueError('未知视频模式')
        with self.lock:
            self.state['mode']=mode
            if self.accelerator is None or mode not in self.accelerator.modes:self.requested_backend='ARM'
            self.state['requested_backend']=self.requested_backend

    def select_backend(self,backend):
        if backend not in ('ARM','FPGA'):raise ValueError('未知视频后端')
        if backend=='FPGA' and self.accelerator is None:raise ValueError('当前硬件未包含视频滤波')
        with self.lock:
            self.requested_backend=backend
            self.state['requested_backend']=backend
            if backend=='FPGA' and self.state['mode'] not in self.accelerator.modes:self.state['mode']='smooth'

    def install(self,path,name):
        path=Path(path)
        if not path.is_file() or not 0<path.stat().st_size<=MAX_BYTES:raise ValueError('视频文件大小无效')
        cap=cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():raise ValueError('无法解码视频；请使用 H.264 MP4 或 MJPEG AVI')
            ok,frame=cap.read()
            if not ok or frame is None:raise ValueError('视频中没有可解码的画面')
            fps=float(cap.get(cv2.CAP_PROP_FPS))
            if not np.isfinite(fps) or fps<=0:fps=15.0
            fps=min(fps,60.0)
            total=max(0,int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        finally:cap.release()
        self.stop()
        dest=self.root/('uploaded_video'+path.suffix.lower())
        if path.resolve()!=dest.resolve():path.replace(dest)
        digest=hashlib.sha256()
        with dest.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        sha=digest.hexdigest()
        with self.lock:
            self.file=dest
            self.jpeg_bytes=b''
            self.state.update(status='ready',source=name,sha256=sha,source_fps=round(fps,2),
                              frames_total=total,frame=0,fps=0.0,filter_ms=0.0,
                              display_ms=0.0,dropped=0,error='',version=self.state['version']+1)
            self.changed.notify_all()
        (self.root/'video_current.json').write_text(json.dumps({'file':dest.name},ensure_ascii=False),encoding='utf-8')
        return self.snapshot()

    def start(self,clock=None):
        with self.lock:
            if self.file is None:raise ValueError('请先上传视频')
            if self.thread and self.thread.is_alive():raise ValueError('视频正在播放')
            self.stop_event.clear()
            self.records.clear()
            self.clock=clock
            self.state.update(status='playing',error='',frame=0,dropped=0,fps=0.0)
            self.state.update(synchronized=clock is not None,sync_error_ms=0.0)
            self.thread=threading.Thread(target=self._run,daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        worker=self.thread
        if worker and worker.is_alive() and worker is not threading.current_thread():worker.join(timeout=3)
        if worker and worker.is_alive():raise RuntimeError('视频线程仍在运行')
        with self.changed:
            if self.state['status']=='playing':self.state['status']='ready'
            self.changed.notify_all()

    def _run(self):
        cap=cv2.VideoCapture(str(self.file))
        if not cap.isOpened():
            with self.changed:self.state.update(status='error',error='视频打开失败');self.changed.notify_all()
            return
        fps=self.state['source_fps'] or 15.0
        period=1/fps
        began=time.monotonic()
        shown=0
        rendered=0
        dropped=0
        pipeline_estimate=.14
        display_estimate=.04
        try:
            while not self.stop_event.is_set():
                if self.clock:
                    clock=self.clock()
                    if clock['error'] or clock['underruns']:raise RuntimeError(clock['error'] or '音频硬件出现缺样，已停止同步播放')
                    if not clock['started']:
                        if time.monotonic()-began>10:raise TimeoutError('音频时钟未启动')
                        self.stop_event.wait(.01);continue
                    if clock['finished']:break
                    elapsed=clock['seconds']
                else:elapsed=time.monotonic()-began
                work_start=time.monotonic()
                # Pick the frame covering the expected presentation time. Rounding
                # up forces an extra wait (and often skips another source frame).
                target=int((elapsed+pipeline_estimate)/period) if self.clock else int(elapsed/period)
                if self.clock and self.state['frames_total']:
                    target=min(target,self.state['frames_total']-1)
                if target>shown:
                    skip=target-shown
                    for _ in range(skip):
                        if not cap.grab():break
                    dropped+=skip;shown+=skip
                ok,frame=cap.read()
                if not ok:break
                shown+=1
                rendered+=1
                h,w=frame.shape[:2]
                scale=min(1.0,320/w,240/h)
                if scale<1:frame=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))))
                with self.lock:
                    mode=self.state['mode'];backend=self.requested_backend
                started=time.perf_counter()
                if backend=='FPGA':
                    result,_=self.accelerator.process(frame,mode)
                else:result=arm_filter(frame,mode)
                filter_ms=(time.perf_counter()-started)*1000
                compose_start=time.perf_counter()
                actual_fps=rendered/max(.001,time.monotonic()-began)
                canvas=canvas_for_video(frame,result,mode,shown,actual_fps,backend)
                ok,encoded=cv2.imencode('.jpg',canvas,[cv2.IMWRITE_JPEG_QUALITY,75])
                if not ok:raise RuntimeError('视频帧 JPEG 编码失败')
                prepare_seconds=time.monotonic()-work_start
                compose_ms=(time.perf_counter()-compose_start)*1000
                wait_start=time.perf_counter()
                if self.clock:
                    desired=(shown-1)/fps-display_estimate
                    while not self.stop_event.is_set():
                        current=self.clock()
                        if current['error'] or current['finished'] or current['seconds']>=desired:break
                        self.stop_event.wait(.003)
                    if self.stop_event.is_set() or current['finished']:break
                wait_ms=(time.perf_counter()-wait_start)*1000
                display_start=time.perf_counter()
                if self.display:
                    self.display.refresh_canvas(canvas)
                    if self.display.state['error']:raise RuntimeError(self.display.state['error'])
                display_ms=(time.perf_counter()-display_start)*1000
                pipeline_estimate=min(.4,.7*pipeline_estimate+.3*(prepare_seconds+display_ms/1000))
                display_estimate=.7*display_estimate+.3*display_ms/1000
                sync_error=0.0
                if self.clock:sync_error=((shown-1)/fps-self.clock()['seconds'])*1000
                with self.changed:
                    self.records.append(dict(frame=shown,backend=backend,mode=mode,
                        filter_ms=filter_ms,display_ms=display_ms,
                        prepare_ms=prepare_seconds*1000,sync_error_ms=sync_error))
                    self.jpeg_bytes=encoded.tobytes()
                    self.state.update(frame=shown,fps=round(actual_fps,2),
                                      backend=backend,requested_backend=self.requested_backend,
                                      filter_ms=round(filter_ms,3),display_ms=round(display_ms,3),
                                      prepare_ms=round(prepare_seconds*1000,3),
                                      compose_ms=round(compose_ms,3),wait_ms=round(wait_ms,3),
                                      dropped=dropped,sync_error_ms=round(sync_error,2),version=self.state['version']+1)
                    self.changed.notify_all()
                if self.clock:
                    continue
                delay=(began+shown*period)-time.monotonic()
                if delay>0:self.stop_event.wait(delay)
            with self.changed:
                self.state['status']='ready' if self.stop_event.is_set() else 'ended'
                self.changed.notify_all()
        except Exception as error:
            with self.changed:self.state.update(status='error',error=str(error));self.changed.notify_all()
        finally:cap.release()
