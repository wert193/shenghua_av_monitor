"""Package the combined audio design and a user-authorized 30-second excerpt."""
from pathlib import Path
import base64,hashlib,io,json,sys,wave,zipfile,html as html_escape
REPO=Path(__file__).resolve().parents[2]
FPGA=REPO/'fpga'
SRC=FPGA/'src'
APP=REPO/'host'/'app'
sys.path.insert(0,str(SRC/'board'))
from check_hardware import check_reset
avsync='--avsync' in sys.argv
video_effects='--video-effects' in sys.argv
video_fpga='--video-fpga' in sys.argv or video_effects
if video_fpga:avsync=True
mv_dir=Path(sys.argv[sys.argv.index('--mv-dir')+1]) if '--mv-dir' in sys.argv else None
if mv_dir and not avsync:raise ValueError('--mv-dir requires --avsync')
if avsync and mv_dir is None and not video_effects:
    raise SystemExit('For synchronized playback, prepare an authorized MV and pass --mv-dir. Media is not included in this repository.')
video='--video' in sys.argv or avsync
hdmi='--hdmi' in sys.argv or video
build=SRC/'build'/('video_effects_output' if video_effects else 'video_fpga_output' if video_fpga else 'avsync_output' if avsync else 'hdmi_output' if hdmi else 'live_output')
if not (build/'BUILD_OK').is_file() and video_effects:
    build=FPGA/'build'
assert (build/'BUILD_OK').is_file()
if video_effects:
    from check_hardware import check_reset
    check_reset(build/'audio_live.hwh')
assert 'All user specified timing constraints are met.' in (build/'timing.rpt').read_text()
check_reset(build/'audio_live.hwh')
if hdmi:
    import xml.etree.ElementTree as ET
    handoff=ET.parse(build/'audio_live.hwh')
    ranges={m.get('INSTANCE'):m for m in handoff.iter('MEMRANGE')}
    assert ranges['screen_bram'].get('BASEVALUE')=='0x42000000'
    assert ranges['screen_bram'].get('HIGHVALUE')=='0x4207FFFF'
    assert ranges['screen_control'].get('BASEVALUE')=='0x41260000'

files={p.name:p.read_bytes() for p in (APP).glob('*') if p.suffix in ('.py','.c')}
if video_effects:
    files['video_effects.json']=json.dumps({'modes':{'smooth':0,'edge':1,'sharpen':2,'original':3},'mode_bits':[20,21]}).encode()
    files['web/monitor.html']=(APP/'monitor.html').read_bytes()
    files['usb_capture.py']=(APP/'usb_capture.py').read_bytes()
if not video:
    files.pop('video_app.py',None)
    files.pop('video_engine.py',None)
elif mv_dir:
    media=json.loads((mv_dir/'media.json').read_text(encoding='utf-8'))
    files['demo_motion.avi']=(mv_dir/'video.avi').read_bytes()
    assert hashlib.sha256(files['demo_motion.avi']).hexdigest()==media['video_sha256']
    files['media.json']=json.dumps(media,ensure_ascii=False).encode()
else:
    demo=APP/'demo_motion.avi'
    if not demo.is_file():
        import runpy
        runpy.run_path(str(REPO/'host'/'deploy'/'make_video_demo.py'))
    files['demo_motion.avi']=(APP/'demo_motion.avi').read_bytes()
if avsync:
    files['pcm_sink.c']=(APP/'pcm_fifo_sink.c').read_bytes()
    files['avsync.json']=json.dumps({'sample_rate':48000,'fifo_depth':8192,'clock':'hardware_samples'}).encode()
