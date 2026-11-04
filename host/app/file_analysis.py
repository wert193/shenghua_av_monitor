"""Analyze an uploaded image or sampled video frames on both processing paths."""
import hashlib
import json
import time
import wave
from pathlib import Path

import cv2
import numpy as np

from image_filters import arm_filter

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png'}
VIDEO_SUFFIXES = {'.mp4', '.avi', '.mov', '.mkv'}
WAVE_SUFFIXES = {'.wav'}
MODES = ('smooth', 'edge', 'sharpen')


def _features(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    return {
        'brightness_mean': round(float(np.mean(gray)), 2),
        'contrast_std': round(float(np.std(gray)), 2),
        'sharpness_laplacian_var': round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
        'edge_density_percent': round(float(np.count_nonzero(edges)) * 100 / edges.size, 2),
    }


def _resize(frame, max_width, max_height):
    h, w = frame.shape[:2]
    scale = min(1.0, max_width / w, max_height / h)
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))),
                           interpolation=cv2.INTER_AREA)
    return frame


def _recommend(arm, fpga, max_error, target_fps=None):
    if fpga is None:
        return '仅 ARM 可用；当前版本未检测到 FPGA 图像加速器。'
    if max_error != 0:
        return '两路输出不一致，暂不推荐 FPGA；请检查硬件和滤波配置。'
    arm_mean, fpga_mean = arm['mean_ms'], fpga['mean_ms']
    arm_p95, fpga_p95 = arm['p95_ms'], fpga['p95_ms']
    if target_fps and target_fps > 0:
        arm_capacity = 1000 / arm_p95
        fpga_capacity = 1000 / fpga_p95
        arm_meets = arm_capacity >= target_fps
        fpga_meets = fpga_capacity >= target_fps
        if arm_meets and fpga_meets:
            if fpga_p95 <= arm_p95 * .85:
                return '推荐 FPGA：两路均达到素材帧率，且 FPGA 的 P95 滤波耗时至少低 15%%（%.1f 对 %.1f ms），余量更大。' % (fpga_p95, arm_p95)
            if arm_p95 <= fpga_p95 * .85:
                return '推荐 ARM：两路均达到素材帧率，且 ARM 的 P95 滤波耗时至少低 15%%（%.1f 对 %.1f ms）。' % (arm_p95, fpga_p95)
            return '推荐 ARM：两路均达到素材帧率，P95 差异不足 15%，可减少 FPGA 数据搬运。'
        if arm_meets:
            return '推荐 ARM：ARM 的 P95 滤波能力约 %.1f FPS，达到素材 %.2f FPS；FPGA 本次未达到目标。' % (arm_capacity, target_fps)
        if fpga_meets:
            return '推荐 FPGA：FPGA 的 P95 滤波能力约 %.1f FPS，达到素材 %.2f FPS；ARM 本次未达到目标。' % (fpga_capacity, target_fps)
        winner = 'FPGA' if fpga_p95 < arm_p95 else 'ARM'
        capacity = max(arm_capacity, fpga_capacity)
        return '两路本次均未达到素材 %.2f FPS；推荐较快的 %s（P95 约 %.1f FPS），可降低分辨率或帧率。' % (target_fps, winner, capacity)
    mean_winner = 'ARM' if arm_mean <= fpga_mean else 'FPGA'
    p95_winner = 'ARM' if arm_p95 <= fpga_p95 else 'FPGA'
    if mean_winner != p95_winner:
        return '平均值与 P95 结论不一致，建议按实际帧率要求手动选择。'
    fast = arm_mean if mean_winner == 'ARM' else fpga_mean
    slow = fpga_mean if mean_winner == 'ARM' else arm_mean
    if slow <= 0 or (slow - fast) / slow < .05:
        return '两路性能差异小于 5%，推荐 ARM，结构更简单且避免 FPGA 数据搬运。'
    return '推荐 %s：平均滤波耗时约快 %.0f%%，且 P95 同向；本结论仅针对该素材和测试尺寸。' % (mean_winner, (1 - fast / slow) * 100)


