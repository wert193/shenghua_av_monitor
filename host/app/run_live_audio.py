"""Combined-overlay live audio prototype; restores base on notebook interrupt."""
from pathlib import Path
import asyncio
import ctypes
import hashlib
import json
import os
import select
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from fir_driver import FirDriver
from check_hardware import check_reset

ROOT=Path(__file__).resolve().parent
BLOCK=4096

class Engine:
    def __init__(self, overlay, driver, song, uio, reference):
        self.overlay,self.driver,self.song,self.uio,self.reference=overlay,driver,song,uio,reference
        self.default_song=Path(song)
        self.uploaded_source=False
        self.source_name='等待上传现场视频音轨'
        self.lock=threading.RLock()
        self.stop_event=threading.Event()
        self.thread=None
        self.fifo_mmio=None
        self.clock_seen=False
        self.controls_locked=False
        self.state=dict(status='idle', mode=3, backend='FPGA', applied_mode=3,
                        applied_backend='', elapsed=0, compute_ms=0, blocks=0, error='',events=[],last_log='')
        self.coeff=np.asarray(json.loads((ROOT/'coefficients.json').read_text())['coefficients'],np.int32)

    def use_uploaded_source(self, path, name):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('请先停止当前音频播放，再载入视频音轨。')
            self.song=Path(path)
            self.uploaded_source=True
            self.source_name=str(name)

    def restore_default_source(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('请先停止当前音频播放。')
            self.song=self.default_song
            self.uploaded_source=False
            self.source_name='等待上传现场视频音轨'

    def snapshot(self):
        with self.lock:
            state=json.loads(json.dumps(self.state))
            state['source_name']=self.source_name
            state['uploaded_source']=self.uploaded_source
            if self.fifo_mmio is not None:state['clock']=self.playback_clock()
            return state

    def playback_clock(self):
        if self.fifo_mmio is None:return None
        flags=int(self.fifo_mmio[4])
        if flags&2:self.clock_seen=True
        played=int(self.fifo_mmio[0]) if self.clock_seen else 0
        return dict(seconds=max(0,played-127)/48000,played=played,
                    underruns=int(self.fifo_mmio[1]),level=int(self.fifo_mmio[2]),
                    started=self.clock_seen,finished=self.clock_seen and not bool(flags&2),
                    error=self.state.get('error',''))

    def update(self, **values):
        with self.lock: self.state.update(values)

    def command(self, command, internal=False):
        with self.lock:
            if self.controls_locked and not internal:raise ValueError('分轮测试正在运行，请先停止测试')
            if 'mode' in command:
                mode=command['mode']
                if type(mode) is not int or mode not in range(4): raise ValueError('Invalid mode')
                self.state['mode']=mode
            if 'backend' in command:
                if command['backend'] not in ('ARM','FPGA'): raise ValueError('Invalid backend')
                self.state['backend']=command['backend']
            if command.get('action')=='stop':
                self.stop_event.set()
                if self.state['status'] in ('starting','running'): self.state['status']='stopping'
            if command.get('action')=='play':
                if self.thread and self.thread.is_alive(): raise ValueError('播放尚未结束')
                self.stop_event.clear()
                self.clock_seen=False
                self.update(status='starting',error='',blocks=0,elapsed=0,events=[],last_log='')
                self.thread=threading.Thread(target=self.play,daemon=True)
                self.thread.start()

    def compute(self, x, mode, backend):
        if backend=='FPGA': return self.driver.process(x,mode,True)[0]
        out=np.empty_like(x); history=np.zeros(256,np.int16); head=ctypes.c_uint()
        self.reference(x,out,len(x),self.coeff[mode],history,ctypes.byref(head),1)
        return out

    def play(self):
        p=None
        logpath=ROOT/('playback_'+str(time.time_ns())+'.log')
        try:
            song=np.fromfile(self.song,dtype='<i2').astype(np.int32)//2
            # Each block includes real preceding samples. This makes backend and
            # mode changes independent of hidden fpga/src/software history.
            padded=np.concatenate((np.zeros(255,np.int32),song,np.zeros(127,np.int32)))
            previous=None
            with logpath.open('w') as log:
                args=[str(ROOT/'pcm_sink'),self.uio,'/dev/i2c-1','65536']
                if self.fifo_mmio is not None:args.append(str(len(song)+127))
                p=subprocess.Popen(args,
                    stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,bufsize=0)
                os.set_blocking(p.stdin.fileno(),False)
                self.update(status='running')
                for start in range(0,len(song)+127,BLOCK):
                    if self.stop_event.is_set(): break
                    state=self.snapshot(); current=(state['mode'],state['backend'])
                    n=min(BLOCK,len(song)+127-start)
                    x=np.ascontiguousarray(padded[start:start+n+255])
                    began=time.perf_counter()
                    out=self.compute(x,*current)[255:]
                    if previous is not None and current!=previous:
                        old=self.compute(x,*previous)[255:]
                        fade=min(960,n)
                        alpha=np.arange(1,fade+1,dtype=np.float64)/fade
                        out[:fade]=np.rint(old[:fade]*(1-alpha)+out[:fade]*alpha).astype(np.int32)
                    previous=current
                    indices=np.arange(start,start+n)
                    envelope=np.minimum(1,np.minimum(indices/2400,(len(song)+126-indices)/2400))
                    out=np.rint(out*np.maximum(0,envelope)).astype('<i4')
                    compute_ms=(time.perf_counter()-began)*1000
                    data=memoryview(out).cast('B'); deadline=time.monotonic()+3
                    while data and not self.stop_event.is_set():
                        if p.poll() is not None: raise RuntimeError('音频输出进程退出')
                        if time.monotonic()>deadline: raise TimeoutError('音频输出等待超时')
                        if not select.select([], [p.stdin], [], .1)[1]: continue
                        try: count=os.write(p.stdin.fileno(),data)
                        except BlockingIOError: continue
                        data=data[count:]
                    self.update(applied_mode=current[0],applied_backend=current[1],
                        elapsed=round((start+n)/48000,2),compute_ms=round(compute_ms,3),blocks=start//BLOCK+1)
                p.stdin.close()
                if self.stop_event.is_set(): p.terminate()
                p.wait(timeout=5)
                if p.returncode: raise RuntimeError('音频输出失败：'+logpath.read_text()[-1200:])
            self.update(status='idle')
        except Exception as error:
            self.update(status='error',error=str(error))
        finally:
            if p and p.poll() is None:
                p.terminate()
                try: p.wait(timeout=3)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
            self.update(log=str(logpath))
            if logpath.exists(): self.update(last_log=logpath.read_text()[-2500:])
            (ROOT/('session_'+str(time.time_ns())+'.json')).write_text(
                json.dumps(self.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')

    def buttons(self, exiting):
        candidate=stable=0; since=time.monotonic()
        while not exiting.wait(.02):
            if self.controls_locked:continue
            value=self.overlay.btns_gpio.read(0)&15
            if value!=candidate: candidate=value; since=time.monotonic()
            if time.monotonic()-since>.04 and candidate!=stable:
                old,stable=stable,candidate
                if old==0 and stable in (1,2,4,8):
                    display_button=False
                    if stable==8:
                        live_monitor=getattr(self,'live_monitor',None)
                        if live_monitor is not None and live_monitor.snapshot()['active']:
                            live_monitor.toggle_display()
                            display_button=True
                        else:
                            backend='ARM' if self.snapshot()['backend']=='FPGA' else 'FPGA'
                            self.command({'backend':backend})
                    else:
                        live_monitor=getattr(self,'live_monitor',None)
                        mode={1:0,2:1,4:2}[stable]
                        if live_monitor is not None and live_monitor.snapshot()['active']:
                            live_monitor.select_physical_mode(mode)
                        else:
                            self.command({'mode':mode})
                    if not display_button:
                        with self.lock:
                            self.state['events'].append({'seconds':self.state['elapsed'],'button':{1:0,2:1,4:2,8:3}[stable],'backend':self.state['backend']})
            self.overlay.leds_gpio.write(0,1<<self.snapshot()['applied_mode'])

PAGE='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>音视频监控系统 · 实时音频</title><style>body{max-width:850px;margin:50px auto;padding:20px;background:#101925;color:#e6efff;font:18px system-ui}button{padding:15px;margin:6px;border:0;border-radius:9px;cursor:pointer}pre{white-space:pre-wrap;background:#1d2d42;padding:20px}small{color:#b2c4da}</style>
<h1>Closer · ARM / FPGA 实时滤波</h1><p>演示片段：原曲 00:30—01:00，共 30 秒</p><p>BTN0 低通 · BTN1 高通 · BTN2 带通 · BTN3 切换 ARM / FPGA</p>
<button onclick="cmd({action:'play'})">播放</button><button onclick="cmd({action:'stop'})">停止</button><br>
<button onclick="cmd({mode:3})">原曲（延时对齐）</button><button onclick="cmd({mode:0})">低通 800 Hz</button><button onclick="cmd({mode:1})">高通 3000 Hz</button><button onclick="cmd({mode:2})">带通 800–2500 Hz</button><br>
<button onclick="cmd({backend:'ARM'})">ARM 计算</button><button onclick="cmd({backend:'FPGA'})">FPGA 计算</button>
<pre id="status">连接中…</pre><small>歌曲在开发板处理并从音响播放。此版验证实时音频；HDMI 和图像界面尚未合入。计算耗时包含分块处理，不代表端到端声音延迟。</small>
<script>async function cmd(x){try{let r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(x)});if(!r.ok)alert(await r.text())}catch(e){alert(e)}}async function tick(){try{let r=await fetch('/api/status');let s=await r.json();document.getElementById('status').textContent='状态：'+s.status+'\\n当前后端：'+s.applied_backend+' → 请求：'+s.backend+'\\n模式：'+['低通','高通','带通','原曲'][s.applied_mode]+'\\n已提交音频：'+s.elapsed+' 秒\\n最近一块计算：'+s.compute_ms+' ms\\n'+(s.error||'')}catch(e){document.getElementById('status').textContent='服务未连接'}setTimeout(tick,500)}tick();</script>'''

def main():
    from pynq import Overlay,allocate
    from pynq.overlays.base import BaseOverlay
    import pynq.lib.audio as audio_module
    check_reset(ROOT/'audio_live.hwh')
    song=ROOT/'closer_clip.s16le'
    meta=json.loads((ROOT/'clip.json').read_text())
    if hashlib.sha256(song.read_bytes()).hexdigest()!=meta['sha256']:
        raise RuntimeError('演示片段校验失败')
    for source,target,args in (
            ('pcm_sink.c','pcm_sink',[]),
            ('pcm_stream_sink.c','pcm_stream',[]),
            ('reference.c','reference.so',['-shared','-fPIC'])):
        path=ROOT/source
        if path.exists():
            try:
                subprocess.run(['gcc','-O3','-Wall','-Wextra',*args,str(path),'-o',str(ROOT/target)],
                               check=True,timeout=60)
            except subprocess.CalledProcessError as error:
                if target!='pcm_stream':
                    raise
                print('板载监听程序编译失败；摄像头与音频分析仍可使用：',error,flush=True)
    lib=ctypes.CDLL(str(ROOT/'reference.so'))
    vec=np.ctypeslib.ndpointer(dtype=np.int32,ndim=1,flags='C_CONTIGUOUS')
    hist=np.ctypeslib.ndpointer(dtype=np.int16,ndim=1,flags='C_CONTIGUOUS')
    lib.fir_reference.argtypes=[vec,vec,ctypes.c_uint,vec,hist,ctypes.POINTER(ctypes.c_uint),ctypes.c_int]
    lib.fir_reference.restype=None
    uios=[p for p in Path('/sys/class/uio').glob('uio*') if (p/'name').read_text().strip()=='audio-codec-ctrl']
    if len(uios)!=1 or int((uios[0]/'maps/map0/addr').read_text(),0)!=0x43c00000:
        raise RuntimeError('音频 UIO 地址不匹配，尚未加载 FPGA。')
    driver=server=engine=None; exiting=threading.Event(); buttons=None; changed=False
    try:
        changed=True
        overlay=Overlay(str(ROOT/'audio_live.bit'))
        driver=FirDriver(overlay,allocate,BLOCK+255)
        codec=ctypes.CDLL(str(Path(audio_module.__file__).parent/'libaudio.so'))
        for name in ('config_audio_pll','config_audio_codec'):
            fn=getattr(codec,name); fn.argtypes=[ctypes.c_int]; fn.restype=None; fn(1)
        engine=Engine(overlay,driver,song,'/dev/'+uios[0].name,lib.fir_reference)
        if (ROOT/'avsync.json').exists():
            from pynq import MMIO
            import cv2
            cv2.setNumThreads(1)
            cv2.ocl.setUseOpenCL(False)
            engine.fifo_mmio=MMIO(0x43c00000,65536,device=overlay.device).array
            if int(engine.fifo_mmio[3])!=0x53414631:raise RuntimeError('音频 FIFO 硬件签名不匹配')
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                data=json.dumps(engine.snapshot(),ensure_ascii=False).encode() if self.path=='/api/status' else PAGE.encode()
                self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8' if self.path=='/api/status' else 'text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_POST(self):
                try:
                    if self.path!='/api/command': raise ValueError('Unknown endpoint')
                    n=int(self.headers.get('Content-Length','0'))
                    if not 0<n<=1024: raise ValueError('Invalid request length')
                    engine.command(json.loads(self.rfile.read(n)))
                    self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
                except Exception as error:
                    self.send_response(400); self.end_headers(); self.wfile.write(str(error).encode())
        if (ROOT/'video_app.py').exists():
            from video_app import make_handler
            Handler=make_handler(ROOT,engine)
        elif (ROOT/'integrated_app.py').exists():
            from integrated_app import make_handler
            Handler=make_handler(ROOT,engine)
        server=ThreadingHTTPServer(('0.0.0.0',8080),Handler)
        if hasattr(Handler,'application'):
            Handler.application.project_root=ROOT
            Handler.application.server_pid=os.getpid()
        buttons=threading.Thread(target=engine.buttons,args=(exiting,),daemon=True); buttons.start()
        print('已启动 ARM / FPGA 实时音频页面；请访问开发板地址的 8080 端口。',flush=True)
        print('此单元保持运行是正常的。页面点播放；结束整个服务请用 Kernel → Interrupt。',flush=True)
        server.serve_forever(poll_interval=.2)
    finally:
        exiting.set()
        if server and hasattr(server.RequestHandlerClass,'application'):
            server.RequestHandlerClass.application.close()
        if engine:
            engine.stop_event.set()
            if engine.thread: engine.thread.join(timeout=10)
            if engine.thread and engine.thread.is_alive(): raise RuntimeError('播放线程未退出，请重启板子，勿加载其他 FPGA 配置。')
        if buttons: buttons.join(timeout=2)
        if server: server.server_close()
        if driver: driver.close()
        if changed:
            BaseOverlay('base.bit',download=True)
            print('已恢复 base 配置。',flush=True)

if __name__=='__main__': main()
