"""Regenerate the smooth-only golden vectors used by tb_video_smooth.v.

Writes fpga/src/sim/fpga/src/sim/data/vectors/video_input.hex (the 15x13 test image padded by one
replicated pixel) and fpga/src/sim/fpga/src/sim/data/vectors/video_expected.hex (the ARM reference
result for the smooth effect) with a fixed seed, so the committed fixtures can
be reproduced byte for byte.

The larger four-effect vector set is produced by fpga/fpga/build/scripts/video_effects_vectors.py.
"""
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / 'hardware' / 'live'))
import numpy as np
import cv2
from image_filters import filter_frame

image = np.random.default_rng(42).integers(0, 256, (15, 13, 3), dtype=np.uint8)
padded = cv2.copyMakeBorder(image, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
out = root / 'fpga' / 'src' / 'sim' / 'data' / 'vectors'
out.mkdir(parents=True, exist_ok=True)
for name, frame in (('input', padded), ('expected', filter_frame(image, 'smooth'))):
    words = (frame[:, :, 0].astype(np.uint32)
             | (frame[:, :, 1].astype(np.uint32) << 8)
             | (frame[:, :, 2].astype(np.uint32) << 16))
    (out / f'video_{name}.hex').write_text('\n'.join(f'{int(x):08x}' for x in words.ravel()),
                                           encoding='utf-8')
    print('wrote', out / f'video_{name}.hex')
