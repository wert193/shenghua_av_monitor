"""Minimal ALSA capture through ``libasound`` without the arecord binary.

PYNQ images do not always ship ``alsa-utils``.  The ALSA shared library is
usually present, so this module uses ctypes to open a ``plughw:`` capture
device and read S16_LE frames directly.  It is only used as a fallback when
``arecord`` is unavailable; the arecord path remains the primary one.
"""
import ctypes
import ctypes.util

import numpy as np

SND_PCM_STREAM_CAPTURE = 1
SND_PCM_FORMAT_S16_LE = 2
SND_PCM_ACCESS_RW_INTERLEAVED = 3


class AlsaCaptureError(RuntimeError):
    pass


def _library():
    candidates = ['libasound.so.2', 'libasound.so', 'asound']
    found = ctypes.util.find_library('asound')
    if found:
        candidates.append(found)
    last = None
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError as error:
            last = error
    raise AlsaCaptureError('找不到 libasound（alsa-lib），无法在板端直接采集麦克风：%s' % last)


def alsa_available():
    try:
        _library()
        return True
    except AlsaCaptureError:
        return False


class AlsaCapture:
    """Blocking-ish ALSA capture with a short wait so stop is responsive."""

    def __init__(self):
        self.lib = _library()
        self.handle = ctypes.c_void_p()
        self.rate = 0
        self.channels = 0
        self.lib.snd_pcm_open.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                          ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        self.lib.snd_pcm_open.restype = ctypes.c_int
        self.lib.snd_pcm_set_params.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_uint,
                                                ctypes.c_uint, ctypes.c_int,
                                                ctypes.c_uint]
        self.lib.snd_pcm_set_params.restype = ctypes.c_int
        self.lib.snd_pcm_readi.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_ulong]
        self.lib.snd_pcm_readi.restype = ctypes.c_long
        self.lib.snd_pcm_wait.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.snd_pcm_wait.restype = ctypes.c_int
        self.lib.snd_pcm_recover.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.lib.snd_pcm_recover.restype = ctypes.c_int
        self.lib.snd_pcm_drop.argtypes = [ctypes.c_void_p]
        self.lib.snd_pcm_drop.restype = ctypes.c_int
        self.lib.snd_pcm_close.argtypes = [ctypes.c_void_p]
        self.lib.snd_pcm_close.restype = ctypes.c_int
        self.lib.snd_strerror.argtypes = [ctypes.c_int]
        self.lib.snd_strerror.restype = ctypes.c_char_p

    def _text(self, code):
        message = self.lib.snd_strerror(int(code))
        return message.decode('utf-8', 'replace') if message else str(code)

    def open(self, device, rate, channels, latency_us=100000):
        handle = ctypes.c_void_p()
        error = self.lib.snd_pcm_open(ctypes.byref(handle), str(device).encode('utf-8'),
                                      SND_PCM_STREAM_CAPTURE, 0)
        if error < 0:
            raise AlsaCaptureError('snd_pcm_open(%s) 失败：%s' % (device, self._text(error)))
        error = self.lib.snd_pcm_set_params(handle, SND_PCM_FORMAT_S16_LE,
                                            SND_PCM_ACCESS_RW_INTERLEAVED,
                                            int(channels), int(rate), 1, int(latency_us))
        if error < 0:
            self.lib.snd_pcm_close(handle)
            raise AlsaCaptureError('snd_pcm_set_params(%d Hz/%d ch) 失败：%s'
                                   % (rate, channels, self._text(error)))
        self.handle = handle
        self.rate = int(rate)
        self.channels = int(channels)
        return self

    def wait(self, timeout_ms=200):
        if not self.handle:
            return False
        result = self.lib.snd_pcm_wait(self.handle, int(timeout_ms))
        if result < 0:
            recovered = self.lib.snd_pcm_recover(self.handle, int(result), 1)
            if recovered < 0:
                raise AlsaCaptureError('snd_pcm_wait 失败：%s' % self._text(result))
            return False
        return result > 0

    def read(self, frames):
        if not self.handle:
            return np.zeros(0, dtype='<i2')
        buffer = np.empty(int(frames) * self.channels, dtype='<i2')
        count = self.lib.snd_pcm_readi(self.handle,
                                       buffer.ctypes.data_as(ctypes.c_void_p),
                                       int(frames))
        if count < 0:
            recovered = self.lib.snd_pcm_recover(self.handle, int(count), 1)
            if recovered < 0:
                raise AlsaCaptureError('snd_pcm_readi 失败：%s' % self._text(count))
            return np.zeros(0, dtype='<i2')
        return buffer[:int(count) * self.channels]

    def close(self):
        handle, self.handle = self.handle, None
        if handle:
            self.lib.snd_pcm_drop(handle)
            self.lib.snd_pcm_close(handle)
