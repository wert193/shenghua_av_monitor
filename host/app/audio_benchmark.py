"""Repeatable compute-only comparison; no codec output or prerecorded results."""
import hashlib
import json
import time
from pathlib import Path
import numpy as np

def measure(engine, root, progress, repeats=20):
    root=Path(root)
    x=np.fromfile(engine.song,dtype='<i2',count=4096).astype(np.int32)//2
    if len(x)!=4096: raise ValueError('音频片段不足 4096 个采样')
    folder=root/'data'/('audio_benchmark_'+str(time.time_ns()))
    folder.mkdir(parents=True)
    report=dict(scope='compute_only_4096_pcm_samples',samples=len(x),sample_rate=48000,
        warmups=3,repeats=repeats,input_sha256=hashlib.sha256(x.tobytes()).hexdigest(),
        coefficients_sha256=hashlib.sha256(engine.coeff.tobytes()).hexdigest(),modes=[],passed=False,
        timing_scope='Wall time around Engine.compute: ARM includes allocation, ctypes and C FIR; FPGA includes register setup, cache maintenance, DMA, polling and output copy. Both reset history. Excludes file I/O, playback, mixing and display. Not end-to-end latency.',
        error_unit='PCM16 integer sample',p95_method='numpy.percentile linear interpolation')
    np.save(folder/'input.npy',x)
    try:
        for mode,name in enumerate(('低通','高通','带通','原曲延时对齐')):
            progress(f'{name}：预热与测量')
            expected=np.clip((np.convolve(x.astype(np.int64),engine.coeff[mode].astype(np.int64))[:len(x)]+16384)//32768,-32768,32767).astype(np.int32)
            times={'ARM':[],'FPGA':[]}; error=0
            for iteration in range(3+repeats):
                for backend in (('ARM','FPGA') if iteration%2==0 else ('FPGA','ARM')):
                    if engine.stop_event.is_set(): raise RuntimeError('测量已取消')
                    start=time.perf_counter()
                    output=engine.compute(x,mode,backend)
                    duration=(time.perf_counter()-start)*1000
                    if output.shape!=expected.shape: raise ValueError('输出长度不一致')
                    delta=int(np.max(np.abs(output.astype(np.int64)-expected)))
                    error=max(error,delta)
                    if delta: raise ValueError(f'{name} {backend} 结果误差为 {delta}，不生成加速比')
                    if iteration>=3: times[backend].append(duration)
                    if iteration==3+repeats-1: np.save(folder/f'mode{mode}_{backend}.npy',output)
            row=dict(mode=mode,name=name,max_error=error,passed=True,times_ms=times)
            for backend in times:
                row[backend]=dict(mean_ms=float(np.mean(times[backend])),p95_ms=float(np.percentile(times[backend],95)))
            row['speedup']=row['ARM']['mean_ms']/row['FPGA']['mean_ms']
            report['modes'].append(row)
        report['passed']=True
        return report
    except BaseException as exc:
        report['error']=str(exc)
        raise
    finally:
        report['directory']=str(folder)
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
