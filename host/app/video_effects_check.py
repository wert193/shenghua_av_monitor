"""Exact actual-board verification for every implemented FPGA video effect."""
import json,time
import numpy as np
import cv2
from image_filters import filter_frame,arm_filter

def validate_effects(accelerator,root,movie=None):
    rng=np.random.default_rng(20261003)
    impulse=np.zeros((7,9,3),np.uint8);impulse[0,0]=255;impulse[3,4]=255;impulse[-1,-1]=255
    checker=((np.indices((240,320)).sum(axis=0)%2)*255).astype(np.uint8)
    frames=[rng.integers(0,256,(180,320,3),dtype=np.uint8),
        rng.integers(0,256,(240,320,3),dtype=np.uint8),
        np.zeros((180,320,3),np.uint8),np.full((180,320,3),255,np.uint8),
        np.full((1,1,3),(17,244,91),np.uint8),impulse,
        rng.integers(0,256,(1,19,3),dtype=np.uint8),
        rng.integers(0,256,(17,1,3),dtype=np.uint8),np.repeat(checker[:,:,None],3,axis=2)]
    if movie:
        cap=cv2.VideoCapture(str(movie))
        try:
            for index in (0,150,300):
                cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,frame=cap.read()
                if ok:
                    h,w=frame.shape[:2];scale=min(1,320/w,240/h)
                    if scale<1:frame=cv2.resize(frame,(round(w*scale),round(h*scale)))
                    frames.append(frame)
        finally:cap.release()
    result={'modes':[],'passed':False,'repeats':10,'warmup':3,
        'scope':'Same ARM implementation as live video. FPGA includes native padding/packing, DMA, and result unpacking. Excludes decoding, composition and HDMI.'}
    for mode in ('smooth','edge','sharpen','original'):
        if mode not in accelerator.modes:continue
        checks=[]
        for image in frames:
            expected=filter_frame(image,mode)
            actual,_=accelerator.process(image,mode)
            if actual.shape!=expected.shape:raise ValueError(mode+' output shape mismatch')
            error=int(np.max(np.abs(actual.astype(np.int16)-expected.astype(np.int16))))
            if error:raise ValueError(f'{mode} FPGA pixel error {error} at shape {image.shape}')
            if not np.array_equal(arm_filter(image,mode),expected):raise ValueError('ARM optimized result mismatch')
            checks.append({'shape':list(image.shape),'max_error':error})
        image=frames[0];expected=filter_frame(image,mode);times={'ARM':[],'FPGA':[]}
        for iteration in range(13):
            for backend in ('ARM','FPGA') if iteration%2==0 else ('FPGA','ARM'):
                began=time.perf_counter()
                out=arm_filter(image,mode) if backend=='ARM' else accelerator.process(image,mode)[0]
                elapsed=(time.perf_counter()-began)*1000
                if not np.array_equal(out,expected):raise ValueError(mode+' repeated frame mismatch')
                if iteration>=3:times[backend].append(elapsed)
        row={'mode':mode,'max_error':0,'checks':checks,'times_ms':times}
        for backend in times:row[backend]={'mean_ms':float(np.mean(times[backend])),'p95_ms':float(np.percentile(times[backend],95))}
        row['speedup']=row['ARM']['mean_ms']/row['FPGA']['mean_ms'];result['modes'].append(row)
    result['passed']=True
    path=root/'data'/('video_effects_'+str(time.time_ns())+'.json');path.parent.mkdir(exist_ok=True)
    result['report']=str(path);path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
