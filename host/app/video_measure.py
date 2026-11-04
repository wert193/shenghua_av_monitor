"""Board-side exact pixel verification and matched smooth-filter timings."""
import json,time,hashlib
import numpy as np
import cv2
from image_filters import arm_filter,benchmark_frame,ARM_IMPLEMENTATION
def measure_video(accelerator,root,mode='smooth'):
    if mode not in ('smooth','edge','sharpen') or mode not in accelerator.modes:raise ValueError('不支持的 FPGA 测量模式')
    rng=np.random.default_rng(42)
    frames=[benchmark_frame(),
            np.zeros((180,320,3),np.uint8),np.full((180,320,3),255,np.uint8),
            rng.integers(0,256,(7,13,3),dtype=np.uint8)]
    errors=[]
    for image in frames:
        expected=arm_filter(image,mode)
        actual,_=accelerator.process(image,mode)
        errors.append(int(np.abs(actual.astype(np.int16)-expected.astype(np.int16)).max()))
    if max(errors):raise RuntimeError('FPGA pixel mismatch: '+str(errors))
    image=frames[0];times={'ARM':[],'FPGA':[]};expected=arm_filter(image,mode)
    for i in range(23):
        for backend in ('ARM','FPGA') if i%2==0 else ('FPGA','ARM'):
            began=time.perf_counter()
            actual=arm_filter(image,mode) if backend=='ARM' else accelerator.process(image,mode)[0]
            elapsed=(time.perf_counter()-began)*1000
            if i>=3:times[backend].append(elapsed)
            if not np.array_equal(expected,actual):raise RuntimeError('Repeated pixel mismatch')
    result={'mode':mode,'size':[320,180],'warmup':3,'repeats':20,'max_error':max(errors),
            'source_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'arm_implementation':ARM_IMPLEMENTATION,
            'scope':'Filter call; FPGA includes padding, packing, DMA and copy. Excludes decoding, composition, HDMI and audio.',
            'times_ms':times}
    for backend,values in times.items():result[backend]={'mean_ms':float(np.mean(values)),'p95_ms':float(np.percentile(values,95))}
    result['speedup']=result['ARM']['mean_ms']/result['FPGA']['mean_ms']
    dest=root/'data'/('video_'+mode+'_'+str(time.time_ns())+'.json');dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['report']=str(dest)
    return result

def measure_uploaded_video(accelerator,root,path,source_sha256,mode='smooth',sample_count=20):
    """Compare both filters on identical, evenly spaced frames from an upload."""
    if mode not in ('smooth','edge','sharpen') or mode not in accelerator.modes:
        raise ValueError('当前 FPGA 不支持所选视频效果')
    capture=cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError('无法重新打开已上传视频')
    try:
        total=max(0,int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        if total<=0:
            raise ValueError('视频没有可供对比的帧')
        count=min(sample_count,total)
        indices=np.unique(np.linspace(0,total-1,count,dtype=np.int64))
        frames=[]
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES,int(index))
            ok,frame=capture.read()
            if not ok or frame is None:
                continue
            h,w=frame.shape[:2]
            scale=min(1.0,320/w,240/h)
            if scale<1:
                frame=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))),
                                 interpolation=cv2.INTER_AREA)
            frames.append((int(index),frame))
    finally:
        capture.release()
    if not frames:
        raise ValueError('无法从视频中读取可处理画面')

    times={'ARM':[],'FPGA':[]}
    errors=[]
    for _,frame in frames[:min(3,len(frames))]:
        arm_filter(frame,mode)
        accelerator.process(frame,mode)
    for index,frame in frames:
        expected=arm_filter(frame,mode)
        began=time.perf_counter()
        if index%2:
            actual,_=accelerator.process(frame,mode)
            times['FPGA'].append((time.perf_counter()-began)*1000)
            began=time.perf_counter();reference=arm_filter(frame,mode)
            times['ARM'].append((time.perf_counter()-began)*1000)
        else:
            reference=arm_filter(frame,mode)
            times['ARM'].append((time.perf_counter()-began)*1000)
            began=time.perf_counter();actual,_=accelerator.process(frame,mode)
            times['FPGA'].append((time.perf_counter()-began)*1000)
        errors.append(int(np.abs(actual.astype(np.int16)-expected.astype(np.int16)).max()))
        if not np.array_equal(reference,expected):
            raise RuntimeError('ARM 结果校验不一致')

    result={'mode':mode,'source_sha256':source_sha256,'source_frames':total,
            'sampled_frames':len(frames),'sampled_indices':[i for i,_ in frames],
            'warmup_frames':min(3,len(frames)),
            'scope':'Same decoded frames; filter call only. FPGA includes packing, DMA and result copy; excludes decode, network, composition and HDMI.',
            'arm_implementation':ARM_IMPLEMENTATION,'max_error':max(errors)}
    for backend,values in times.items():
        result[backend]={'mean_ms':float(np.mean(values)),
                         'p95_ms':float(np.percentile(values,95)),
                         'filter_fps':float(1000/np.mean(values))}
    result['speedup']=result['ARM']['mean_ms']/result['FPGA']['mean_ms']
    dest=root/'data'/('uploaded_video_'+mode+'_'+str(time.time_ns())+'.json')
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['report']=str(dest)
    return result
