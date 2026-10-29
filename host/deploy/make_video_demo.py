"""Create a clearly labelled moving test clip, containing only source frames."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[2]
import cv2
import numpy as np
target=root/'hardware'/'live'/'demo_motion.avi'
writer=cv2.VideoWriter(str(target),cv2.VideoWriter_fourcc(*'MJPG'),15,(320,180))
assert writer.isOpened()
for n in range(450):
    frame=np.full((180,320,3),(35,30,25),np.uint8)
    for x in range(0,320,20):cv2.line(frame,(x,45),(x,175),(55,55,55),1)
    cv2.circle(frame,(25+(n*3)%270,95),22,(220,130,30),-1)
    cv2.rectangle(frame,(125,55+(n%45)),(185,95+(n%45)),(20,190,245),-1)
    cv2.putText(frame,'GENERATED TEST VIDEO',(10,20),cv2.FONT_HERSHEY_SIMPLEX,.45,(240,240,240),1)
    cv2.putText(frame,'FRAME %03d  %.1fs'%(n,n/15),(10,40),cv2.FONT_HERSHEY_SIMPLEX,.4,(240,240,240),1)
    writer.write(frame)
writer.release()
print(target,target.stat().st_size)
