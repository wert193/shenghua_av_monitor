"""Streaming FPGA video filters, sharing DMA under the audio driver lock."""
import time
import ctypes
import json
import subprocess
from pathlib import Path
import numpy as np
import cv2

class VideoFpga:
    def __init__(self,driver,allocate):
        self.driver=driver
        self.input=allocate(shape=((320+2)*(240+2),),dtype=np.uint32)
        self.output=allocate(shape=(320*240,),dtype=np.uint32)
        self.failed=False
        config=Path(__file__).with_name('video_effects.json')
        self.modes=json.loads(config.read_text())['modes'] if config.exists() else {'smooth':0}
        source=Path(__file__).with_name('video_pack.c')
        library=source.with_suffix('.so')
        if not library.exists() or library.stat().st_mtime<source.stat().st_mtime:
            subprocess.run(['gcc','-O3','-shared','-fPIC',str(source),'-o',str(library)],check=True,timeout=30,capture_output=True)
        self.native=ctypes.CDLL(str(library))
        self.native.video_pack.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint]
        self.native.video_unpack.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
        self.native.video_pack.restype=None;self.native.video_unpack.restype=None

    def process(self,frame,mode='smooth'):
        if mode not in self.modes:raise ValueError('当前 FPGA 不支持视频模式：'+mode)
        if frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3:
            raise ValueError('Expected BGR uint8 frame')
        h,w=frame.shape[:2]
        if not 0<w<=320 or not 0<h<=240:raise ValueError('FPGA video limit is 320x240')
        with self.driver.lock:
            if self.failed:raise RuntimeError('Video DMA fault; restart the application before reuse')
            began=time.perf_counter()
            n=(h+2)*(w+2);count=h*w
            source=np.ascontiguousarray(frame)
            self.native.video_pack(source.ctypes.data,self.input.ctypes.data,w,h)
            self.input.flush();self.output.flush()
            dma=self.driver.dma;control=self.driver.video_control
            src=int(self.input.physical_address);dst=int(self.output.physical_address)
            if src+n*4>2**32 or dst+count*4>2**32:raise ValueError('DMA address exceeds 32 bits')
            # Changing back to audio clears video counters before a new frame.
            control.write(0,0);control.write(0,0x80000000|(self.modes[mode]<<20)|w)
            try:
                dma.write(0x04,0x7000);dma.write(0x34,0x7000)
                dma.write(0x48,dst);dma.write(0x58,count*4)
                dma.write(0x18,src);dma.write(0x28,n*4)
                deadline=time.monotonic()+.5
                while True:
                    tx=dma.read(4);rx=dma.read(0x34)
                    if (tx|rx)&0x770:raise RuntimeError(f'Video DMA fault: {tx:#x}, {rx:#x}')
                    if tx&2 and rx&2:break
                    if time.monotonic()>deadline:raise TimeoutError('Video DMA timeout')
                    time.sleep(.0001)
                self.output.invalidate()
                out=np.empty((h,w,3),np.uint8)
                self.native.video_unpack(self.output.ctypes.data,out.ctypes.data,count)
            except Exception:
                self.failed=True
                self.driver._reset()
                dma.write(0,1);dma.write(0x30,1)
                raise
            finally:control.write(0,0)
            return out,(time.perf_counter()-began)*1000

    def close(self):
        with self.driver.lock:
            self.input.freebuffer();self.output.freebuffer()
