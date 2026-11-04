"""Capture a UVC camera and a USB microphone directly on the PYNQ board.

The camera and microphone are expected to be interfaces of the same USB
composite device (for example a Hikvision DE-UVC12 webcam).  Video is read by
OpenCV/V4L2; audio is read by ALSA ``arecord`` and resampled to the FIR's
48 kHz input contract.  Filtered audio is streamed to the board's hardware
FIFO so it can be monitored from the HP MIC jack without a computer.
"""
from pathlib import Path
import os
import select
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

from alsa_capture import AlsaCapture, AlsaCaptureError, alsa_available
from usb_audio import (StreamResampler, choose_audio_device, fifo_drift_ratio,
                       list_alsa_cards, list_audio_devices)

ROOT = Path(__file__).resolve().parent
TARGET_RATE = 48000
READ_FRAMES = 1024
SINK_TARGET = 4096
MAX_VIDEO_WIDTH = 640
MAX_VIDEO_HEIGHT = 480


def _tail(path, limit=900):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return text[-limit:].strip()


class USBCapture:
    """Board-side UVC + USB-audio capture with optional FIFO playback."""

    def __init__(self, monitor, video_device=None, audio_device=None,
                 width=MAX_VIDEO_WIDTH, height=MAX_VIDEO_HEIGHT, fps=15,
                 sample_rate=TARGET_RATE):
        self.monitor = monitor
        self.video_device = video_device or os.environ.get('PYNQ_USB_CAMERA')
        self.audio_device = audio_device or os.environ.get('PYNQ_USB_AUDIO')
        self.width, self.height = width, height
        self.fps = fps
        self.sample_rate = sample_rate
        self.stop_event = threading.Event()
        self.video_thread = None
        self.audio_thread = None
        self.cap = None
        self.audio_process = None
        self.audio_log = None
        self.audio_log_handle = None
        self.audio_capture = None
        self.sink = None
        self.sink_log = None
        self.sink_failures = 0
        self.sink_dropped = 0
        self.resampler = StreamResampler(sample_rate)
        self.lock = threading.RLock()
        self.audio_output = os.environ.get('PYNQ_USB_AUDIO_PLAYBACK', '1') != '0'
        try:
            self.input_gain = min(8.0, max(0.1, float(os.environ.get('PYNQ_USB_MIC_GAIN', '1.0'))))
        except ValueError:
            self.input_gain = 1.0
        self.state = {
            'active': False, 'video_device': '', 'audio_device': '',
            'audio_rate': 0, 'audio_channels': 0, 'video_fps': 0.0,
            'audio_level': 0.0, 'audio_output': self.audio_output,
            'sink_active': False, 'sink_error': '', 'audio_error': '',
            'sink_dropped': 0, 'error': '',
        }

    # ---------------------------------------------------------------- status
    def snapshot(self):
        with self.lock:
            state = dict(self.state)
            state['audio_output'] = bool(self.audio_output)
            state['sink_active'] = bool(self.sink and self.sink.poll() is None)
            state['sink_dropped'] = self.sink_dropped
            state['fifo'] = self._fifo_state()
            return state

    def _fifo_state(self):
        engine = getattr(getattr(self.monitor, 'app'), 'audio', None)
        fifo = getattr(getattr(engine, 'engine', None), 'fifo_mmio', None)
        if fifo is None:
            return None
        try:
            return {'level': int(fifo[2]), 'underruns': int(fifo[1]),
                    'played': int(fifo[0]), 'flags': int(fifo[4])}
        except Exception:
            return None

    def _fifo_level(self):
        state = self._fifo_state()
        return None if state is None else state['level']

    def devices(self):
        """Return a diagnostic snapshot of the board-side USB devices."""
        result = {'video_nodes': sorted(str(p) for p in Path('/dev').glob('video*')),
                  'audio': list_audio_devices(), 'alsa_cards': list_alsa_cards(),
                  'libasound': alsa_available(),
                  'arecord_binary': shutil.which('arecord') or '',
                  'lsusb': '', 'arecord': '',
                  'selected_video': self.state.get('video_device', ''),
                  'selected_audio': self.state.get('audio_device', '')}
        for key, args in (('lsusb', ['lsusb']), ('arecord', ['arecord', '-l'])):
            try:
                run = subprocess.run(args, capture_output=True, text=True, timeout=5,
                                     check=False)
                result[key] = (run.stdout + run.stderr).strip()
            except (OSError, subprocess.SubprocessError) as error:
                result[key] = str(error)
        return result

    # ------------------------------------------------------------- lifecycle
    def start(self):
        if self.state['active']:
            raise ValueError('板端 USB 采集已经启动。')
        audio_backend = bool(shutil.which('arecord')) or alsa_available()
        self.monitor.start(source='usb')
        self.monitor.note_source_activity()
        try:
            self.cap, path, width, height, fps = self._open_camera()
        except Exception:
            self.monitor.stop()
            raise
        self.stop_event.clear()
        self.sink_failures = 0
        self.sink_dropped = 0
        self.resampler.reset()
        audio = self._select_audio() if audio_backend else None
        if not audio_backend:
            audio_error = ('开发板缺少 arecord 和 libasound（alsa-lib），音频采集不可用；'
                           '摄像头画面仍可使用。安装 alsa-utils 或 libasound2 后重启本服务。')
        elif audio:
            audio_error = ''
        else:
            audio_error = ('未找到 USB 麦克风；请检查 /proc/asound/cards 与 PYNQ_USB_AUDIO。'
                           '摄像头画面仍可使用。')
        with self.lock:
            self.state.update(active=True, error='', video_device=path,
                              audio_device=audio['name'] if audio else '',
                              audio_error=audio_error,
                              audio_rate=0, audio_channels=0, video_fps=0.0,
                              audio_level=0.0, sink_error='')
        self.video_thread = threading.Thread(target=self._video_loop, args=(self.cap,),
                                             daemon=True, name='usb-video')
        self.video_thread.start()
        self.monitor.note_source_activity()
        if audio:
            self.audio_thread = threading.Thread(target=self._audio_loop, args=(audio,),
                                                daemon=True, name='usb-audio')
            self.audio_thread.start()
        return self.snapshot()

    def stop(self):
        self.stop_event.set()
        self._terminate_audio()
        for thread in (self.audio_thread, self.video_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=3)
        self._stop_sink()
        cap, self.cap = self.cap, None
        if cap is not None:
            cap.release()
        self.monitor.stop()
        with self.lock:
            self.state['active'] = False
            self.state['video_fps'] = 0.0
            self.state['audio_level'] = 0.0
        return self.snapshot()

    def set_audio_output(self, enabled):
        enabled = bool(enabled)
        self.audio_output = enabled
        with self.lock:
            self.state['audio_output'] = enabled
        if enabled and self.state['active']:
            self._start_sink()
        elif not enabled:
            self._stop_sink()
        return self.snapshot()

    # ---------------------------------------------------------------- camera
    def _open_camera(self):
        if self.video_device:
            candidates = [self.video_device]
        else:
            candidates = sorted(str(p) for p in Path('/dev').glob('video*'))
        errors = []
        for path in candidates:
            cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                errors.append('%s: 无法打开' % path)
                continue
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, frame = cap.read()
                if not ok or frame is None:
                    raise ValueError('已枚举但读不到画面')
                height, width = frame.shape[:2]
                actual_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
                if not (0 < actual_fps < 120):
                    actual_fps = float(self.fps)
            except Exception as error:
                cap.release()
                errors.append('%s: %s' % (path, error))
                continue
            self.width, self.height = width, height
            return cap, path, width, height, actual_fps
        names = '\n'.join('  %s' % item for item in errors) or '  没有 /dev/video* 节点'
        raise ValueError(
            '未找到可用的 USB 摄像头。\n%s\n请确认摄像头插在板卡 USB Host 口，'
            '并用 lsusb、ls -l /dev/video* 检查接线与供电。' % names)

    def _video_loop(self, cap):
        interval = 1.0 / max(1.0, float(self.fps))
        try:
            while not self.stop_event.is_set():
                began = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None:
                    raise RuntimeError('USB 摄像头读取画面失败；请检查 USB 线、供电与设备节点。')
                self.monitor.process_camera_frame(frame)
                self.monitor.note_source_activity()
                elapsed = time.monotonic() - began
                with self.lock:
                    self.state['video_fps'] = round(1.0 / max(1e-3, elapsed), 1)
                self.stop_event.wait(max(0.0, interval - elapsed))
        except Exception as error:
            self._fail(error)
        finally:
            try:
                cap.release()
            except Exception:
                pass

    # ----------------------------------------------------------------- audio
    def _select_audio(self):
        devices = list_audio_devices()
        return choose_audio_device(devices, self.audio_device)

    def _audio_command(self, alsa, rate, channels, tuned):
        command = ['arecord', '-q', '-D', alsa, '-t', 'raw', '-f', 'S16_LE',
                   '-c', str(channels), '-r', str(rate)]
        if tuned:
            command += ['--period-size=1024', '--buffer-size=8192']
        command.append('-')
        return command

    def _open_arecord(self, alsa, rate, channels):
        log_path = ROOT / ('monitor_mic_%d.log' % time.time_ns())
        for tuned in (True, False):
            log = log_path.open('wb')
            try:
                process = subprocess.Popen(
                    self._audio_command(alsa, rate, channels, tuned),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=log, bufsize=0, close_fds=True)
            except OSError as error:
                log.close()
                return None, log_path, str(error)
            time.sleep(.05)
            if process.poll() is None:
                self.audio_log_handle = log
                return process, log_path, ''
            log.close()
            detail = _tail(log_path)
            if 'period-size' not in detail and 'buffer-size' not in detail:
                return None, log_path, detail or ('arecord 退出码 %s' % process.returncode)
        return None, log_path, _tail(log_path) or 'arecord 无法打开设备'

    def _read_exact(self, process, size, timeout):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while len(data) < size:
            if self.stop_event.is_set():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                ready = select.select([process.stdout], [], [], min(remaining, .2))[0]
            except (OSError, ValueError):
                return None
            if not ready:
                if process.poll() is not None:
                    return None
                continue
            try:
                chunk = os.read(process.stdout.fileno(), size - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _audio_loop(self, device):
        if shutil.which('arecord'):
            self._arecord_loop(device)
        else:
            self._alsa_loop(device)

    def _arecord_loop(self, device):
        last_error = ''
        try:
            for rate, channels in ((48000, 1), (48000, 2), (44100, 1),
                                   (44100, 2), (32000, 1), (16000, 1)):
                if self.stop_event.is_set():
                    return
                process, log_path, detail = self._open_arecord(
                    device['alsa'], rate, channels)
                self.audio_log = str(log_path)
                if process is None:
                    last_error = detail
                    continue
                size = READ_FRAMES * 2 * channels
                first = self._read_exact(process, size, 6)
                if first is None:
                    self._terminate_process(process)
                    last_error = _tail(log_path) or ('%s 在 %.0f Hz/%d ch 无数据'
                                                     % (device['alsa'], rate, channels))
                    continue
                self.audio_process = process
                with self.lock:
                    self.state.update(audio_rate=rate, audio_channels=channels,
                                      audio_device='%s (%s)' % (device['name'], device['alsa']),
                                      audio_error='')
                if self.stop_event.is_set():
                    self._terminate_audio()
                    return
                if self.audio_output:
                    self._start_sink()
                self._process_audio(first, rate, channels)
                while not self.stop_event.is_set():
                    raw = self._read_exact(process, size, 2)
                    if raw is None:
                        if self.stop_event.is_set():
                            break
                        raise RuntimeError('USB 麦克风读取中断；请检查 USB 供电与 arecord -l。'
                                           + ('\n' + _tail(log_path) if _tail(log_path) else ''))
                    self._process_audio(raw, rate, channels)
                return
            raise ValueError('无法打开 USB 麦克风（已尝试 48/44.1/32/16 kHz）。'
                             + ('\n' + last_error if last_error else
                                '\n请用 arecord -l 确认设备，并设置 PYNQ_USB_AUDIO=plughw:N,0。'))
        except Exception as error:
            self._fail(error)
        finally:
            self._terminate_audio()
            self._stop_sink()

    def _alsa_loop(self, device):
        """Fallback capture through libasound when arecord is not installed."""
        if not alsa_available():
            raise ValueError('开发板没有 arecord，也没有 libasound；请安装 alsa-utils 或 libasound2。')
        last_error = ''
        try:
            for rate, channels in ((48000, 1), (48000, 2), (44100, 1),
                                   (44100, 2), (32000, 1), (16000, 1)):
                if self.stop_event.is_set():
                    return
                capture = AlsaCapture()
                try:
                    capture.open(device['alsa'], rate, channels)
                except AlsaCaptureError as error:
                    last_error = str(error)
                    capture.close()
                    continue
                self.audio_capture = capture
                with self.lock:
                    self.state.update(audio_rate=rate, audio_channels=channels,
                                      audio_device='%s (%s)' % (device['name'], device['alsa']),
                                      audio_error='')
                if self.stop_event.is_set():
                    capture.close()
                    self.audio_capture = None
                    return
                if self.audio_output:
                    self._start_sink()
                try:
                    while not self.stop_event.is_set():
                        if not capture.wait(200):
                            continue
                        pcm = capture.read(READ_FRAMES)
                        if pcm.size:
                            self._process_audio(pcm.tobytes(), rate, channels)
                finally:
                    capture.close()
                    self.audio_capture = None
                return
            raise ValueError('无法打开 USB 麦克风（ALSA 直连，已尝试 48/44.1/32/16 kHz）。'
                             + ('\n' + last_error if last_error else
                                '\n请检查 /proc/asound/cards 与 PYNQ_USB_AUDIO。'))
        except Exception as error:
            self._fail(error)
        finally:
            self._terminate_audio()
            self._stop_sink()

    def _process_audio(self, raw, rate, channels):
        pcm = np.frombuffer(raw, dtype='<i2')
        if channels == 2:
            pcm = pcm.reshape(-1, 2).astype(np.float32).mean(axis=1)
        if self.input_gain != 1.0:
            pcm = pcm.astype(np.float32) * self.input_gain
        pcm = np.clip(np.rint(pcm), -32768, 32767).astype(np.int16)
        level = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) if pcm.size else 0.0
        ratio = fifo_drift_ratio(self._fifo_level(), SINK_TARGET) if self.audio_output else 1.0
        pcm48 = self.resampler.process(pcm, rate, ratio)
        output = self.monitor.process_pcm_samples(pcm48)
        self.monitor.note_source_activity()
        with self.lock:
            self.state.update(audio_level=round(level, 1), audio_ratio=round(ratio, 6),
                              audio_ms=self.monitor.state.get('audio_ms', 0.0))
        if self.audio_output and output is not None and len(output):
            self._write_sink(output.tobytes())

    def _terminate_process(self, process):
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        try:
            process.stdout.close()
        except (AttributeError, OSError):
            pass

    def _terminate_audio(self):
        process, self.audio_process = self.audio_process, None
        self._terminate_process(process)
        log, self.audio_log_handle = self.audio_log_handle, None
        if log is not None:
            try:
                log.close()
            except OSError:
                pass

    # ------------------------------------------------------------------ sink
    def _sink_binary(self):
        source = ROOT / 'pcm_stream_sink.c'
        binary = ROOT / 'pcm_stream'
        if not source.is_file():
            raise RuntimeError('安装包缺少 pcm_stream_sink.c，无法板载监听。')
        if binary.is_file() and binary.stat().st_mtime >= source.stat().st_mtime:
            return binary
        if shutil.which('gcc') is None:
            raise RuntimeError('开发板缺少 gcc，无法编译板载音频输出程序。')
        try:
            subprocess.run(['gcc', '-O3', '-Wall', '-Wextra', str(source), '-o', str(binary)],
                           check=True, timeout=60, capture_output=True)
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or b'').decode('utf-8', 'replace')[-600:]
            raise RuntimeError('编译 pcm_stream_sink.c 失败：' + (detail or str(error)))
        return binary

    def _start_sink(self):
        if not self.audio_output:
            return False
        if self.sink and self.sink.poll() is None:
            return True
        if self.sink is not None:
            self._stop_sink(keep_state=True)
        engine = getattr(getattr(self.monitor, 'app'), 'audio', None)
        engine = getattr(engine, 'engine', None)
        uio = getattr(engine, 'uio', None)
        if getattr(engine, 'fifo_mmio', None) is None or not uio:
            with self.lock:
                self.state['sink_error'] = '当前安装包不含硬件音频 FIFO，声音仅分析、不板载播放。'
            return False
        try:
            binary = self._sink_binary()
            log_path = ROOT / ('monitor_audio_%d.log' % time.time_ns())
            log = log_path.open('wb')
            sink = subprocess.Popen([str(binary), str(uio), '/dev/i2c-1', '65536'],
                                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                    bufsize=0, close_fds=True)
            os.set_blocking(sink.stdin.fileno(), False)
        except Exception as error:
            with self.lock:
                self.state['sink_error'] = '板载音频输出启动失败：%s' % error
            return False
        self.sink, self.sink_log = sink, log
        with self.lock:
            self.state.update(sink_error='', sink_active=True)
        return True

    def _write_sink(self, data):
        if self.sink is None and self.state.get('sink_error'):
            return
        data = memoryview(data)
        deadline = time.monotonic() + 2.0
        while data and not self.stop_event.is_set():
            sink = self.sink
            if sink is None or sink.poll() is not None:
                if not self._restart_sink():
                    return
                continue
            if time.monotonic() > deadline:
                self.sink_dropped += 1
                return
            try:
                _, writable, _ = select.select([], [sink.stdin], [], .1)
            except (OSError, ValueError):
                self._restart_sink()
                continue
            if not writable:
                continue
            try:
                written = os.write(sink.stdin.fileno(), data)
            except BlockingIOError:
                continue
            except (BrokenPipeError, OSError):
                self._restart_sink()
                continue
            data = data[written:]

    def _restart_sink(self):
        self._stop_sink(keep_state=True)
        if self.sink_failures >= 3:
            with self.lock:
                self.state['sink_error'] = '板载音频输出连续退出；请检查 UIO/FIFO 是否被其他程序占用。'
            return False
        self.sink_failures += 1
        return self._start_sink()

    def _stop_sink(self, keep_state=False):
        sink, self.sink = self.sink, None
        log, self.sink_log = self.sink_log, None
        if sink is not None:
            try:
                if sink.stdin:
                    sink.stdin.close()
            except (OSError, ValueError):
                pass
            if sink.poll() is None:
                sink.terminate()
                try:
                    sink.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    sink.kill()
                    sink.wait(timeout=2)
        if log is not None:
            try:
                log.close()
            except OSError:
                pass
        if not keep_state:
            with self.lock:
                self.state['sink_active'] = False

    def _fail(self, error):
        message = str(error)
        with self.lock:
            self.state['error'] = message
        self.monitor.set_source_error(message)
        self.stop_event.set()
