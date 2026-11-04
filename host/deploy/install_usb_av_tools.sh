#!/usr/bin/env bash
# Install the user-space USB camera/microphone tools on a PYNQ-Z2 board.
# UVC (camera) and UAC (microphone) drivers are already in the PYNQ kernel;
# this script installs the command-line tools used for diagnostics/capture:
#   alsa-utils -> arecord
#   v4l-utils  -> v4l2-ctl
#   usbutils   -> lsusb
# Run it in a PYNQ Terminal:  bash install_usb_av_tools.sh
set -u

echo "== PYNQ USB A/V tool setup =="
uname -a || true
if [ -r /etc/os-release ]; then . /etc/os-release; echo "OS: ${PRETTY_NAME:-unknown}"; fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: apt-get not found; this image is not Debian/Ubuntu based."
  exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

echo
echo "== 1/3 apt update =="
if ! $SUDO apt-get update; then
  echo "WARNING: apt-get update failed (no network or DNS)."
  echo "         If packages are already cached, the install step may still work."
fi

echo
echo "== 2/3 install alsa-utils v4l-utils usbutils =="
if ! $SUDO apt-get install -y alsa-utils v4l-utils usbutils; then
  echo "ERROR: package install failed."
  echo "Check the board network (ping 8.8.8.8), then retry."
  exit 1
fi

echo
echo "== 3/3 load standard USB drivers =="
$SUDO modprobe uvcvideo 2>/dev/null || echo "uvcvideo: already loaded or unavailable"
$SUDO modprobe snd-usb-audio 2>/dev/null || echo "snd-usb-audio: already loaded or unavailable"

echo
echo "== camera nodes =="
ls -l /dev/video* 2>/dev/null || echo "no /dev/video*"
echo
echo "== USB tree =="
lsusb -t 2>/dev/null || echo "lsusb not available"
echo
echo "== ALSA cards =="
cat /proc/asound/cards 2>/dev/null || echo "no /proc/asound/cards"
echo
echo "== capture devices (arecord -l) =="
arecord -l 2>/dev/null || echo "arecord still not available"
echo
echo "== v4l2 formats (first node) =="
if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl --list-devices 2>/dev/null || true
  v4l2-ctl --list-formats-ext -d /dev/video0 2>/dev/null || true
else
  echo "v4l2-ctl not installed"
fi
echo
echo "Done. If /proc/asound/cards has no USB card, the camera may be video-only;"
echo "check 'lsusb -t' for a Class=Audio interface before assuming a driver problem."
