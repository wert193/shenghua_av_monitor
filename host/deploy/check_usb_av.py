"""Verify board-side USB camera + microphone capture on a PYNQ-Z2.

Run this on the host while the board application is running and the DE-UVC12
(or another UVC+UAC device) is plugged into the board USB Host port.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description='Check board-side USB camera/microphone capture.')
parser.add_argument('--host', default=os.environ.get('SHENGHUA_BOARD_HOST'),
                    required=os.environ.get('SHENGHUA_BOARD_HOST') is None,
                    help='Board address (or set SHENGHUA_BOARD_HOST).')
parser.add_argument('--seconds', type=float, default=8.0,
                    help='How long to observe after starting capture.')
parser.add_argument('--keep', action='store_true',
                    help='Leave capture running instead of stopping at the end.')
args = parser.parse_args()

client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
base = 'http://' + args.host + ':8080'


def get(route, timeout=10):
    with client.open(base + route, timeout=timeout) as response:
        return json.load(response)


def post(route, data=None, timeout=30):
    body = json.dumps(data or {}).encode()
    request = urllib.request.Request(base + route, body,
                                     {'Content-Type': 'application/json'})
    try:
        with client.open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode('utf-8', errors='replace')) from error


devices = get('/api/monitor/devices')
print('USB devices:')
print('  video nodes:', ', '.join(devices.get('video_nodes') or []) or '(none)')
for item in devices.get('audio') or []:
    print('  audio:', item.get('name'), '->', item.get('alsa'))
if not devices.get('video_nodes'):
    raise SystemExit('No /dev/video* node. Check the board USB port and power.')
if not devices.get('audio'):
    raise SystemExit('No ALSA capture device. Check arecord -l and the USB microphone.')

print('Starting board-side capture...')
post('/api/monitor/usb/start')
started = time.monotonic()
samples = []
status = None
try:
    while time.monotonic() - started < args.seconds:
        status = get('/api/status')
        usb = status.get('usb_capture') or {}
        monitor = status.get('live_monitor') or {}
        samples.append({
            't': round(time.monotonic() - started, 2),
            'video_fps': monitor.get('fps'),
            'frames': monitor.get('frames'),
            'audio_ms': monitor.get('audio_ms'),
            'audio_level': monitor.get('audio_level'),
            'fifo': (usb.get('fifo') or {}).get('level'),
            'underruns': (usb.get('fifo') or {}).get('underruns'),
            'error': usb.get('error') or monitor.get('error') or '',
        })
        if samples[-1]['error']:
            break
        time.sleep(0.5)
finally:
    usb = (status or {}).get('usb_capture') or {}
    monitor = (status or {}).get('live_monitor') or {}
    report = {
        'devices': devices,
        'selected_video': usb.get('video_device', ''),
        'selected_audio': usb.get('audio_device', ''),
        'audio_rate': usb.get('audio_rate', 0),
        'audio_channels': usb.get('audio_channels', 0),
        'audio_output': usb.get('audio_output', False),
        'sink_active': usb.get('sink_active', False),
        'frames': monitor.get('frames', 0),
        'fps': monitor.get('fps', 0),
        'audio_ms': monitor.get('audio_ms', 0),
        'audio_level': monitor.get('audio_level', 0),
        'fifo': usb.get('fifo'),
        'error': usb.get('error') or monitor.get('error') or '',
        'samples': samples,
    }
    if not args.keep:
        try:
            post('/api/monitor/usb/stop')
        except Exception as error:
            report['stop_error'] = str(error)
    destination = Path(__file__).resolve().parents[1] / 'measurements' / 'usb_av_check.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('report:', destination)
    print(json.dumps({k: report[k] for k in ('selected_video', 'selected_audio', 'audio_rate',
                                            'frames', 'fps', 'audio_ms', 'audio_output',
                                            'sink_active', 'error')}, ensure_ascii=False, indent=2))

if report['error']:
    raise SystemExit('FAIL: ' + report['error'])
if not report['frames']:
    raise SystemExit('FAIL: no frames captured')
if not report['audio_rate'] or not report['audio_ms']:
    raise SystemExit('FAIL: no audio blocks processed')
print('PASS: board-side USB video and audio are both active.')