integrated='--integrated' in sys.argv or hdmi
if integrated:
    files['console_app.py']=(APP/'console_app.py').read_bytes()
    for name in ('image_engine.py','image_filters.py'):
        files[name]=(APP/name).read_bytes()
    files['web/index.html']=(APP/'console.html').read_bytes()
    if hdmi:
        html=files['web/index.html'].decode('utf-8')
        html=html.replace('HDMI 显示、连续视频及音画同步尚未接入。','外接屏显示同一组左右图片；连续视频及音画同步尚未接入。')
        html=html.replace('FPGA 图像滤波、HDMI 输出','FPGA 图像滤波')
        html=html.replace('<h2>画面处理</h2>','<h2>画面处理 · HDMI 左右同屏</h2>')
        html=html.replace('<div class="card"><h2>基线数据</h2>', '<div class="card"><h2>外接显示器</h2><p id="hdmiStatus">正在初始化输出…</p><button id="hdmiRefresh" onclick="act(\'/api/hdmi/refresh\')">刷新外接屏</button><p class="sub">HDMI OUT → 显示器 HDMI 输入。720p60 信号，内部 640×360 双缓冲画布、256 色。换图或切换图片效果后自动更新；音频仍由 HP MIC 输出。状态只确认板端输出，不检测显示器是否接好。</p></div><div class="card"><h2>基线数据</h2>')
        html=html.replace("const am=s.audio_measurement;", "$('hdmiStatus').textContent=s.hdmi.error||('板端状态：'+s.hdmi.status+' · 已更新 '+s.hdmi.frames+' 次');$('hdmiRefresh').disabled=busy||measuring;const am=s.audio_measurement;")
        if video:
            html=html.replace('外接屏显示同一组左右图片；连续视频及音画同步尚未接入。','支持上传视频逐帧处理并同步送到网页与外接屏；音画同步尚未接入。')
            html=html.replace('待完成：FPGA 图像滤波、HDMI 输出、真实视频与音频同步、完整分轮性能对比。','待完成：FPGA 视频滤波、音画同步和完整分轮性能对比。')
            html=html.replace('集成开发版 0.3 · ARM / FPGA 音频','视频开发版 0.4 · ARM 视频 / ARM/FPGA 音频')
            html=html.replace('<div class="grid"><section>','<div class="grid"><section>'+(APP/'video_panel.html').read_text(encoding='utf-8'))
            html=html.replace("const am=s.audio_measurement;", "showVideo(s.video);showVideoFpga(s);const am=s.audio_measurement;")
            html=html.replace('setTimeout(loop,1000)','setTimeout(loop,200)')
            html=html.replace('</script></body>',(APP/'video_client.js').read_text(encoding='utf-8')+'</script></body>')
            if avsync:
                html=html.replace('<h2>实时视频处理</h2>','<h2>音画同步 · 硬件音频时钟</h2><div class="row"><button class="primary" onclick="act(\'/api/av/start\')">同步播放音乐与视频</button><button onclick="act(\'/api/av/stop\')">全部停止</button></div><p class="sub">当前为 Closer 音乐 + 动态测试画面，验证同步链路；取得 MV 后换成同源音轨和画面。</p>')
                html=html.replace('尚未实现音画同步。','同步播放按音频硬件时钟推进，视频来不及时跳帧。')
                html=html.replace('showVideo(s.video);','showVideo(s.video);if(s.audio.clock){const c=s.audio.clock;$(\'videoInfo\').textContent+=\' · 音频实播 \'+c.seconds.toFixed(2)+\' s · 硬件缺样 \'+c.underruns+\' · 画面偏差 \'+(s.video.sync_error_ms||0)+\' ms\';}')
                if mv_dir:
                    html=html.replace('<h2>音画同步 · 硬件音频时钟</h2>','<h2>'+html_escape.escape(media.get('title','MV'))+' · 音画同步</h2>')
                    html=html.replace('当前为 Closer 音乐 + 动态测试画面，验证同步链路；取得 MV 后换成同源音轨和画面。','当前音轨和画面提取自同一个 MV、同一段 30 秒。')
                    html=html.replace('已内置 30 秒动态测试视频','已内置 30 秒 MV 片段')
                    html=html.replace('Closer · 00:30—01:00 片段','MV 同源音轨 · 30 秒片段')
                    html=html.replace('已内置 Closer 第 30～60 秒，共 30 秒','已内置与 MV 同一时间区间的音轨，共 30 秒')
        if video_fpga:
            html=html.replace('开发板逐帧解码并在 ARM 上滤波。','开发板逐帧解码，平滑滤波可切换 ARM / FPGA。')
            html=html.replace('视频滤波由 ARM 计算；','视频平滑支持 ARM / FPGA，其他效果由 ARM 计算；')
        if video_effects:
            html=html.replace('视频开发版 0.4 · ARM 视频 / ARM/FPGA 音频','ARM / FPGA · 音视频滤波')
            html=html.replace('待完成：FPGA 图像滤波、真实视频与音频同步、完整分轮性能对比。','已接入：FPGA 图片与视频平滑、边缘提取、锐化；同源 MV 同步与三种效果分轮对比。')
            html=html.replace('支持上传视频逐帧处理并同步送到网页与外接屏；音画同步尚未接入。','图片可选 ARM / FPGA 处理，并同步送到网页与外接屏；视频支持同源音画同步。')
            html=html.replace('左右音箱播放相同声音，与图片独立。','左右音箱播放相同声音；顶部同步播放使用同源 MV 音轨。')
            html=html.replace('</script></body>',(APP/'comparison_client.js').read_text(encoding='utf-8')+'</script></body>')
            html=html.replace('showVideoFpga(s);','showVideoFpga(s);showComparisons(s);')
            html=html.replace("'ARM / '+effects[i.mode]","(i.backend||'ARM')+' / '+effects[i.mode]")
            html=html.replace('ARM 实时计算的图片滤波结果','开发板 ARM / FPGA 图片滤波结果')
            html=html.replace('记录仅包含图像滤波计算。','FPGA 计时包含分块传输。')
            html=html.replace('未包含解码、传输、显示或音频耗时。','FPGA 对比含分块传输；不含解码、显示或音频。')
            html=html.replace('图片仍为 ARM 运算。','图片与视频滤波均可选 ARM / FPGA。')
            html=html.replace('待完成：FPGA 视频滤波、音画同步和完整分轮性能对比。','已接入：三种 FPGA 图片/视频滤波、同源 MV 同步、HDMI 输出与三种效果分轮对比。')
            html=html.replace('单块耗时包含分块处理，不能直接作为严格加速比或端到端延迟。','滤波对比包含 FPGA 数据搬运，不代表端到端音画延迟或整体加速。')
            html=html.replace('FPGA 平滑滤波','FPGA 视频滤波')
            html=html.replace('测量视频滤波</button>','测量视频平滑</button>')
            html=html.replace('选择 FPGA 会切换为平滑；其他效果使用 ARM。','平滑、边缘提取、锐化均支持 ARM / FPGA，可保持效果切换后端。')
            html=html.replace('平滑滤波可切换 ARM / FPGA。','平滑、边缘提取和锐化均可切换 ARM / FPGA。')
            html=html.replace('视频平滑支持 ARM / FPGA，其他效果由 ARM 计算；','视频平滑、边缘提取、锐化均支持 ARM / FPGA；')
        files['web/index.html']=html.encode('utf-8')
