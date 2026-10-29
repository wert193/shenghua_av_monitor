"""Board-only audio controller. Single owner of the existing base overlay."""
from pathlib import Path
import subprocess
import threading
import queue
import time
import json
import re
import hashlib
import asyncio


class AudioEngine:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.thread = None
        self.state = {'status': 'idle', 'mode': 3, 'requested_mode': 3, 'track': 'Closer',
                      'error': '', 'elapsed': 0, 'last_log': '', 'events': []}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('音频已在运行或停止中')
            self.commands = queue.Queue()
            self.state.update(status='starting', error='', elapsed=0, events=[], last_log='')
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def mode(self, mode):
        if mode not in (0, 1, 2, 3):
            raise ValueError('模式必须为低通、高通、带通或原曲')
        with self.lock:
            self.state['requested_mode'] = mode
            if self.state['status'] in ('starting', 'running'):
                self.commands.put(str(mode).encode('ascii'))

    def stop(self):
        with self.lock:
            if self.state['status'] in ('starting', 'running'):
                self.state['status'] = 'stopping'
                self.commands.put(b'q')

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=8)

    def _update(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _run(self):
        # PYNQ creates asyncio-backed objects during BaseOverlay construction.
        # Python worker threads do not receive an event loop automatically.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self._run_session()
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def _run_session(self):
        base = None
        p = None
        output = None
        session_lock = None
        folder = self.root / 'data' / ('audio_' + str(time.time_ns()))
        folder.mkdir(parents=True)
        log = folder / 'native.log'
        try:
            import fcntl
            import numpy as np
            from scipy.signal import firwin
            from pynq.overlays.base import BaseOverlay
            from pynq.lib.audio import AudioADAU1761
            song = self.root / 'media' / 'closer.s16le'
            song_bytes = song.stat().st_size
            if song_bytes < 2 or song_bytes % 2 or song_bytes > 48000*600*2:
                raise ValueError('歌曲文件格式不正确')
            duration = song_bytes / (48000*2)
            song_meta = json.loads((song.parent/'closer.json').read_text(encoding='utf-8'))
            with song.open('rb') as song_file:
                hasher = hashlib.sha256()
                for block in iter(lambda: song_file.read(1024*1024), b''):
                    hasher.update(block)
            if hasher.hexdigest() != song_meta['pcm_sha256']:
                raise ValueError('歌曲校验失败，请重新上传完整安装包')
            self._update(duration=duration, source_sha256=song_meta['pcm_sha256'])
            # The legacy helper's UIO flock remains the second line of defense.
            session_lock = (self.root / 'data' / 'audio.lock').open('a')
            fcntl.flock(session_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            base = BaseOverlay('base.bit', download=False)
            if not base.is_loaded() or not isinstance(base.audio, AudioADAU1761):
                raise RuntimeError('基础配置不匹配。请正常开机，不要运行其他下载 FPGA 的程序。')
            audio = base.audio
            uio = int(audio.uio_index)
            name = (Path('/sys/class/uio') / f'uio{uio}' / 'name').read_text().strip()
            if name != 'audio-codec-ctrl':
                raise RuntimeError('音频 UIO 不匹配')
            coeffs = np.asarray([firwin(255, 800, fs=48000),
                                firwin(255, 3000, pass_zero=False, fs=48000),
                                firwin(255, [800, 2500], pass_zero=False, fs=48000)], dtype='<f4')
            coeff_file = folder / 'coefficients.f32'
            coeffs.tofile(coeff_file)
            source = self.root / 'src' / 'audio_live.c'
            build = self.root / 'build'
            build.mkdir(exist_ok=True)
            digest = hashlib.sha256(source.read_bytes() + (source.parent/'pcm_source.h').read_bytes()).hexdigest()[:16]
            exe = build / ('audio_' + digest)
            if not exe.exists():
                result = subprocess.run(['gcc', '-std=gnu11', '-O3', '-Wall', '-Wextra',
                                         str(source), '-lm', '-o', str(exe)], capture_output=True,
                                        text=True, timeout=60)
                (folder / 'compile.log').write_text(result.stdout+result.stderr)
                if result.returncode:
                    raise RuntimeError('编译失败：' + result.stderr)
            if self.snapshot()['status'] == 'stopping':
                self._update(status='idle')
                return
            output = log.open('w')
            p = subprocess.Popen([str(exe), f'/dev/uio{uio}', f'/dev/i2c-{audio.iic_index}',
                                  str(audio.mmio.length), str(coeff_file), str(song)], stdin=subprocess.PIPE,
                                 stdout=output, stderr=subprocess.STDOUT)
            start = time.monotonic()
            self._update(status='running', mode=3)
            self.commands.put(str(self.snapshot()['requested_mode']).encode('ascii'))
            candidate = (0, 0, 0, 0)
            stable = None
            since = start
            last_heartbeat = last_log = 0
            offset = 0
            active_mode = -1

            def send(data):
                try:
                    p.stdin.write(data)
                    p.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

            while p.poll() is None:
                now = time.monotonic()
                if now-start > duration*1.25+15:
                    raise TimeoutError('音频运行超过时限')
                if now-last_heartbeat > 0.5:
                    send(b'h')
                    last_heartbeat = now
                    self._update(elapsed=round(now-start, 1))
                for _ in range(32):
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    send(command)
                pressed = tuple(int(base.buttons[i].read()) for i in range(4))
                if pressed != candidate:
                    candidate, since = pressed, now
                if now-since >= 0.03 and candidate != stable:
                    old, stable = stable, candidate
                    if old is not None and not any(old) and sum(stable) == 1:
                        button = stable.index(1)
                        if button == 3:
                            self.stop()
                        else:
                            self.mode(button)
                        with self.lock:
                            self.state['events'].append({'seconds': round(now-start, 3), 'button': button})
                if now-last_log > 0.25:
                    with log.open() as reader:
                        reader.seek(offset)
                        lines = reader.read()
                        offset = reader.tell()
                    for match in re.finditer(r'Mode=(\d) at sample=(\d+)', lines):
                        self._update(mode=int(match[1]))
                    last_log = now
                applied = self.snapshot()['mode']
                if active_mode != applied:
                    for i in range(4):
                        base.leds[i].write(int(i == applied))
                    active_mode = applied
                time.sleep(0.01)
            if p.returncode:
                raise RuntimeError('音频进程异常退出：' + log.read_text()[-1600:])
            self._update(status='idle')
        except Exception as exc:
            self._update(status='error', error=str(exc))
        finally:
            if p is not None:
                if p.poll() is None:
                    try:
                        p.stdin.write(b'q')
                        p.stdin.flush()
                        p.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        p.terminate()
                        try:
                            p.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            p.kill()
                            p.wait()
                            self._update(status='error', error='音频被强制停止；静音状态未确认，请调低音响。')
                p.stdin.close()
            if output:
                output.close()
            if base:
                for i in range(4):
                    try:
                        base.leds[i].off()
                    except Exception:
                        pass
            if session_lock:
                session_lock.close()
            self._update(last_log=log.read_text()[-2500:] if log.exists() else '')
            (folder / 'session.json').write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding='utf-8')
