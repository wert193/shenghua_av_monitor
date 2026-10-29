"""Halo-tiled static images using the existing FPGA video filter only."""
import time
import numpy as np

class ImageFpga:
    def __init__(self,video):self.video=video;self.modes=video.modes
    def process(self,frame,mode):
        if frame.shape[0]<=240 and frame.shape[1]<=320:return self.video.process(frame,mode)
        began=time.perf_counter();h,w=frame.shape[:2];output=np.empty_like(frame)
        # Only true image boundaries use replicated padding. Tile edges have
        # real neighbors; crop the halo after hardware convolution.
        for y in range(0,h,238):
            for x in range(0,w,318):
                bottom=min(h,y+238);right=min(w,x+318)
                top=max(0,y-1);left=max(0,x-1)
                filtered,_=self.video.process(frame[top:min(h,bottom+1),left:min(w,right+1)],mode)
                output[y:bottom,x:right]=filtered[y-top:bottom-top,x-left:right-left]
        return output,(time.perf_counter()-began)*1000
