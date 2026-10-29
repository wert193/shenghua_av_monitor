"""Open the board UI on localhost so the browser can use the computer camera/mic.

Browsers only allow ``getUserMedia`` from a secure origin (HTTPS or localhost).
The board serves plain HTTP on the LAN, so run this proxy on the demo computer
and open ``http://localhost:8765/monitor`` instead of ``http://<board>:8080``.

    python host/deploy/tools/camera_proxy.py --board http://<board-ip>:8080

The proxy listens on 127.0.0.1 only and forwards the page and its API calls.
"""
import argparse
import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def make_handler(board_url):
    target = urlsplit(board_url)
    if target.scheme != 'http' or not target.hostname:
        raise ValueError('Board URL must be an http:// address.')
    port = target.port or 80
    prefix = target.path.rstrip('/')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):
            if self.path not in ('/api/status', '/favicon.ico'):
                super().log_message(fmt, *args)

        def forward(self):
            allowed_hosts = {'localhost:%d' % self.server.server_port,
                             '127.0.0.1:%d' % self.server.server_port}
            if self.headers.get('Host', '').lower() not in allowed_hosts:
                self.send_error(403, 'Open the local demo using localhost.')
                return
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://localhost:%d' % self.server.server_port,
                                         'http://127.0.0.1:%d' % self.server.server_port):
                self.send_error(403, 'Cross-origin request blocked.')
                return
            if not self.path.startswith('/') or self.path.startswith('//'):
                self.send_error(400, 'Invalid path')
                return
            length = int(self.headers.get('Content-Length', '0'))
            if length > 110 * 1024 * 1024:
                self.send_error(413, 'Request too large')
                return
            body = self.rfile.read(length) if length else None
            headers = {'Host': target.netloc, 'Connection': 'close'}
            for name in ('Content-Type', 'Content-Length', 'X-Analysis-Name',
                         'X-Video-Name', 'X-File-Name'):
                value = self.headers.get(name)
                if value is not None:
                    headers[name] = value
            conn = http.client.HTTPConnection(target.hostname, port, timeout=180)
            try:
                conn.request(self.command, prefix + self.path, body=body, headers=headers)
                response = conn.getresponse()
                data = response.read()
                self.send_response(response.status, response.reason)
                for name, value in response.getheaders():
                    if name.lower() not in ('connection', 'transfer-encoding',
                                            'content-length', 'server', 'date'):
                        self.send_header(name, value)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(data)
            except (OSError, http.client.HTTPException) as exc:
                payload = ('Board connection failed: ' + str(exc)).encode('utf-8')
                try:
                    self.send_response(502)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass
            finally:
                conn.close()

        do_GET = forward
        do_POST = forward

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', default=os.environ.get('SHENGHUA_BOARD_URL'),
                        required=os.environ.get('SHENGHUA_BOARD_URL') is None,
                        help='Board web service, e.g. http://<board-ip>:8080')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.board))
    server.daemon_threads = True
    print('Local camera access: http://localhost:%d/monitor' % args.port, flush=True)
    print('Keep this window open during the demonstration. Press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
