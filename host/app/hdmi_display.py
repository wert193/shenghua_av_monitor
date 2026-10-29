"""720p scanout of a 640x360 RGB332 double-buffered comparison canvas."""
import threading
import time
import cv2
import numpy as np

def canvas_for(image):
    canvas=np.full((360,640,3),(28,22,16),np.uint8)
    cv2.putText(canvas,'SHENGHUA  |  PYNQ-Z2',(16,27),cv2.FONT_HERSHEY_SIMPLEX,.65,(240,230,215),1,cv2.LINE_AA)
    state=image.snapshot()
    for x,which,label in ((12,'original','ORIGINAL'),(332,'processed',state.get('backend','ARM')+' / '+state['mode'].upper())):
        frame=cv2.imdecode(np.frombuffer(image.jpeg(which),np.uint8),cv2.IMREAD_COLOR)
        h,w=frame.shape[:2]; scale=min(296/w,230/h)
        frame=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))))
        h,w=frame.shape[:2]; left=x+(296-w)//2; top=68+(230-h)//2
        canvas[top:top+h,left:left+w]=frame
        cv2.putText(canvas,label,(x,56),cv2.FONT_HERSHEY_SIMPLEX,.5,(220,210,190),1,cv2.LINE_AA)
    cv2.line(canvas,(320,42),(320,310),(105,95,75),1)
    cv2.putText(canvas,'LIVE BOARD OUTPUT   |   IMAGE: '+state.get('backend','ARM'),(14,326),cv2.FONT_HERSHEY_SIMPLEX,.45,(180,190,180),1,cv2.LINE_AA)
    cv2.putText(canvas,'AUDIO: ARM / FPGA   |   CONTROL VIA WEB',(14,348),cv2.FONT_HERSHEY_SIMPLEX,.43,(180,190,180),1,cv2.LINE_AA)
    return canvas

def canvas_for_video(original, processed, mode, index, fps, backend='ARM'):
    canvas=np.full((360,640,3),(28,22,16),np.uint8)
    cv2.putText(canvas,'SHENGHUA  |  LIVE VIDEO',(16,27),cv2.FONT_HERSHEY_SIMPLEX,.65,(240,230,215),1,cv2.LINE_AA)
    for x,frame,label in ((12,original,'ORIGINAL'),(332,processed,backend+' / '+mode.upper())):
        h,w=frame.shape[:2]; scale=min(296/w,230/h)
        frame=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))))
        h,w=frame.shape[:2]; left=x+(296-w)//2; top=68+(230-h)//2
        canvas[top:top+h,left:left+w]=frame
        cv2.putText(canvas,label,(x,56),cv2.FONT_HERSHEY_SIMPLEX,.5,(220,210,190),1,cv2.LINE_AA)
    cv2.line(canvas,(320,42),(320,310),(105,95,75),1)
    cv2.putText(canvas,'FRAME %d   |   %.1f FPS   |   VIDEO: %s'%(index,fps,backend),(14,327),cv2.FONT_HERSHEY_SIMPLEX,.48,(180,190,180),1,cv2.LINE_AA)
    cv2.putText(canvas,'HDMI: FPGA SCANOUT   |   AUDIO: ARM / FPGA',(14,348),cv2.FONT_HERSHEY_SIMPLEX,.43,(180,190,180),1,cv2.LINE_AA)
    return canvas

def pack_frame(canvas):
    if canvas.shape!=(360,640,3) or canvas.dtype!=np.uint8: raise ValueError('Invalid HDMI canvas')
    b,g,r=cv2.split(canvas)
    packed=(r&0xe0)|((g>>3)&0x1c)|(b>>6)
    return np.ascontiguousarray(packed).reshape(-1).view('<u4')

class HdmiDisplay:
    def __init__(self,overlay,mmio_factory=None):
        # AXI BRAM is a memory in PYNQ's HWH parser, not necessarily an IP.
        # Open its verified physical range directly instead of overlay.screen_bram.
        if mmio_factory is None:
            from pynq import MMIO
            mmio_factory=MMIO
        self.memory=mmio_factory(0x42000000,0x80000,device=overlay.device).array
        self.control=overlay.screen_control
        self.lock=threading.Lock()
        self.state={'status':'ready','format':'1280x720 / 60 Hz','canvas':'640x360 RGB332','error':'','frames':0}
    def refresh(self,image):
        self.refresh_canvas(canvas_for(image))
    def refresh_canvas(self,canvas):
        with self.lock:
            try:
                words=pack_frame(canvas)
                bank=1-(self.control.read(8)&1)
                offset=bank*65536
                self.memory[offset:offset+len(words)]=words
                request=bank|2
                self.control.write(0,request)
                deadline=time.monotonic()+1
                while self.control.read(8)&3!=request:
                    if time.monotonic()>deadline: raise TimeoutError('HDMI 帧切换超时')
                    time.sleep(.002)
                self.state.update(status='output_active',error='',frames=self.state['frames']+1)
            except Exception as error:
                self.state.update(status='error',error=str(error))
    def snapshot(self): return dict(self.state)
