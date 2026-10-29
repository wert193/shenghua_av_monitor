from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root/'hardware'/'live'))
import numpy as np
import cv2
from image_filters import filter_frame
rng=np.random.default_rng(73)
checker=((np.indices((240,320)).sum(axis=0)%2)*255).astype(np.uint8)
impulse=np.zeros((7,9,3),np.uint8);impulse[0,0]=255;impulse[3,4]=255;impulse[-1,-1]=255
images=[rng.integers(0,256,(15,13,3),dtype=np.uint8),np.full((1,1,3),255,np.uint8),
        np.repeat(checker[:,:,None],3,axis=2),impulse,
        rng.integers(0,256,(1,19,3),dtype=np.uint8),rng.integers(0,256,(17,1,3),dtype=np.uint8)]
words=[len(images)*4]
def pack(frame):
    p=frame.astype(np.uint32)
    return (p[:,:,0]|p[:,:,1]<<8|p[:,:,2]<<16).ravel().tolist()
for image in images:
    h,w=image.shape[:2]
    for mode_id,mode in enumerate(('smooth','edge','sharpen','original')):
        source=pack(cv2.copyMakeBorder(image,1,1,1,1,cv2.BORDER_REPLICATE))
        expected=pack(filter_frame(image,mode))
        words.extend([w,mode_id,len(source),len(expected),*source,*expected])
out=root/'fpga'/'src'/'build'/'video_effects_sim';out.mkdir(parents=True,exist_ok=True)
(out/'vectors.hex').write_text('\n'.join(f'{int(v):08x}' for v in words))
print('Generated',len(images)*4,'cases;',len(words),'words')
