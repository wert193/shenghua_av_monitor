"""Process webcam and microphone chunks received from the local demo browser."""
import os
import threading
import time

import cv2
import numpy as np
from hdmi_display import canvas_for_video
from image_filters import arm_filter


class LiveMonitor:
    MAX_VIDEO_BYTES = 512 * 1024
    MAX_AUDIO_SAMPLES = 8192
    VIDEO_MODES = ('original', 'smooth', 'edge', 'sharpen')

    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        # Keep camera work independent from microphone filtering.
        self.video_lock = threading.Lock()
        self.audio_lock = threading.Lock()
        self.active = False
        self.audio_tail = np.zeros(255, dtype=np.int32)
        self.raw_history = np.zeros(4096, dtype=np.int16)
        self.filtered_history = np.zeros(4096, dtype=np.int16)
        self.display_mode = 'video'
        self.source = 'browser'
        self.video_mode = 'smooth'
        self.audio_mode = 0
        self.video_backends = {name: 'ARM' for name in ('smooth', 'edge', 'sharpen')}
        self.audio_backends = {name: 'ARM' for name in ('0', '1', '2')}
        self.last_video_canvas = None
        self.last_camera_frame = None
        self.last_result_frame = None
        self.last_camera_jpeg_bytes = b''
        self.last_result_jpeg_bytes = b''
        self._audio_applied = None
        self.frames = 0
        self.last_frame_at = 0.0
        self.last_activity = 0.0
        self.state = {'active': False, 'frames': 0, 'fps': 0.0,
                      'video_ms': 0.0, 'audio_ms': 0.0, 'error': '',
                      'board_audio_output': False, 'source': 'browser'}
        # Lightweight demo detectors. They are intentionally conservative:
        # person uses OpenCV's pretrained HOG, fire/audio are rule-based.
        self.detection_enabled = os.environ.get('SHENGHUA_DETECT', '0') != '0'
        self.person_enabled = os.environ.get('SHENGHUA_PERSON', '0') != '0'
        self.audio_threshold = float(os.environ.get('SHENGHUA_AUDIO_THRESHOLD', '5000'))
        self._hog = None
        if self.detection_enabled and self.person_enabled:
            try:
                hog = cv2.HOGDescriptor()
                hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                self._hog = hog
            except Exception:
                self._hog = None
        self._detect_frame_no = 0
        self._person_hits = 0
        self._person_busy = False
        self.person_interval = int(os.environ.get('SHENGHUA_PERSON_INTERVAL', '15'))
        self.audio_peak = float(os.environ.get('SHENGHUA_AUDIO_PEAK', '9000'))
        self._fire_hits = 0
        self._audio_hits = 0
        self._last_event_at = {}
        self.detections = {'person': 0, 'fire': 0, 'audio': 0, 'last': ''}

    def snapshot(self):
        with self.lock:
            if self.active and time.monotonic() - self.last_activity > 5:
                self.active = False
                self.audio_tail.fill(0)
                self.state['active'] = False
            state = dict(self.state)
            state['source'] = self.source
            state['display_mode'] = self.display_mode
            controls = self.app.audio.engine.snapshot()
            state.update(video_mode=self.video_mode,
                         video_backend=self.video_backends.get(self.video_mode, 'ARM'),
                         audio_mode=self.audio_mode,
                         audio_backend=self.audio_backends.get(str(self.audio_mode), 'ARM'),
                         video_backends=dict(self.video_backends),
                         audio_backends=dict(self.audio_backends),
                         detection=dict(self.detections),
                         mode=controls['mode'], backend=controls['backend'])
        return state

    def start(self, source='browser'):
        engine = self.app.audio.engine
        if self.active:
            raise ValueError('实时监控已经启动。')
        state = engine.snapshot()
        if state['status'] in ('starting', 'running', 'stopping', 'measuring'):
            raise ValueError('请先停止当前音频播放或测量，再启动实时监控。')
        if self.app.video.snapshot()['status'] == 'playing':
            raise ValueError('请先停止当前视频播放，再启动实时监控。')
        if engine.thread and engine.thread.is_alive():
            raise ValueError('音频进程尚未完全退出，请稍后再启动实时监控。')
        with self.lock:
            self.active = True
            self.source = source
            self.audio_tail.fill(0)
            self._audio_applied = None
            self.last_camera_jpeg_bytes = b''
            self.last_result_jpeg_bytes = b''
            self.frames = 0
            self.last_frame_at = 0.0
            self.last_activity = time.monotonic()
            self.state.update(active=True, frames=0, fps=0.0, video_ms=0.0,
                              audio_ms=0.0, error='', source=source)
        try:
            engine.command({'mode': 0}, internal=True)
        except Exception:
            with self.lock:
                self.active = False
                self.state['active'] = False
            raise
        return self.snapshot()

    def note_source_activity(self):
        with self.lock:
            if self.active:
                self.last_activity = time.monotonic()

    def set_source_error(self, error):
        with self.lock:
            self.state['error'] = error

    def last_camera_jpeg(self):
        with self.lock:
            data = self.last_camera_jpeg_bytes
            frame = None if data else (self.last_camera_frame.copy()
                                       if self.last_camera_frame is not None else None)
        if data:
            return data
        if frame is None:
            return b''
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return encoded.tobytes() if ok else b''

    def last_result_jpeg(self):
        with self.lock:
            data = self.last_result_jpeg_bytes
            frame = None if data else (self.last_result_frame.copy()
                                       if self.last_result_frame is not None else None)
        if data:
            return data
        if frame is None:
            return b''
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return encoded.tobytes() if ok else b''

    def _fit_processing(self, frame):
        height, width = frame.shape[:2]
        scale = min(1.0, 320 / width, 240 / height)
        if scale < 1:
            frame = cv2.resize(frame, (max(1, round(width * scale)),
                                       max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
        return frame

    def process_camera_frame(self, frame):
        """Process one already-decoded camera frame without a JPEG round trip."""
        frame = self._fit_processing(frame)
        with self.lock:
            self.last_camera_frame = frame.copy()
            ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                self.last_camera_jpeg_bytes = encoded.tobytes()
        return self.process_frame(frame)

    def stop(self):
        with self.lock:
            self.active = False
            self.audio_tail.fill(0)
            self._audio_applied = None
            self.state['active'] = False
            self.state['source'] = self.source
        return self.snapshot()

    def toggle_display(self):
        """BTN3 switches the HDMI monitor between video and audio analysis."""
        with self.lock:
            self.display_mode = 'audio' if self.display_mode == 'video' else 'video'
            selected = self.display_mode
            canvas = self.last_video_canvas.copy() if self.last_video_canvas is not None else None
        if selected == 'audio':
            canvas = self._audio_canvas()
        if self.app.display and canvas is not None:
            self.app.display.refresh_canvas(canvas)
        return {'display_mode': selected}

    def _audio_canvas(self):
        canvas = np.full((360, 640, 3), (20, 29, 40), np.uint8)
        cv2.putText(canvas, 'LIVE AUDIO ANALYSIS  |  PYNQ-Z2', (18, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, .58, (235, 240, 245), 1, cv2.LINE_AA)
        with self.audio_lock:
            raw = self.raw_history.astype(np.float32).copy()
            filtered = self.filtered_history.astype(np.float32).copy()
            controls = self.app.audio.engine.snapshot()
        peak = max(1.0, float(np.percentile(np.abs(np.concatenate((raw, filtered))), 99.5)))
        scale = min(32768.0, peak * 1.15)
        for y0, signal, color, label in ((48, raw, (220, 155, 55), 'MIC INPUT'),
                                         (132, filtered, (75, 210, 145), 'FILTERED OUTPUT')):
            left, right, height = 68, 622, 64
            mid = y0 + height // 2
            cv2.putText(canvas, label, (8, y0 + 12), cv2.FONT_HERSHEY_SIMPLEX,
                        .34, color, 1, cv2.LINE_AA)
            cv2.line(canvas, (left, y0), (right, y0), (65, 77, 89), 1)
            cv2.line(canvas, (left, mid), (right, mid), (90, 103, 115), 1)
            cv2.line(canvas, (left, y0 + height), (right, y0 + height), (65, 77, 89), 1)
            cv2.putText(canvas, '+%.0f' % scale, (8, y0 + 31), cv2.FONT_HERSHEY_SIMPLEX,
                        .30, (165, 177, 187), 1, cv2.LINE_AA)
            cv2.putText(canvas, '-%.0f' % scale, (8, y0 + height), cv2.FONT_HERSHEY_SIMPLEX,
                        .30, (165, 177, 187), 1, cv2.LINE_AA)
            points = []
            for index in range(0, len(signal), 4):
                x = left + index * (right - left) // (len(signal) - 1)
                y = mid - int(np.clip(signal[index] / scale, -1, 1) * (height // 2 - 2))
                points.append((x, y))
            if len(points) > 1:
                cv2.polylines(canvas, [np.asarray(points, np.int32)], False, color, 1, cv2.LINE_AA)

        # Overlay input and filtered spectra, normalized to their joint peak.
        window = np.hanning(len(raw))
        spectra = [np.abs(np.fft.rfft(signal * window)) for signal in (raw, filtered)]
        joint_peak = max(1.0, float(max(s.max() for s in spectra)))
        left, right, top, bottom = 68, 622, 238, 337
        cv2.putText(canvas, 'FREQUENCY SPECTRUM  |  INPUT: AMBER  FILTERED: GREEN',
                    (8, 218), cv2.FONT_HERSHEY_SIMPLEX, .34, (210, 220, 230), 1, cv2.LINE_AA)
        cv2.putText(canvas, 'LP <800 Hz', (left, 233), cv2.FONT_HERSHEY_SIMPLEX,
                    .28, (110, 170, 225), 1, cv2.LINE_AA)
        cv2.putText(canvas, 'BP 800-2500 Hz', (245, 233), cv2.FONT_HERSHEY_SIMPLEX,
                    .28, (130, 195, 145), 1, cv2.LINE_AA)
        cv2.putText(canvas, 'HP >3000 Hz', (475, 233), cv2.FONT_HERSHEY_SIMPLEX,
                    .28, (195, 145, 205), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (left, top), (right, bottom), (52, 66, 78), 1)
        for db in (0, -30, -60):
            y = bottom - int((db + 60) / 60 * (bottom - top))
            cv2.line(canvas, (left, y), (right, y), (48, 60, 72), 1)
            cv2.putText(canvas, str(db), (39, y + 3), cv2.FONT_HERSHEY_SIMPLEX,
                        .26, (145, 158, 170), 1, cv2.LINE_AA)
        for hz, color in ((800, (40, 65, 85)), (2500, (45, 55, 80)), (3000, (55, 45, 70))):
            x = left + int(hz / 12000 * (right - left))
            cv2.line(canvas, (x, top), (x, bottom), color, 1)
            cv2.putText(canvas, str(hz), (x + 2, bottom - 3), cv2.FONT_HERSHEY_SIMPLEX,
                        .28, (155, 165, 175), 1, cv2.LINE_AA)
        cv2.putText(canvas, '0 Hz', (left, 352), cv2.FONT_HERSHEY_SIMPLEX, .30,
                    (165, 177, 187), 1, cv2.LINE_AA)
        cv2.putText(canvas, '12 kHz', (right - 40, 352), cv2.FONT_HERSHEY_SIMPLEX, .30,
                    (165, 177, 187), 1, cv2.LINE_AA)
        colors = ((220, 155, 55), (75, 210, 145))
        for spectrum, color in zip(spectra, colors):
            points = []
            for bin_index in range(1, len(spectrum) * 2 // 4):
                hz = bin_index * 48000 / len(raw)
                if hz > 12000:
                    break
                db = 20 * np.log10(max(1e-6, spectrum[bin_index] / joint_peak))
                x = left + int(hz / 12000 * (right - left))
                y = bottom - int(np.clip((db + 60) / 60, 0, 1) * (bottom - top))
                points.append((x, y))
            if len(points) > 1:
                cv2.polylines(canvas, [np.asarray(points, np.int32)], False, color, 1, cv2.LINE_AA)
        mode_names = ('LOW-PASS', 'HIGH-PASS', 'BAND-PASS', 'BYPASS')
        cv2.putText(canvas, '%s  |  %s  |  BTN3: SWITCH VIEW' %
                    (mode_names[self.audio_mode], self.audio_backends[str(self.audio_mode)]),
                    (260, 25), cv2.FONT_HERSHEY_SIMPLEX, .42, (170, 195, 220), 1, cv2.LINE_AA)
        return canvas

    def preset(self, settings=None, backend=None):
        settings = settings if isinstance(settings, dict) else {'mode': settings, 'backend': backend}
        video_mode = settings.get('video_mode', settings.get('mode'))
        audio_mode = settings.get('audio_mode')
        legacy_backend = settings.get('backend')
        if video_mode is not None and video_mode not in self.VIDEO_MODES:
            raise ValueError('未知视频滤波模式。')
        if audio_mode is not None:
            try:
                audio_mode = int(audio_mode)
            except (TypeError, ValueError):
                raise ValueError('未知音频滤波模式。')
            if audio_mode not in (0, 1, 2, 3):
                raise ValueError('未知音频滤波模式。')
        if legacy_backend is not None:
            if legacy_backend not in ('ARM', 'FPGA'):
                raise ValueError('未知计算通道。')
            if video_mode in ('smooth', 'edge', 'sharpen'):
                settings.setdefault('video_backends', {})
                settings['video_backends'][video_mode] = legacy_backend
            if audio_mode is not None and audio_mode < 3:
                settings.setdefault('audio_backends', {})
                settings['audio_backends'][str(audio_mode)] = legacy_backend
        video_backends = settings.get('video_backends', {})
        audio_backends = settings.get('audio_backends', {})
        if not isinstance(video_backends, dict) or not isinstance(audio_backends, dict):
            raise ValueError('ARM / FPGA 通道设置格式无效。')
        for name, value in video_backends.items():
            if name not in ('smooth', 'edge', 'sharpen') or value not in ('ARM', 'FPGA'):
                raise ValueError('视频通道设置无效。')
            if value == 'FPGA' and (self.app.video_accelerator is None or
                                    name not in self.app.video_accelerator.modes):
                raise ValueError('FPGA 当前未提供%s视频滤波。' % name)
        for name, value in audio_backends.items():
            if str(name) not in ('0', '1', '2') or value not in ('ARM', 'FPGA'):
                raise ValueError('音频通道设置无效。')
            if value == 'FPGA' and self.app.audio.engine.driver is None:
                raise ValueError('当前 FPGA 配置未包含音频滤波器。')
        with self.lock:
            if video_mode is not None:
                self.video_mode = video_mode
            if audio_mode is not None:
                self.audio_mode = audio_mode
            self.video_backends.update(video_backends)
            self.audio_backends.update({str(key): value for key, value in audio_backends.items()})
        if audio_mode is not None:
            self.app.audio.engine.command({'mode': audio_mode}, internal=True)
        return self.snapshot()

    def select_physical_mode(self, mode):
        if mode not in (0, 1, 2):
            return
        with self.lock:
            self.audio_mode = mode
        self.app.audio.engine.command({'mode': mode}, internal=True)

    def process_video(self, raw):
        if not raw or len(raw) > self.MAX_VIDEO_BYTES:
            raise ValueError('摄像头帧为空或超过 512 KB。')
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('无法解码摄像头画面。')
        return self.process_frame(self._fit_processing(frame))

    def _trigger_event(self, kind, confidence, cooldown=20.0):
        if not self.detection_enabled:
            return
        now = time.monotonic()
        if now - self._last_event_at.get(kind, 0.0) < cooldown:
            return
        self._last_event_at[kind] = now
        with self.lock:
            self.detections[kind] = self.detections.get(kind, 0) + 1
            self.detections['last'] = '%s @ %s' % (kind, time.strftime('%H:%M:%S'))

    def _detect_frame(self, output):
        if not self.detection_enabled or output is None:
            return
        self._detect_frame_no += 1
        # Fire/smoke rule: saturated orange/red regions. Cheap enough to run
        # every frame; require several consecutive hits to avoid a single flash.
        try:
            hsv = cv2.cvtColor(output, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (0, 120, 140), (28, 255, 255))
            ratio = float(cv2.countNonZero(mask)) / max(1, output.shape[0] * output.shape[1])
            if ratio > 0.03:
                self._fire_hits += 1
            else:
                self._fire_hits = max(0, self._fire_hits - 1)
            if self._fire_hits >= 3:
                self._fire_hits = 0
                self._trigger_event('fire', min(0.95, 0.55 + ratio), cooldown=60.0)
        except Exception:
            pass
        # Person: run HOG in a background thread so it never blocks the
        # 6 fps video path. Only one inference is in flight at a time.
        if (self._hog is not None and not self._person_busy
                and self._detect_frame_no % max(1, self.person_interval) == 0):
            self._person_busy = True
            threading.Thread(target=self._person_worker, args=(output.copy(),),
                             daemon=True, name='person-detect').start()

    def _person_worker(self, frame):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rects, weights = self._hog.detectMultiScale(
                gray, winStride=(16, 16), padding=(8, 8), scale=1.1)
            if len(rects) and max(float(w) for w in weights) > 0.35:
                self._person_hits += 1
            else:
                self._person_hits = max(0, self._person_hits - 1)
            if self._person_hits >= 2:
                self._person_hits = 0
                self._trigger_event('person', 0.7, cooldown=20.0)
        except Exception:
            pass
        finally:
            self._person_busy = False

    def _detect_audio(self, samples):
        if not self.detection_enabled or not samples.size:
            return
        try:
            values = samples.astype(np.int32)
            rms = float(np.sqrt(np.mean(values.astype(np.float64) ** 2)))
            peak = float(np.max(np.abs(values)))
        except Exception:
            return
        # A clap is short: RMS alone often misses it, so require a high peak
        # and a moderate RMS floor. Two consecutive blocks avoid clicks.
        if peak >= self.audio_peak and rms >= self.audio_threshold * 0.35:
            self._audio_hits += 1
        else:
            self._audio_hits = max(0, self._audio_hits - 1)
        if self._audio_hits >= 2:
            self._audio_hits = 0
            confidence = min(0.95, max(0.55, peak / max(1.0, self.audio_peak * 2)))
            self._trigger_event('audio', confidence, cooldown=15.0)

    def process_frame(self, frame):
        """Filter one decoded BGR frame and update previews/HDMI in one pass."""
        if frame is None or getattr(frame, 'size', 0) == 0:
            raise ValueError('摄像头画面为空。')
        with self.video_lock:
            with self.lock:
                if not self.active:
                    raise ValueError('请先启动实时监控。')
                self.last_activity = time.monotonic()
                mode = self.video_mode
                backend = self.video_backends.get(mode, 'ARM')
            if backend == 'FPGA' and mode != 'original' and self.app.video_accelerator is None:
                raise ValueError('当前 FPGA 配置未包含图像处理加速器。')
            began = time.perf_counter()
            if mode == 'original':
                output = frame
            elif backend == 'FPGA':
                output, _ = self.app.video_accelerator.process(frame, mode)
            else:
                output = arm_filter(frame, mode)
            elapsed_ms = (time.perf_counter() - began) * 1000
            now = time.monotonic()
            with self.lock:
                fps = 1 / (now - self.last_frame_at) if self.last_frame_at else 0.0
                self.last_frame_at = now
                self.frames += 1
            canvas = canvas_for_video(frame, output, mode, self.frames, fps, backend)
            self._detect_frame(output)
            ok, result = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if not ok:
                raise RuntimeError('处理结果编码失败。')
            with self.lock:
                self.last_video_canvas = canvas.copy()
                self.last_result_frame = canvas.copy()
                self.last_result_jpeg_bytes = result.tobytes()
                show_video = self.display_mode == 'video'
                self.state.update(active=True, frames=self.frames,
                                  fps=round(fps, 2), video_ms=round(elapsed_ms, 3),
                                  error='')
            if self.app.display and show_video:
                self.app.display.refresh_canvas(canvas)
                if self.app.display.state['error']:
                    raise RuntimeError(self.app.display.state['error'])
            payload = result.tobytes()
            return payload

    def process_audio(self, raw):
        if not raw or len(raw) % 2:
            raise ValueError('音频数据必须是非空 PCM16。')
        count = len(raw) // 2
        if count > self.MAX_AUDIO_SAMPLES:
            raise ValueError('单个音频块不能超过 8192 个采样。')
        return self.process_pcm_samples(np.frombuffer(raw, dtype='<i2')).tobytes()

    def process_pcm_samples(self, pcm):
        """Filter board-captured PCM16; returns filtered int16 samples.

        The 255-sample tail is kept outside the hardware block so switching
        mode/backend never depends on hidden FIR history.  A 960-sample
        crossfade is applied when the mode or backend changes, matching the
        song playback path and avoiding clicks on live microphone audio.
        """
        samples = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if not samples.size:
            return samples
        with self.audio_lock:
            with self.lock:
                if not self.active:
                    raise ValueError('请先启动实时监控。')
                self.last_activity = time.monotonic()
                mode = self.audio_mode
                backend = self.audio_backends.get(str(mode), 'ARM')
                previous = self._audio_applied
            data = samples.astype(np.int32)
            padded = np.concatenate((self.audio_tail, data))
            began = time.perf_counter()
            filtered = self.app.audio.engine.compute(padded, mode, backend)[255:]
            if previous is not None and previous != (mode, backend):
                old = self.app.audio.engine.compute(padded, *previous)[255:]
                fade = min(960, len(filtered), len(old))
                if fade > 0:
                    alpha = np.arange(1, fade + 1, dtype=np.float64) / fade
                    filtered[:fade] = np.rint(
                        old[:fade] * (1 - alpha) + filtered[:fade] * alpha).astype(np.int32)
            elapsed = (time.perf_counter() - began) * 1000
            self._audio_applied = (mode, backend)
            self.audio_tail = padded[-255:].copy()
            output = np.clip(filtered, -32768, 32767).astype('<i2')
            self._detect_audio(samples)
            self.raw_history = np.concatenate((self.raw_history, samples))[-4096:]
            self.filtered_history = np.concatenate((self.filtered_history, output))[-4096:]
            self.state.update(audio_ms=round(elapsed, 3),
                              audio_level=round(float(np.sqrt(
                                  np.mean(samples.astype(np.float64) ** 2))), 1),
                              error='')
        if self.app.display and self.display_mode == 'audio':
            self.app.display.refresh_canvas(self._audio_canvas())
        return output

    def waveform(self, points=256):
        """Downsampled input/output history for the monitor page."""
        with self.audio_lock:
            raw = self.raw_history.copy()
            filtered = self.filtered_history.copy()
        step = max(1, int(np.ceil(len(raw) / max(1, points))))
        return {'raw': raw[::step][:points].astype(int).tolist(),
                'filtered': filtered[::step][:points].astype(int).tolist(),
                'level': float(self.state.get('audio_level', 0.0))}