else:
    files.pop('integrated_app.py',None)
for name in ('fir_driver.py','check_hardware.py','reference.c'): files[name]=(SRC/'board'/name).read_bytes()
for name in ('audio_live.bit','audio_live.hwh'): files[name]=(build/name).read_bytes()
files['coefficients.json']=(SRC/'reports'/'coefficients.json').read_bytes()
files['LICENSE_PYNQ.txt']=(SRC/'vendor'/'LICENSE_PYNQ.txt').read_bytes()
if video_effects and mv_dir is None:
    clip=bytes(48000*2)
elif mv_dir:
    clip=(mv_dir/'audio.s16le').read_bytes()
    assert len(clip)==30*48000*2
    assert hashlib.sha256(clip).hexdigest()==media['audio_sha256']
else:
    raise ValueError('No audio source was selected.')
files['closer_clip.s16le']=clip
files['clip.json']=json.dumps(dict(start_seconds=0 if video_effects and mv_dir is None else media['start_seconds'],duration_seconds=1 if video_effects and mv_dir is None else 30,sample_rate=48000,channels=1,sha256=hashlib.sha256(clip).hexdigest())).encode()
dist=REPO/'dist'
dist.mkdir(parents=True,exist_ok=True)
with wave.open(str(dist/('Field_audio_placeholder.wav' if video_effects and mv_dir is None else 'MV_30s.wav' if mv_dir else 'Closer_30s.wav')),'wb') as f:
    f.setnchannels(1); f.setsampwidth(2); f.setframerate(48000); f.writeframes(clip)
for name,data in files.items():
    if name.endswith('.py'): compile(data,name,'exec')
files['manifest.json']=json.dumps({name:hashlib.sha256(data).hexdigest() for name,data in files.items()}).encode()
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in files.items(): z.writestr(name,data)
payload=buffer.getvalue(); digest=hashlib.sha256(payload).hexdigest()
template=(SRC/'scripts'/'fpga_launcher.template').read_text(encoding='utf-8')
template=template.replace("'fir_check_'","'shenghua_live_'").replace("'run_fpga_check.py'","'run_live_audio.py'")
template=template.replace("shenghua_fpga_check.lock","shenghua_live.lock")
template=template.replace("run_fpga_check.py'),run_name='__main__'","run_live_audio.py'),run_name='__main__'")
template=template.replace('开始 ARM / FPGA 四种模式数值对照；本次不播放声音。','正在启动音视频监控服务。')
template=template.replace('测试期间暂时关闭作品页面服务，结束后会重新启动。','正在停止旧作品服务，准备启动当前版本。')
if video_effects:
    template=template.replace('启动 30 秒歌曲片段的 ARM / FPGA 实时播放页面。','启动现场视频音画分析与 ARM / FPGA 实时监控方案页面。')
launcher=template.replace('__PAYLOAD__',repr(base64.b64encode(payload).decode())).replace('__DIGEST__',repr(digest))
compile(launcher,'start_live_audio.py','exec')
target=dist/('start_shenghua_video_effects_avsync.py' if video_effects else 'start_shenghua_video_fpga_avsync.py' if video_fpga else 'start_shenghua_mv_avsync.py' if mv_dir else 'start_shenghua_avsync.py' if avsync else 'start_shenghua_video.py' if video else 'start_shenghua_hdmi.py' if hdmi else 'start_shenghua_integrated.py' if integrated else 'start_live_audio.py')
target.write_text(launcher,encoding='utf-8')
print('Ready:',target,'bytes:',len(launcher))
