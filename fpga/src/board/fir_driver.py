"""Bounded synchronous PYNQ DMA driver for the standalone FIR overlay."""
import time
import threading
import numpy as np

class FirDriver:
    def __init__(self, overlay, allocate, capacity=16384, mmio_factory=None):
        self.lock=threading.RLock()
        self.video_control=getattr(overlay,'video_control',None) if 'video_control' in overlay.ip_dict else None
        self.ip=overlay.audio_fir_0
        # PYNQ's DMA constructor can poll indefinitely while starting channels.
        # Bind registers directly and put deadlines on all software polling.
        if mmio_factory is None:
            from pynq import MMIO
            mmio_factory=MMIO
        info=overlay.ip_dict['axi_dma_0']
        self.dma=mmio_factory(info['phys_addr'],info['addr_range'])
        print('DMA：复位并启动通道（软件轮询限时 2 秒）',flush=True)
        self._reset()
        self.dma.write(0x00,1)
        self.dma.write(0x30,1)
        deadline=time.monotonic()+2
        while self.dma.read(0x04)&1 or self.dma.read(0x34)&1:
            if time.monotonic()>deadline: raise TimeoutError('DMA initialization timeout; '+self.status())
            time.sleep(.001)
        print('DMA 通道已启动，申请连续内存',flush=True)
        self.input=allocate(shape=(capacity,), dtype=np.int32)
        self.output=allocate(shape=(capacity,), dtype=np.int32)
        self.capacity=capacity

    def status(self):
        return ' '.join(f'{off:#04x}={self.dma.read(off):#010x}' for off in (0,4,0x30,0x34))

    def _reset(self):
        self.dma.write(0,4)
        deadline=time.monotonic()+2
        while self.dma.read(0)&4:
            if time.monotonic()>deadline: raise TimeoutError('DMA reset timeout; '+self.status())
            time.sleep(.001)

    def process(self, samples, mode, reset=True, timeout=2.0):
        with self.lock:
            if self.video_control is not None:self.video_control.write(0,0)
            return self._process(samples,mode,reset,timeout)

    def _process(self, samples, mode, reset=True, timeout=2.0):
        x=np.asarray(samples)
        if x.ndim!=1 or not 0<len(x)<=self.capacity or x.dtype.kind not in 'iu':
            raise ValueError('Expected a nonempty integer PCM16 vector within capacity')
        if int(x.min())< -32768 or int(x.max())>32767 or type(mode) is not int or mode not in range(4):
            raise ValueError('Invalid PCM16 values or mode')
        n=len(x)
        self.input[:n]=x
        start=time.perf_counter()
        self.input.flush()
        self.output.flush()
        src=int(self.input.physical_address)
        dst=int(self.output.physical_address)
        if src+n*4>2**32 or dst+n*4>2**32:
            raise ValueError('DMA buffer must be in 32-bit address space')
        self.dma.write(0x04,0x7000)
        self.dma.write(0x34,0x7000)
        self.ip.write(0x10,n)
        self.ip.write(0x18,mode)
        self.ip.write(0x20,int(reset))
        # Arm the sink before the source. HLS marks exactly the final output TLAST.
        self.dma.write(0x48,dst)
        self.dma.write(0x58,n*4)
        self.ip.write(0,1)
        self.dma.write(0x18,src)
        self.dma.write(0x28,n*4)
        deadline=time.monotonic()+timeout
        while True:
            tx=self.dma.read(0x04)
            rx=self.dma.read(0x34)
            if (tx|rx)&0x770:
                raise RuntimeError(f'DMA error: MM2S={tx:#x}, S2MM={rx:#x}')
            if (tx&2) and (rx&2):
                break
            if time.monotonic()>deadline:
                raise TimeoutError(f'DMA timeout: MM2S={tx:#x}, S2MM={rx:#x}')
            time.sleep(0.0001)
        self.output.invalidate()
        elapsed=time.perf_counter()-start
        return np.asarray(self.output[:n]).copy(),elapsed

    def close(self):
        # Reset both channels with a deadline before releasing DMA-owned memory.
        self._reset()
        self.input.freebuffer()
        self.output.freebuffer()
