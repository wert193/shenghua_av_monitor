"""Prepare a user-supplied MV: matching 30-second video/audio tracks for PYNQ."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
import imageio_ffmpeg
parser=argparse.ArgumentParser()
parser.add_argument('input',type=Path)
parser.add_argument('--start',type=float,default=30)
parser.add_argument('--title',default='上传的 MV')
parser.add_argument('--output',type=Path,default=root/'host'/'media'/'closer_mv')
args=parser.parse_args()
if not args.input.is_file() or args.start<0:parser.error('Input file must exist and start must be non-negative')
args.output.mkdir(parents=True,exist_ok=True)
video=args.output/'video.avi';audio=args.output/'audio.s16le'
ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
# Both outputs use the same input seek and origin. Fixed 15 FPS video is for
# board decode load; audio is always 48 kHz and is never slowed to match video.
command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-ss',str(args.start),'-i',str(args.input),
         '-map','0:v:0','-t','30','-an','-vf','fps=15,scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2',
         '-c:v','mjpeg','-q:v','4',str(video),
         '-map','0:a:0','-t','30','-vn','-ac','1','-ar','48000','-af','aresample=async=0:first_pts=0',
         '-c:a','pcm_s16le','-f','s16le',str(audio)]
subprocess.run(command,check=True,timeout=180)
import cv2
cap=cv2.VideoCapture(str(video))
frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));cap.release()
if frames!=450 or audio.stat().st_size!=30*48000*2:
    raise RuntimeError('The selected MV segment does not contain a full 30 seconds of both tracks; choose an earlier start')
def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
    return digest.hexdigest()
metadata=dict(kind='same_source_mv',source=args.input.name,start_seconds=args.start,duration_seconds=30,
              title=args.title,
              source_sha256=sha(args.input),video_sha256=sha(video),audio_sha256=sha(audio),sample_rate=48000,fps=15)
(args.output/'media.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared:',args.output)
print('Package using: host/deploy/package_live.py --video-effects --mv-dir "'+str(args.output)+'"')
