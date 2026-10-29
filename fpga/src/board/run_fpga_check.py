"""Offline ARM/FPGA experiment. Temporarily replaces base, restores it in finally."""
from pathlib import Path
import ctypes
import hashlib
import json
import subprocess
import time
import urllib.request
import urllib.error
import numpy as np
import faulthandler
from fir_driver import FirDriver
from check_hardware import check_reset

ROOT=Path(__file__).resolve().parent

def require_audio_stopped():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/api/status',timeout=2) as r:
            state=json.load(r)
    except (urllib.error.URLError,TimeoutError):
        return
    if state.get('project')!='shenghua':
        raise RuntimeError('8080 is occupied by an unknown application')
    if state['audio']['status'] in ('starting','running','stopping'):
        raise RuntimeError('请先在作品页面停止歌曲，再运行 FPGA 检查。')

def main():
    require_audio_stopped()
    # Validate and compile before changing any PL state.
    for name in ('audio_fir.bit','audio_fir.hwh','coefficients.json','music_input.npy'):
        if not (ROOT/name).is_file(): raise FileNotFoundError(name)
    check_reset(ROOT/'audio_fir.hwh')
    print('硬件复位配置检查通过（修正版 v2）',flush=True)
    meta=json.loads((ROOT/'coefficients.json').read_text())
    coeff=np.asarray(meta['coefficients'],dtype=np.int32)
    x=np.load(ROOT/'music_input.npy',allow_pickle=False)
    assert x.dtype==np.int32 and x.ndim==1 and 0<len(x)<=16384
    exe=ROOT/'reference.so'
    subprocess.run(['gcc','-O3','-shared','-fPIC',str(ROOT/'reference.c'),'-o',str(exe)],check=True,timeout=60)
    lib=ctypes.CDLL(str(exe))
    vector=np.ctypeslib.ndpointer(dtype=np.int32,ndim=1,flags='C_CONTIGUOUS')
    history_type=np.ctypeslib.ndpointer(dtype=np.int16,ndim=1,flags='C_CONTIGUOUS')
    lib.fir_reference.argtypes=[vector,vector,ctypes.c_uint,vector,history_type,ctypes.POINTER(ctypes.c_uint),ctypes.c_int]
    lib.fir_reference.restype=None
    folder=ROOT/'results'/('comparison_'+str(time.time_ns()))
    folder.mkdir(parents=True)
    record={'input_sha256':hashlib.sha256(x.tobytes()).hexdigest(),'samples':len(x),
            'bitstream_sha256':hashlib.sha256((ROOT/'audio_fir.bit').read_bytes()).hexdigest(),
            'scope':'Offline PCM16 FIR, ARM compiled C versus FPGA DMA. No playback, A/V sync or crossfade.',
            'fpga_time_includes':'register setup, cache maintenance, DMA transfers and polling; excludes allocation and output copy',
            'arm_time_includes':'ctypes call, history clear and C FIR; excludes allocation',
            'modes':[], 'restored_base':False, 'passed':False}
    np.save(folder/'input.npy',x)
    driver=None
    changed=False
    try:
        import pynq
        from pynq import Overlay,allocate
        from pynq.overlays.base import BaseOverlay
        record['pynq_version']=pynq.__version__
        base=BaseOverlay('base.bit',download=False)
        if not base.is_loaded(): raise RuntimeError('当前不是 base 配置，请正常重启开发板后再试。')
        # Prevent the integrated audio service from acquiring its session lock.
        # The launcher stops its own identified service before running this script.
        print('加载 FPGA FIR 配置；本次只计算和对比，不播放声音。',flush=True)
        changed=True
        overlay=Overlay(str(ROOT/'audio_fir.bit'))
        print('FPGA 配置加载已返回，开始 DMA 初始化',flush=True)
        driver=FirDriver(overlay,allocate,len(x))
        print('DMA 初始化完成，开始逐模式计算',flush=True)
        for mode,name in enumerate(meta['modes']):
            print('正在检查：'+name,flush=True)
            h=np.zeros(256,np.int16); head=ctypes.c_uint(0); arm=np.empty_like(x)
            def arm_run(data,out,clear=True):
                t=time.perf_counter()
                lib.fir_reference(data,out,len(data),coeff[mode],h,ctypes.byref(head),int(clear))
                return time.perf_counter()-t
            arm_run(x,arm)
            # Independent NumPy integer convolution verifies the compiled reference.
            exact=np.clip((np.convolve(x.astype(np.int64),coeff[mode].astype(np.int64))[:len(x)]+16384)//32768,-32768,32767).astype(np.int32)
            if not np.array_equal(arm,exact): raise AssertionError('ARM reference mismatch')
            fpga,_=driver.process(x,mode)
            error=int(np.max(np.abs(fpga.astype(np.int64)-exact)))
            if error: raise AssertionError(f'{name}: FPGA maximum error {error}')
            # Check that a short split transaction does not erase history.
            a,_=driver.process(x[:17],mode,True)
            b,_=driver.process(x[17:],mode,False)
            if not np.array_equal(np.concatenate((a,b)),exact): raise AssertionError('DMA boundary history mismatch')
            arm_times=[arm_run(x,arm) for _ in range(10)]
            fpga_times=[]
            for _ in range(10):
                got,seconds=driver.process(x,mode)
                if not np.array_equal(got,exact): raise AssertionError('Repeated FPGA result mismatch')
                fpga_times.append(seconds)
            result={'mode':name,'max_integer_error':error,'repeats':10,
                    'arm_mean_ms':float(np.mean(arm_times)*1000),'fpga_dma_mean_ms':float(np.mean(fpga_times)*1000),
                    'arm_times_s':arm_times,'fpga_dma_times_s':fpga_times,
                    'arm_over_fpga_ratio':float(np.mean(arm_times)/np.mean(fpga_times))}
            record['modes'].append(result)
            np.save(folder/(name+'_arm.npy'),arm)
            np.save(folder/(name+'_fpga.npy'),fpga)
            print(f'{name}: PASS, ARM {result["arm_mean_ms"]:.3f} ms, FPGA+DMA {result["fpga_dma_mean_ms"]:.3f} ms',flush=True)
        record['passed']=True
    except BaseException as error:
        record['error']=repr(error)
        raise
    finally:
        if driver:
            try: driver.close()
            except Exception as error: record['dma_cleanup_error']=repr(error)
        if changed:
            try:
                from pynq.overlays.base import BaseOverlay
                BaseOverlay('base.bit',download=True)
                record['restored_base']=True
                print('已恢复 base 配置；可以重新启动歌曲页面。',flush=True)
            except Exception as error:
                record['restore_error']=repr(error)
                print('恢复失败，请正常重启开发板；错误已保存。',flush=True)
        (folder/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('结果目录：',folder,flush=True)

if __name__=='__main__':
    # Diagnostics for lower-level calls that software polling cannot interrupt.
    with (ROOT/'watchdog.log').open('w') as watchdog:
        faulthandler.dump_traceback_later(15,repeat=True,file=watchdog)
        try: main()
        finally: faulthandler.cancel_dump_traceback_later()
