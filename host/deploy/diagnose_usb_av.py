"""Run on the PYNQ board to diagnose the USB camera and microphone.

Usage in a Jupyter Notebook cell or Terminal:

    %run ./diagnose_usb_av.py

It does not start the application or change any configuration.
"""
import glob
import json
import subprocess

import cv2


def run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        return (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)


report = {'video_nodes': sorted(glob.glob('/dev/video*')), 'cameras': [],
          'alsa_cards': '', 'arecord': '', 'lsusb_tree': '', 'lsusb': ''}

for path in report['video_nodes']:
    item = {'path': path, 'opened': False, 'read': False, 'shape': None,
            'format': '', 'error': ''}
    try:
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        item['opened'] = bool(cap.isOpened())
        if item['opened']:
            for fourcc in ('MJPG', 'YUYV'):
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                ok, frame = cap.read()
                item['format'] = fourcc
                item['read'] = bool(ok)
                item['shape'] = None if frame is None else list(frame.shape)
                if ok:
                    break
        cap.release()
    except Exception as error:
        item['error'] = str(error)
    report['cameras'].append(item)

report['alsa_cards'] = run(['cat', '/proc/asound/cards'])
report['arecord'] = run(['arecord', '-l'])
report['lsusb_tree'] = run(['lsusb', '-t'])
report['lsusb'] = run(['lsusb'])

print(json.dumps(report, ensure_ascii=False, indent=2))
print()
if not report['video_nodes']:
    print('结论：没有 /dev/video*，先检查大 USB 口供电/线材。')
elif not any(item['read'] for item in report['cameras']):
    print('结论：节点存在但读不到画面；看上面 opened/read 与权限、dmesg。')
else:
    print('结论：摄像头可出图。')
if 'USB' not in report['alsa_cards'].upper() and not report['arecord'].strip():
    print('结论：没有发现 USB 声卡；用 lsusb -t 确认有没有 Class=Audio。')
