"""Image reference and repeatable single-image ARM benchmark, not video FPS."""
from pathlib import Path
import threading
import time
import json
import hashlib
import io
import numpy as np
import cv2
from PIL import Image
from image_filters import filter_frame,arm_filter,benchmark_frame,ARM_IMPLEMENTATION,test_image


class ImageEngine:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.mode = 'smooth'
        self.backend = 'ARM'
        self.accelerator = None
        self.frame = test_image()
        self.source = '生成的测试图'
        saved = self.root / 'data' / 'input.png'
        if saved.exists():
            frame = cv2.imread(str(saved))
            if frame is not None:
                self.frame, self.source = frame, '上次上传的图片'
        self.version = 0
        self.metrics = None
        self._render()

    def _render(self):
        start = time.perf_counter()
        processed = self.accelerator.process(self.frame,self.mode)[0] if self.backend=='FPGA' else arm_filter(self.frame, self.mode)
        self.last_ms = (time.perf_counter()-start)*1000
        ok1, a = cv2.imencode('.jpg', self.frame)
        ok2, b = cv2.imencode('.jpg', processed)
        if not ok1 or not ok2:
            raise RuntimeError('图片编码失败')
        self.original_jpeg, self.processed_jpeg = a.tobytes(), b.tobytes()
        self.sha = hashlib.sha256(self.frame.tobytes()).hexdigest()
        self.version += 1

    def upload(self, raw):
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('JPEG', 'PNG') or im.width * im.height > 16000000:
                raise ValueError('请上传不超过1600万像素的 JPEG 或 PNG')
            im.thumbnail((640, 360))
            frame = cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)
        with self.lock:
            self.frame = frame
            self.source = '上传的图片'
            self.metrics = None
            self._render()
            if not cv2.imwrite(str(self.root / 'data' / 'input.png'), frame):
                raise RuntimeError('保存图片失败')

    def select(self, mode):
        if mode not in ('original', 'smooth', 'edge', 'sharpen'):
            raise ValueError('未知图像效果')
        with self.lock:
            self.mode = mode
            self.metrics = None
            self._render()

    def snapshot(self):
        with self.lock:
            return {'mode': self.mode, 'backend':self.backend, 'source': self.source, 'version': self.version,
                    'width': self.frame.shape[1], 'height': self.frame.shape[0],
                    'last_ms': round(self.last_ms, 3), 'metrics': self.metrics}

    def jpeg(self, which):
        with self.lock:
            return self.original_jpeg if which == 'original' else self.processed_jpeg

    def benchmark(self):
        # Keep source and mode fixed throughout this test.
        with self.lock:
            for _ in range(3):
                arm_filter(self.frame, self.mode)
            durations = []
            cpu_start = time.process_time()
            wall_start = time.perf_counter()
            for _ in range(30):
                t = time.perf_counter()
                result = arm_filter(self.frame, self.mode)
                durations.append((time.perf_counter()-t)*1000)
            elapsed = time.perf_counter()-wall_start
            cpu = time.process_time()-cpu_start
            metrics = {'backend': 'ARM/OpenCV', 'scope': 'single_image_filter_only',
                       'arm_implementation':ARM_IMPLEMENTATION,
                       'source_sha256': self.sha, 'mode': self.mode,
                       'shape': list(self.frame.shape), 'repeats': 30, 'warmups': 3,
                       'mean_ms': float(np.mean(durations)), 'p95_ms': float(np.percentile(durations, 95)),
                       'process_cpu_core_equivalents': cpu/elapsed if elapsed else None,
                       'opencv': cv2.__version__, 'opencv_threads': cv2.getNumThreads(),
                       'fpga_result': None,
                       'note': 'Excludes decoding, transfer, display, audio. Not playback FPS or final A/V comparison.'}
            folder = self.root/'data'/('image_benchmark_'+str(time.time_ns()))
            folder.mkdir()
            np.save(folder/'input.npy', self.frame)
            np.save(folder/'output.npy', result)
            (folder/'report.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
            self.metrics = metrics
            return metrics

    def select_backend(self,backend):
        if backend not in ('ARM','FPGA'):raise ValueError('未知图片后端')
        if backend=='FPGA' and self.accelerator is None:raise ValueError('图片 FPGA 未接入')
        with self.lock:
            previous=self.backend;self.backend=backend
            try:self._render()
            except Exception:
                self.backend=previous
                raise

    def benchmark_compare(self,same_input=False):
        with self.lock:
            if self.accelerator is None:raise ValueError('图片 FPGA 未接入')
            frame=benchmark_frame() if same_input else self.frame
            repeats=20 if same_input else 30
            expected=filter_frame(frame,self.mode)
            times={'ARM':[],'FPGA':[]};error=0
            for iteration in range(repeats+3):
                for backend in ('ARM','FPGA') if iteration%2==0 else ('FPGA','ARM'):
                    began=time.perf_counter()
                    result=arm_filter(frame,self.mode) if backend=='ARM' else self.accelerator.process(frame,self.mode)[0]
                    elapsed=(time.perf_counter()-began)*1000
                    error=max(error,int(np.abs(result.astype(np.int16)-expected.astype(np.int16)).max()))
                    if error:raise ValueError('图片 ARM / FPGA 像素结果不一致：'+str(error))
                    if iteration>=3:times[backend].append(elapsed)
            metrics={'backend':'ARM / FPGA','mode':self.mode,'source_sha256':hashlib.sha256(frame.tobytes()).hexdigest(),
                'arm_implementation':ARM_IMPLEMENTATION,'same_input':same_input,
                'shape':list(frame.shape),'warmups':3,'repeats':repeats,'max_error':error,
                'times_ms':times,'scope':'Same full-size image; FPGA includes halo tiling, padding, DMA, assembly. Excludes decoding, JPEG, HDMI, audio.'}
            for backend,values in times.items():
                metrics[backend]={'mean_ms':float(np.mean(values)),'p95_ms':float(np.percentile(values,95))}
            metrics.update(mean_ms=metrics['ARM']['mean_ms'],p95_ms=metrics['ARM']['p95_ms'],fpga_result=metrics['FPGA'],speedup=metrics['ARM']['mean_ms']/metrics['FPGA']['mean_ms'])
            folder=self.root/'data'/('image_benchmark_'+str(time.time_ns()));folder.mkdir()
            np.save(folder/'input.npy',frame);np.save(folder/'output.npy',result)
            (folder/'report.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            self.metrics=metrics
            return metrics