def _measure(frames, accelerator, target_fps=None):
    rows = []
    for mode in MODES:
        values = {'ARM': [], 'FPGA': []}
        max_error = 0
        for frame_index, frame in enumerate(frames):
            expected = arm_filter(frame, mode)
            for iteration in range(12):
                order = ('ARM', 'FPGA') if (iteration + frame_index) % 2 == 0 else ('FPGA', 'ARM')
                for backend in order:
                    if backend == 'FPGA' and accelerator is None:
                        continue
                    began = time.perf_counter()
                    output = arm_filter(frame, mode) if backend == 'ARM' else accelerator.process(frame, mode)[0]
                    elapsed = (time.perf_counter() - began) * 1000
                    max_error = max(max_error, int(np.abs(output.astype(np.int16) - expected.astype(np.int16)).max()))
                    if iteration >= 2:
                        values[backend].append(elapsed)
        arm = {'mean_ms': round(float(np.mean(values['ARM'])), 3),
               'p95_ms': round(float(np.percentile(values['ARM'], 95)), 3)}
        fpga = None
        if values['FPGA']:
            fpga = {'mean_ms': round(float(np.mean(values['FPGA'])), 3),
                    'p95_ms': round(float(np.percentile(values['FPGA'], 95)), 3)}
        rows.append({'mode': mode, 'ARM': arm, 'FPGA': fpga, 'max_error': max_error,
                     'recommendation': _recommend(arm, fpga, max_error, target_fps)})
    return rows


