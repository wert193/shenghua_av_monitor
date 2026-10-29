"""Verify all video effects and two concurrent audio/video replays on PYNQ."""
import argparse,json,time,urllib.request,urllib.error
from pathlib import Path
parser=argparse.ArgumentParser(description='Run live video-effect validation on a PYNQ board.')
import os
parser.add_argument('--host',default=os.environ.get('SHENGHUA_BOARD_HOST'),required=os.environ.get('SHENGHUA_BOARD_HOST') is None,
                    help='Board address (or set SHENGHUA_BOARD_HOST).')
args=parser.parse_args()
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
base='http://'+args.host+':8080'
def get():
    with client.open(base+'/api/status',timeout=10) as r:return json.load(r)
def post(route,data={}):
    req=urllib.request.Request(base+route,json.dumps(data).encode(),{'Content-Type':'application/json'})
    try:
        with client.open(req,timeout=45) as r:return json.load(r)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode('utf-8',errors='replace')) from error
state=get();assert set(state['video_fpga_modes'])=={'smooth','edge','sharpen','original'}
assert state['audio']['status']=='idle' and state['video']['status']!='playing'
validation=post('/api/benchmark/video-effects')
assert validation['passed']
assert all(m['max_error']==0 and len(m['checks'])>=9 for m in validation['modes'])
print('VALIDATION',json.dumps([{k:m[k] for k in ('mode','max_error','ARM','FPGA','speedup')} for m in validation['modes']]),flush=True)
post('/api/video/backend',{'backend':'FPGA'})
post('/api/video/mode',{'mode':'edge'})
post('/api/audio/backend',{'backend':'FPGA'})
post('/api/audio/mode',{'mode':0})
rounds=[];seen=set()
for index in range(2):
    post('/api/av/start');began=time.monotonic();samples=[];done=set()
    plan=([(8,'/api/video/mode',{'mode':'sharpen'}),(16,'/api/video/mode',{'mode':'smooth'}),(23,'/api/video/mode',{'mode':'original'})] if index==0 else
          [(5,'/api/video/mode',{'mode':'edge'}),(10,'/api/audio/backend',{'backend':'ARM'}),(15,'/api/video/backend',{'backend':'ARM'}),
           (19,'/api/video/backend',{'backend':'FPGA'}),(24,'/api/audio/backend',{'backend':'FPGA'})])
    while time.monotonic()-began<45:
        s=get();samples.append(s);elapsed=time.monotonic()-began
        assert s['video']['status']!='error' and s['audio']['status']!='error',s
        for second,route,data in plan:
            if elapsed>=second and second not in done:post(route,data);done.add(second)
        if s['video']['backend']=='FPGA' and s['video']['frame']>10:seen.add(s['video']['mode'])
        if len(samples)%10==0:print('PLAY',index,round(elapsed,1),s['video']['mode'],s['video']['backend'],s['video']['fps'],flush=True)
        if elapsed>2 and s['audio']['status']=='idle' and s['video']['status']=='ended':break
        time.sleep(.5)
    assert s['audio']['clock']['underruns']==0 and s['audio']['clock']['played']==1440127
    assert s['video']['frame']>=448 and s['video']['backend']=='FPGA',s['video']
    rounds.append({'final':s,'samples':samples})
    print('ROUND',index,s['audio']['last_log'].strip(),flush=True)
    post('/api/video/mode',{'mode':'sharpen'})
assert seen=={'smooth','edge','sharpen','original'},seen
post('/api/audio/mode',{'mode':3})
post('/api/video/mode',{'mode':'edge'})
report=Path(__file__).resolve().parents[2]/'metrics'/'logs'/'video_effects_board_check.json'
report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps({'validation':validation,'rounds':rounds},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS: every FPGA video mode exact, retained backend on effect switches, ARM/FPGA switch, two replays, zero audio underruns')
