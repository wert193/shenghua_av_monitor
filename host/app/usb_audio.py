"""USB audio discovery and stream resampling for board-side capture.

This module deliberately has no OpenCV/PYNQ dependency so it can be tested on
the host.  The board's USB microphone and UVC camera usually enumerate as two
interfaces of the same composite device (for example a DE-UVC12 webcam).
"""
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

TARGET_RATE = 48000
AUDIO_KEYS = ('USB', 'UVC', 'CAMERA', 'HIKVISION', 'DE-UVC', 'MICROPHONE', 'MIC')


def list_alsa_cards(root='/proc/asound'):
    """Read ``/proc/asound/cards`` without requiring alsa-utils.

    This is the fallback used when ``arecord`` is not installed.  USB cards
    usually expose ``/proc/asound/cardN/usbid``; the card name is also checked
    because some kernels omit that file.  ``root`` is injectable for host tests.
    """
    base = Path(root)
    path = base / 'cards'
    if not path.is_file():
        return []
    cards = []
    pattern = re.compile(r'^\s*(\d+)\s+\[([^\]]+)\]:\s*(.*)$')
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        card = int(match.group(1))
        card_id = match.group(2).strip()
        name = match.group(3).strip() or card_id
        usbid = ''
        usb_file = base / ('card%d' % card) / 'usbid'
        if usb_file.is_file():
            try:
                usbid = usb_file.read_text(encoding='utf-8', errors='replace').strip()
            except OSError:
                usbid = ''
        usb = bool(usbid) or any(key in (card_id + ' ' + name).upper()
                                 for key in AUDIO_KEYS)
        cards.append({'card': card, 'device': 0, 'id': card_id, 'name': name,
                      'alsa': 'plughw:%d,0' % card, 'usb': usb, 'usbid': usbid})
    return cards


def list_audio_devices(root='/proc/asound'):
    """Return ALSA capture devices, preferring ``arecord -l`` when available.

    Each item contains card/device numbers, a human readable name and a
    ``plughw:CARD,DEVICE`` string suitable for ``arecord -D``.
    """
    cards = list_alsa_cards(root)
    if not shutil.which('arecord'):
        return cards
    try:
        result = subprocess.run(['arecord', '-l'], capture_output=True, text=True,
                                timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return cards
    devices = []
    pattern = re.compile(
        r'card\s+(\d+):\s*([^\[]*)\[([^\]]*)\],\s*device\s+(\d+):\s*([^\[]*)\[([^\]]*)\]')
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        card = int(match.group(1))
        device = int(match.group(4))
        name = ' '.join(part.strip() for part in match.group(2, 3, 5, 6) if part.strip())
        devices.append({
            'card': card,
            'device': device,
            'name': name or ('card %d device %d' % (card, device)),
            'alsa': 'plughw:%d,%d' % (card, device),
        })
    return devices or cards


def choose_audio_device(devices, preferred=None):
    """Pick a USB-like capture device, honouring an explicit override.

    ``preferred`` may be a full ALSA name (``plughw:1,0``), a card number, or
    a substring of the device name.  Returns a device dict or ``None``.
    """
    devices = list(devices)
    if not devices:
        return None
    if preferred:
        text = str(preferred).strip()
        lowered = text.lower()
        for item in devices:
            if lowered == item['alsa'].lower() or lowered == item['name'].lower():
                return item
        if text.isdigit():
            for item in devices:
                if item['card'] == int(text):
                    return item
        for item in devices:
            if lowered in item['name'].lower() or lowered in item['alsa'].lower():
                return item
        # An explicit plughw:/hw: string was supplied but is not listed.  Keep
        # it usable so the operator can bypass a stale arecord cache.
        if lowered.startswith(('plughw:', 'hw:', 'default')):
            return {'card': -1, 'device': 0, 'name': text, 'alsa': text}
    usb = [item for item in devices
           if any(key in item['name'].upper() for key in AUDIO_KEYS)]
    return (usb or devices)[0]


class StreamResampler:
    """Block-wise linear resampler with fractional carry and drift control.

    ``ratio`` slightly above 1 produces more output samples (used when the
    hardware FIFO is running low), slightly below 1 produces fewer samples.
    The carry keeps the sample phase continuous across blocks, so a slow clock
    difference does not accumulate into a growing latency.
    """

    def __init__(self, target_rate=TARGET_RATE):
        self.target_rate = int(target_rate)
        self.carry = 0.0
        self.last_ratio = 1.0

    def reset(self):
        self.carry = 0.0
        self.last_ratio = 1.0

    def process(self, pcm, source_rate, ratio=1.0):
        samples = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return np.zeros(0, dtype=np.int16)
        ratio = float(ratio)
        if not np.isfinite(ratio) or ratio <= 0:
            ratio = 1.0
        ratio = min(1.02, max(.98, ratio))
        step = float(source_rate) / (self.target_rate * ratio)
        if step <= 0 or not np.isfinite(step):
            return np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
        if self.carry < 0 or self.carry >= samples.size:
            self.carry = 0.0
        # Include the position at the end of the block; np.interp clamps it to
        # the last sample.  This keeps the output count exact (3x for 16 kHz)
        # and leaves the fractional phase for the next block.
        count = int(np.ceil((samples.size - self.carry) / step))
        if count < 1:
            count = 1
        positions = self.carry + np.arange(count, dtype=np.float64) * step
        output = np.interp(positions, np.arange(samples.size, dtype=np.float64), samples)
        self.carry = float(self.carry + count * step - samples.size)
        if self.carry < 0:
            self.carry = 0.0
        self.last_ratio = ratio
        return np.clip(np.rint(output), -32768, 32767).astype(np.int16)


def fifo_drift_ratio(level, target=4096, span=8192):
    """Convert FIFO fill level into a small resampling ratio correction."""
    if level is None:
        return 1.0
    try:
        level = float(level)
    except (TypeError, ValueError):
        return 1.0
    error = (float(target) - level) / max(1.0, float(span))
    return 1.0 + min(.01, max(-.01, error * .08))


if __name__ == '__main__':  # pragma: no cover - board-side diagnostic
    import json
    print(json.dumps({'cards': list_alsa_cards(), 'devices': list_audio_devices()},
                     ensure_ascii=False, indent=2))
