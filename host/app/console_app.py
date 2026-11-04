"""Shenghua board control server. Python standard library HTTP, LAN use."""
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
import argparse
import json
import sys
import threading
import time
import socket
import os

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))


class Application:
    def __init__(self, root=ROOT, audio=None, image=None):
        self.root = Path(root)
        (self.root/'data').mkdir(parents=True, exist_ok=True)
        if audio is None:
            from audio_engine import AudioEngine
            audio = AudioEngine(self.root)
        if image is None:
            from image_engine import ImageEngine
            image = ImageEngine(self.root)
        self.audio, self.image = audio, image
        self.gate = threading.RLock()
        self.benchmark_state = {'status': 'idle', 'error': ''}

    def status(self):
        marker = self.root/'installed.sha256'
        return {'project': 'shenghua', 'version': '0.4.0', 'pid': getattr(self, 'server_pid', os.getpid()),
                'build_id': marker.read_text().strip() if marker.exists() else 'development',
                'audio': self.audio.snapshot(), 'image': self.image.snapshot(),
                'benchmark': dict(self.benchmark_state), 'fpga_available': False,
                'hdmi_available': False, 'video_available': False}

    def action(self, route, data):
        with self.gate:
            if route == '/api/audio/stop':
                self.audio.stop()
                return {'ok': True}
            if route == '/api/audio/mode':
                mode = data.get('mode')
                if type(mode) is not int:
                    raise ValueError('模式必须为整数')
                self.audio.mode(mode)
                return {'ok': True}
            if self.benchmark_state['status'] == 'running':
                raise ValueError('正在固定参数测量，请稍候')
            if route == '/api/audio/start':
                self.audio.start()
            elif route == '/api/image/mode':
                self.image.select(data.get('mode'))
            elif route == '/api/benchmark/arm':
                if self.audio.snapshot()['status'] in ('starting', 'running', 'stopping'):
                    raise ValueError('请先停止音频，再进行单图像基线测量')
                self.benchmark_state = {'status': 'running', 'error': ''}
                threading.Thread(target=self._benchmark, daemon=True).start()
            else:
                raise ValueError('未知操作')
            return {'ok': True}

    def upload(self, raw):
        with self.gate:
            if self.benchmark_state['status'] == 'running':
                raise ValueError('测量期间不能更换素材')
            self.image.upload(raw)

    def _benchmark(self):
        try:
            self.image.benchmark()
            self.benchmark_state = {'status': 'done', 'error': ''}
        except Exception as exc:
            self.benchmark_state = {'status': 'error', 'error': str(exc)}

    def export(self):
        records = []
        for p in sorted((self.root/'data').glob('*/report.json'))[-30:]:
            records.append({'id': p.parent.name, 'report': json.loads(p.read_text())})
        sessions = []
        for p in sorted((self.root/'data').glob('*/session.json'))[-30:]:
            sessions.append({'id': p.parent.name, 'session': json.loads(p.read_text())})
        return {'project': 'shenghua', 'version': '0.2.0', 'state': self.status(),
                'image_measurements': records, 'audio_sessions': sessions,
                'limitations': 'ARM only; static image; supplied song with live FIR, mono, independent of image. No A/V synchronization or FPGA result.'}


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Avoid a log entry for every status poll.
            if not self.path.startswith(('/api/status', '/image/')):
                super().log_message(fmt, *args)

        def reply(self, body, content_type='application/json; charset=utf-8', status=200, download=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if download:
                self.send_header('Content-Disposition', 'attachment; filename="shenghua_results.json"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            route = urlsplit(self.path).path
            try:
                if route == '/':
                    self.reply((app.root/'web'/'index.html').read_bytes(), 'text/html; charset=utf-8')
                elif route == '/api/status':
                    self.reply(app.status())
                elif route == '/api/export':
                    self.reply(app.export(), download=True)
                elif route in ('/image/original.jpg', '/image/processed.jpg'):
                    self.reply(app.image.jpeg('original' if 'original' in route else 'processed'), 'image/jpeg')
                else:
                    self.reply({'error': 'Not found'}, status=404)
            except Exception as exc:
                self.reply({'error': str(exc)}, status=500)

        def do_POST(self):
            route = urlsplit(self.path).path
            try:
                self.connection.settimeout(15)
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    self.reply({'error': 'Origin mismatch'}, status=403)
                    return
                length = int(self.headers.get('Content-Length', '0'))
                limit = 10*1024*1024 if route == '/api/image/upload' else 4096
                if length <= 0 or length > limit:
                    self.reply({'error': '上传内容过大或为空'}, status=413)
                    self.close_connection = True
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('请求不完整')
                if route == '/api/image/upload':
                    app.upload(raw)
                    result = {'ok': True}
                else:
                    if not self.headers.get('Content-Type', '').startswith('application/json'):
                        raise ValueError('Expected application/json')
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError('Expected an object')
                    result = app.action(route, data)
                self.reply(result)
            except (ValueError, OSError) as exc:
                self.reply({'error': str(exc)}, status=400)
            except Exception as exc:
                self.reply({'error': str(exc)}, status=500)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    import fcntl
    (ROOT/'data').mkdir(exist_ok=True)
    lock = (ROOT/'data'/'server.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('作品服务已经运行，不要重复启动。')
    app = Application()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(app))
    server.daemon_threads = True
    import signal
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    print(f'Shenghua 0.2.0 ready on port {args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.audio.close()
        server.server_close()
        lock.close()


if __name__ == '__main__':
    main()