def analyze_file(path, display_name, accelerator, root, audio_engine=None):
    path = Path(path)
    suffix = path.suffix.lower()
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    raw_hash = digest.hexdigest()
    size = path.stat().st_size
    if suffix in WAVE_SUFFIXES:
        if audio_engine is None:
            raise ValueError('音频处理引擎不可用。')
        audio_fpga_available = getattr(audio_engine, 'driver', None) is not None
        try:
            with wave.open(str(path), 'rb') as source:
                if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != 48000 or source.getcomptype() != 'NONE':
                    raise ValueError('音频需为 48 kHz、单声道、16 位 PCM WAV。')
                total = source.getnframes()
                if total < 1:
                    raise ValueError('音频文件没有采样。')
                used = min(total, 2 * 48000)
                samples = np.frombuffer(source.readframes(used), dtype='<i2').astype(np.int32)
        except (wave.Error, EOFError) as error:
            raise ValueError('无法读取 WAV 文件，请检查文件是否完整。') from error
        modes = ((0, '低通'), (1, '高通'), (2, '带通'), (3, '原曲（延时对齐）'))
        rows, waveforms = [], {}
        # Process the same short excerpt on each backend. Keep block boundaries
        # and FIR history explicit so measurements match the streaming engine.
        for mode, label in modes:
            outputs = {'ARM': [], 'FPGA': []}
            timings = {'ARM': [], 'FPGA': []}
            tails = {'ARM': np.zeros(255, np.int32), 'FPGA': np.zeros(255, np.int32)}
            max_error = 0
            for block_index, start in enumerate(range(0, used, 4096)):
                block = samples[start:start + 4096]
                order = ('ARM', 'FPGA') if (mode + block_index) % 2 == 0 else ('FPGA', 'ARM')
                for backend in order:
                    if backend == 'FPGA' and not audio_fpga_available:
                        continue
                    padded = np.concatenate((tails[backend], block))
                    began = time.perf_counter()
                    processed = audio_engine.compute(padded, mode, backend)
                    timings[backend].append((time.perf_counter() - began) * 1000)
                    outputs[backend].append(processed[255:])
                    tails[backend] = padded[-255:].copy()
            arm_signal = np.concatenate(outputs['ARM']).astype(np.int32)
            fpga_signal = np.concatenate(outputs['FPGA']).astype(np.int32) if outputs['FPGA'] else None
            rmse = None
            ser_db = None
            if fpga_signal is not None:
                difference = arm_signal.astype(np.float64) - fpga_signal.astype(np.float64)
                max_error = int(np.max(np.abs(difference)))
                rmse = float(np.sqrt(np.mean(difference * difference)))
                reference_rms = float(np.sqrt(np.mean(arm_signal.astype(np.float64) ** 2)))
                ser_db = None if rmse == 0 else round(20 * float(np.log10(max(reference_rms, 1e-12) / rmse)), 3)
            arm_times = timings['ARM']
            fpga_times = timings['FPGA']
            arm = {'mean_ms': round(float(np.mean(arm_times)), 3), 'p95_ms': round(float(np.percentile(arm_times, 95)), 3)}
            fpga = None if not fpga_times else {'mean_ms': round(float(np.mean(fpga_times)), 3), 'p95_ms': round(float(np.percentile(fpga_times, 95)), 3)}
            recommendation = _recommend(arm, fpga, max_error)
            rows.append({'mode': str(mode), 'label': label, 'ARM': arm, 'FPGA': fpga,
                         'max_error': max_error, 'rmse': None if rmse is None else round(rmse, 6),
                         'ser_db': ser_db, 'recommendation': recommendation})
            if mode in (0, 1, 2):
                stride = max(1, len(samples) // 800)
                waveforms[str(mode)] = {
                    'original': samples[::stride][:800].astype(float).tolist(),
                    'ARM': arm_signal[::stride][:800].astype(float).tolist(),
                    'FPGA': fpga_signal[::stride][:800].astype(float).tolist() if fpga_signal is not None else [],
                }
        result = {
            'kind': 'audio', 'name': display_name, 'format': 'WAV PCM16', 'size_bytes': size,
            'sha256': raw_hash, 'sample_rate': 48000, 'channels': 1, 'sample_count': used,
            'duration_seconds': round(used / 48000, 3), 'source_duration_seconds': round(total / 48000, 3),
            'rows': rows, 'waveforms': waveforms,
            'accelerator_available': audio_fpga_available,
            'measurement_scope': '同一段 WAV 前 2 秒，48 kHz 单声道 PCM16；四种模式分别在 ARM 与 FPGA 上逐块处理。最大误差和 RMSE 比较两路输出，信噪比以 ARM 输出为参考，不代表与真实声源的绝对保真度。计时为每块滤波计算时间，不含文件读取、网页绘图、播放及声学端到端延迟。波形为抽样显示，误差按完整处理采样计算。',
        }
    elif suffix in IMAGE_SUFFIXES:
        raw = np.fromfile(str(path), dtype=np.uint8)
        original = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if original is None:
            raise ValueError('无法读取图片；请上传有效的 JPEG 或 PNG。')
        original_h, original_w = original.shape[:2]
        if original_w * original_h > 16_000_000:
            raise ValueError('图片超过 1600 万像素，请先缩小图片。')
        measured = _resize(original, 640, 360)
        result = {
            'kind': 'image', 'name': display_name, 'format': suffix[1:].upper(), 'size_bytes': size,
            'sha256': raw_hash, 'width': original_w, 'height': original_h,
            'measure_width': measured.shape[1], 'measure_height': measured.shape[0],
            'sample_count': 1, 'features': _features(measured),
            'measurement_scope': '同一张上传图片；双方预热 2 次并测量 10 次；FPGA 耗时包含分块、DMA 和结果复制，不含解码与显示。',
            'rows': _measure([measured], accelerator),
        }
    elif suffix in VIDEO_SUFFIXES:
        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                raise ValueError('无法解码视频；建议使用 H.264 MP4 或 MJPEG AVI。')
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            if not np.isfinite(fps) or fps <= 0:
                fps = 0.0
            count = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            duration = count / fps if count and fps else 0.0
            fourcc_num = int(cap.get(cv2.CAP_PROP_FOURCC))
            codec = ''.join(chr((fourcc_num >> (8 * i)) & 255) for i in range(4)).strip('\x00 ')
            indices = sorted(set([0, count // 2, max(0, count - 1)])) if count else [0]
            frames = []
            for index in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append(_resize(frame, 320, 180))
            if not frames:
                raise ValueError('视频中没有可解码的画面。')
        finally:
            cap.release()
        frame_features = [_features(frame) for frame in frames]
        features = {key: round(float(np.mean([item[key] for item in frame_features])), 2)
                    for key in frame_features[0]}
        result = {
            'kind': 'video', 'name': display_name, 'format': suffix[1:].upper(), 'size_bytes': size,
            'sha256': raw_hash, 'width': width, 'height': height, 'fps': round(fps, 3),
            'frame_count': count, 'duration_seconds': round(duration, 3), 'codec': codec,
            'sample_count': len(frames), 'measure_width': frames[0].shape[1],
            'measure_height': frames[0].shape[0], 'features': features,
            'measurement_scope': '从视频开头、中间、结尾抽取最多 3 帧并缩放到 320×180；双方预热 2 次并测量 10 次。仅测滤波，未测解码、音频、HDMI 和整段播放帧率。',
            'rows': _measure(frames, accelerator, fps if fps > 0 else None),
        }
    else:
        raise ValueError('支持 JPEG、PNG 图片，MP4、AVI、MOV、MKV 视频，以及 48 kHz 单声道 PCM16 WAV 音频。')
    result['accelerator_available'] = accelerator is not None
    folder = Path(root) / 'data' / ('file_analysis_' + str(time.time_ns()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    result['report_id'] = folder.name
    return result

