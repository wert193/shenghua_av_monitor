let videoVersion=-1,videoCompareBusy=false,latestVideoResult=null,latestVideoAnalysis=null;
let latestImageAnalysis=null,embeddedAudioBlob=null,embeddedAudioAnalysis=null;
const videoEffects={smooth:'平滑',edge:'边缘提取',sharpen:'锐化'};
const audioEffects=['低通','高通','带通'];

document.querySelectorAll('#videoBackends button[data-backend]').forEach(button=>{
  button.onclick=()=>act('/api/video/backend',{backend:button.dataset.backend});
});
document.querySelectorAll('#videoModes button[data-mode]').forEach(button=>{
  button.onclick=()=>{act('/api/video/mode',{mode:button.dataset.mode});renderRecommendations()};
});

function postFile(url,file,headerName,headerValue){
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/octet-stream',[headerName]:headerValue},body:file});
}
async function analyzeImage(file){
  const response=await postFile('/api/analysis/upload',file,'X-Analysis-Name',encodeURIComponent(file.name));
  const result=await response.json();if(!response.ok)throw Error(result.error||'图片分析失败');
  latestImageAnalysis=result;renderFileAnalysis();renderRecommendations();
}
// Keep the existing image preview/HDMI upload path, then measure that exact file.
$('file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>10*1024*1024){notice('图片不能超过 10 MB');event.target.value='';return;}
  latestImageAnalysis=null;document.querySelectorAll('#solutionCard select').forEach(select=>delete select.dataset.manual);renderFileAnalysis();renderRecommendations();
  try{
    notice('正在上传图片并测量三种处理效果…');
    const upload=await postFile('/api/image/upload',file,'X-File-Name',encodeURIComponent(file.name));
    const payload=await upload.json();if(!upload.ok)throw Error(payload.error||'图片上传失败');
    await analyzeImage(file);notice('图片效果和 ARM / FPGA 数据已更新；可切换上方效果查看画面。');
  }catch(error){notice(error.message)}finally{event.target.value=''}
};

$('videoFile').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>100*1024*1024){notice('视频不能超过 100 MB');event.target.value='';return;}
  latestVideoResult=null;latestVideoAnalysis=null;embeddedAudioAnalysis=null;embeddedAudioBlob=null;document.querySelectorAll('#solutionCard select').forEach(select=>delete select.dataset.manual);renderFileAnalysis();renderRecommendations();
  $('embeddedAudioPanel').hidden=true;$('videoAudioName').textContent='正在上传视频…';
  $('playEmbeddedAudio').disabled=true;$('syncVideoAudio').disabled=true;
  $('videoMeasurement').textContent='视频已上传后，选择效果并点击“测量视频 ARM / FPGA”。';
  try{
    notice('正在上传视频…');
    const suffix=(file.name.match(/\.[a-zA-Z0-9]+$/)||['.mp4'])[0];
    const response=await fetch('/api/video/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Video-Name':'input'+suffix},body:file});
    const result=await response.json();if(!response.ok)throw Error(result.error||'视频上传失败');
    await poll();
    notice('视频已上传，正在分析三种视频效果…');
    const analysis=await postFile('/api/analysis/upload',file,'X-Analysis-Name',encodeURIComponent(file.name));
    latestVideoAnalysis=await analysis.json();if(!analysis.ok)throw Error(latestVideoAnalysis.error||'视频画面分析失败');
    renderFileAnalysis();renderRecommendations();
    await extractEmbeddedAudio(file);
    notice('视频画面与内嵌音轨已载入；现在可手动切换效果，或运行视频 ARM / FPGA 测量。');
  }catch(error){$('videoAudioName').textContent='音轨未载入';notice(error.message)}finally{event.target.value=''}
};

function makeWav(samples){
  const buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
  const write=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i))};
  write(0,'RIFF');view.setUint32(4,buffer.byteLength-8,true);write(8,'WAVE');write(12,'fmt ');
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
  view.setUint32(24,48000,true);view.setUint32(28,96000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
  write(36,'data');view.setUint32(40,samples.length*2,true);
  for(let i=0;i<samples.length;i++)view.setInt16(44+i*2,Math.max(-32768,Math.min(32767,Math.round(samples[i]*32767))),true);
  return new Blob([buffer],{type:'audio/wav'});
}
async function extractEmbeddedAudio(file){
  const AudioContextClass=window.AudioContext||window.webkitAudioContext;
  if(!AudioContextClass)throw Error('此浏览器不支持视频音轨解码。');
  $('videoAudioName').textContent='正在从视频解码声音…';
  const decoder=new AudioContextClass();let decoded;
  try{decoded=await decoder.decodeAudioData(await file.arrayBuffer())}catch(_){throw Error('无法解码视频内嵌音轨。请使用包含 AAC 音轨的 MP4。')}finally{await decoder.close()}
  if(!decoded.numberOfChannels||decoded.duration<.05)throw Error('视频内没有可用音轨。');
  if(decoded.duration>180)throw Error('视频音轨超过 3 分钟；请先剪短视频后再上传。');
  const length=Math.ceil(decoded.duration*48000),offline=new OfflineAudioContext(1,length,48000),source=offline.createBufferSource();
  source.buffer=decoded;source.connect(offline.destination);source.start();
  const rendered=await offline.startRendering();
  embeddedAudioBlob=makeWav(rendered.getChannelData(0));
  if(embeddedAudioBlob.size>20*1024*1024)throw Error('解码后音轨超过 20 MB。');
  $('embeddedAudioPanel').hidden=false;$('embeddedAudioStatus').textContent='音轨解码完成，正在提交板端…';
  const sourceResponse=await postFile('/api/audio/source',embeddedAudioBlob,'X-Audio-Name','video_audio.wav');
  const sourceResult=await sourceResponse.json();if(!sourceResponse.ok)throw Error(sourceResult.error||'板端音轨载入失败');
  $('playEmbeddedAudio').disabled=false;$('syncVideoAudio').disabled=false;
  $('videoAudioName').textContent=file.name+' · 已解码内嵌音轨 '+sourceResult.duration_seconds+' 秒';
  $('embeddedAudioStatus').textContent='同源音轨已载入板端耳机口；正在计算 ARM / FPGA 三种滤波模式…';
  await analyzeEmbeddedAudio();
}
async function analyzeEmbeddedAudio(){
  if(!embeddedAudioBlob)throw Error('请先上传含音轨的视频。');
  const response=await postFile('/api/analysis/upload',embeddedAudioBlob,'X-Analysis-Name','video_audio.wav');
  const result=await response.json();if(!response.ok)throw Error(result.error||'音频波形分析失败');
  embeddedAudioAnalysis=result;drawEmbeddedWave();renderAudioRows();renderRecommendations();
  $('embeddedAudioStatus').textContent='音轨分析完成 · '+result.duration_seconds+' 秒用于测量 · 48 kHz · 板载音频可试听。';
}
$('audioMeasureButton').onclick=async()=>{try{$('audioMeasureButton').disabled=true;$('embeddedAudioStatus').textContent='正在重新测量音频…';await analyzeEmbeddedAudio()}catch(error){notice(error.message)}finally{$('audioMeasureButton').disabled=false}};
$('playEmbeddedAudio').onclick=()=>act('/api/audio/start');
$('syncVideoAudio').onclick=()=>act('/api/av/start');
$('restoreDefaultAudio').onclick=async()=>{try{const response=await fetch('/api/audio/source/default',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),result=await response.json();if(!response.ok)throw Error(result.error||'恢复失败');$('playEmbeddedAudio').disabled=true;$('syncVideoAudio').disabled=true;$('embeddedAudioStatus').textContent='已恢复 Closer 示例音轨；同步播放按钮仅对已载入的同源视频音频开放。';await poll()}catch(error){notice(error.message)}};
$('audioAnalysisMode').onchange=drawEmbeddedWave;

function drawEmbeddedWave(){
  if(!embeddedAudioAnalysis)return;
  const canvas=$('embeddedAudioWave'),context=canvas.getContext('2d'),rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  canvas.width=Math.max(1,Math.round(rect.width*dpr));canvas.height=Math.round(220*dpr);context.setTransform(dpr,0,0,dpr,0,0);
  const width=rect.width,height=220,mode=$('audioAnalysisMode').value,signals=embeddedAudioAnalysis.waveforms[mode];
  context.clearRect(0,0,width,height);context.font='12px Segoe UI, Microsoft YaHei';
  const all=[signals.original,signals.ARM,signals.FPGA].filter(values=>values?.length).flatMap(values=>values.map(Math.abs)).sort((a,b)=>a-b);
  const peak=Math.max(1,all[Math.floor(all.length*.995)]||32767),scale=Math.min(32768,peak*1.12),mid=height/2;
  context.strokeStyle='#e1e8f0';context.lineWidth=1;
  for(let i=0;i<5;i++){const y=20+i*(height-40)/4;context.beginPath();context.moveTo(46,y);context.lineTo(width-10,y);context.stroke()}
  context.fillStyle='#718096';context.fillText('+'+Math.round(scale),4,26);context.fillText('0',22,mid+4);context.fillText('−'+Math.round(scale),4,height-15);
  const colors=['#718096','#2463df','#087f65'],names=['原声','ARM','FPGA'];
  [signals.original,signals.ARM,signals.FPGA].forEach((values,index)=>{if(!values?.length)return;context.strokeStyle=colors[index];context.lineWidth=index===0?1:1.5;context.beginPath();values.forEach((value,i)=>{const x=48+i*(width-60)/Math.max(1,values.length-1),y=mid-Math.max(-1,Math.min(1,value/scale))*(height/2-22);i?context.lineTo(x,y):context.moveTo(x,y)});context.stroke()});
  names.forEach((name,index)=>{context.fillStyle=colors[index];context.fillText(name,54+index*74,15)});
  const row=embeddedAudioAnalysis.rows.find(item=>Number(item.mode)===Number(mode));
  $('embeddedAudioMetrics').textContent=row?`${audioEffects[Number(mode)]} · ARM ${row.ARM.mean_ms.toFixed(3)} ms / FPGA ${row.FPGA?row.FPGA.mean_ms.toFixed(3)+' ms':'不可用'} · 输出最大误差 ${row.max_error} · 波形纵轴按本段信号自动放大。`:'选择滤波模式查看分析数据。';
}
function renderAudioRows(){
  const box=$('embeddedAudioChart');box.replaceChildren();if(!embeddedAudioAnalysis)return;
  for(const row of embeddedAudioAnalysis.rows.filter(item=>Number(item.mode)<3)){
    const line=document.createElement('div');line.className='metric-line';
    const best=row.FPGA&&row.max_error===0&&row.FPGA.mean_ms<row.ARM.mean_ms?'FPGA':'ARM';
    line.textContent=`${row.label} · 建议 ${best} · ARM ${row.ARM.mean_ms.toFixed(3)} / ${row.ARM.p95_ms.toFixed(3)} ms`+
      (row.FPGA?` · FPGA ${row.FPGA.mean_ms.toFixed(3)} / ${row.FPGA.p95_ms.toFixed(3)} ms · 最大误差 ${row.max_error}`:' · FPGA 不可用');
    box.append(line);
  }
}

function recommendationBackend(row){
  return row&&row.FPGA&&row.max_error===0&&String(row.recommendation||'').startsWith('推荐 FPGA')?'FPGA':'ARM';
}
function videoRecommendationBackend(result){
  if(result.max_error!==0)return 'ARM';
  const target=window.latestStatus?.video?.source_fps||0,armCapacity=1000/result.ARM.p95_ms,fpgaCapacity=1000/result.FPGA.p95_ms;
  if(target>0){
    const armMeets=armCapacity>=target,fpgaMeets=fpgaCapacity>=target;
    if(armMeets!==fpgaMeets)return fpgaMeets?'FPGA':'ARM';
    if(armMeets&&fpgaMeets)return result.FPGA.p95_ms<=result.ARM.p95_ms*.85?'FPGA':'ARM';
  }
  return result.FPGA.p95_ms<result.ARM.p95_ms?'FPGA':'ARM';
}
const solutionIds={smooth:'solVBSmooth',edge:'solVBEdge',sharpen:'solVBSharpen','0':'solAB0','1':'solAB1','2':'solAB2'};
function preferred(row){return row?recommendationBackend(row):'ARM'}
function setSuggestion(key,value){const el=$(solutionIds[key]);if(el&&!el.dataset.manual)el.value=value}
function renderFileAnalysis(){
  const box=$('fileAnalysisMetrics');if(!box)return;box.replaceChildren();
  for(const [label,result] of [['图片',latestImageAnalysis],['视频',latestVideoAnalysis]]){
    if(!result)continue;
    const features=result.features||{};
    const summary=document.createElement('div');summary.className='metric-line';
    summary.textContent=`${label}：${result.name} · ${result.width}×${result.height}`+(result.kind==='video'?` · ${result.fps} FPS · ${result.duration_seconds} 秒 · 抽样 ${result.sample_count} 帧`:'')+` · 亮度 ${features.brightness_mean??'—'} · 对比度 ${features.contrast_std??'—'} · 清晰度 ${features.sharpness_laplacian_var??'—'} · 边缘占比 ${features.edge_density_percent??'—'}%`;
    box.append(summary);
    for(const row of result.rows||[]){
      const line=document.createElement('div');line.className='metric-line';
      line.textContent=`${label} / ${videoEffects[row.mode]||row.label||row.mode} · ${row.recommendation} ARM ${row.ARM.mean_ms.toFixed(3)} / ${row.ARM.p95_ms.toFixed(3)} ms · FPGA ${row.FPGA?row.FPGA.mean_ms.toFixed(3)+' / '+row.FPGA.p95_ms.toFixed(3)+' ms':'不可用'} · 最大误差 ${row.max_error}`;
      box.append(line);
    }
  }
}
function renderRecommendations(){
  const rows=$('solutionRows');if(!rows)return;rows.replaceChildren();
  for(const [source,result] of [['上传图片',latestImageAnalysis],['上传视频抽帧',latestVideoAnalysis]])if(result){
    for(const row of result.rows||[])appendSolution(source,videoEffects[row.mode]||row.label||row.mode,recommendationBackend(row),`${row.recommendation} ARM ${row.ARM.mean_ms.toFixed(3)} / ${row.ARM.p95_ms.toFixed(3)} ms · FPGA ${row.FPGA?row.FPGA.mean_ms.toFixed(3)+' / '+row.FPGA.p95_ms.toFixed(3)+' ms':'不可用'} · 最大误差 ${row.max_error}`);
  }
  if(latestVideoResult){const backend=videoRecommendationBackend(latestVideoResult);appendSolution('视频抽样对照',videoEffects[latestVideoResult.mode]||latestVideoResult.mode,backend,`抽样 ${latestVideoResult.sampled_frames} 帧 · ARM ${latestVideoResult.ARM.mean_ms.toFixed(3)} / ${latestVideoResult.ARM.p95_ms.toFixed(3)} ms · FPGA ${latestVideoResult.FPGA.mean_ms.toFixed(3)} / ${latestVideoResult.FPGA.p95_ms.toFixed(3)} ms · 最大误差 ${latestVideoResult.max_error}`)}
  if(embeddedAudioAnalysis)for(const row of embeddedAudioAnalysis.rows.filter(item=>Number(item.mode)<3))appendSolution('视频内嵌音频',row.label,recommendationBackend(row),`ARM ${row.ARM.mean_ms.toFixed(3)} / ${row.ARM.p95_ms.toFixed(3)} ms · FPGA ${row.FPGA?row.FPGA.mean_ms.toFixed(3)+' / '+row.FPGA.p95_ms.toFixed(3)+' ms':'不可用'} · 最大误差 ${row.max_error}`);
  if(!latestImageAnalysis&&!latestVideoAnalysis&&!embeddedAudioAnalysis){
    const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='上传图片或视频并完成测量后，这里显示针对本段素材的方案。';tr.append(td);rows.append(tr);$('solutionCard').hidden=true;return;
  }
  $('solutionCard').hidden=false;
  const ready=Boolean(latestImageAnalysis&&latestVideoAnalysis&&embeddedAudioAnalysis);
  $('confirmSolution').disabled=!ready;
  for(const mode of ['smooth','edge','sharpen']){const image=latestImageAnalysis?.rows?.find(row=>row.mode===mode),video=latestVideoAnalysis?.rows?.find(row=>row.mode===mode),vrow=video||image;setSuggestion(mode,preferred(vrow))}
  for(const mode of ['0','1','2']){const row=embeddedAudioAnalysis?.rows?.find(item=>String(item.mode)===mode);setSuggestion(mode,preferred(row))}
  $('solutionNote').textContent=ready?'已按本次素材逐项生成六种效果的默认建议。图片/视频/音频依据均列在上表；你可以分别调整六个通道，确认后进入监控。':'请上传一张图片和一段含音轨的视频；系统自动显示图像特征、视频抽帧的三种滤波数据和音频波形数据。完成后即可确认。视频逐帧对比按钮是额外测量，不影响进入监控。';
}
function appendSolution(source,effect,backend,basis){
  const tr=document.createElement('tr');for(const value of [source,effect,backend,basis]){const td=document.createElement('td');td.textContent=value;tr.append(td)}$('solutionRows').append(tr);
}
document.querySelectorAll('#solutionCard select').forEach(select=>select.onchange=()=>{select.dataset.manual='1'});

function renderUploadedVideoComparison(result){
  latestVideoResult=result;
  const mode=videoEffects[result.mode]||result.mode,arm=result.ARM,fpga=result.FPGA;
  $('videoMeasurement').textContent=`${mode} · 抽样 ${result.sampled_frames}/${result.source_frames} 帧 · 最大像素误差 ${result.max_error} · ARM / FPGA 平均耗时比 ${result.speedup.toFixed(2)}×`;
  const box=$('uploadedVideoChart');box.replaceChildren();
  for(const [name,value,color] of [['ARM',arm,'#2463df'],['FPGA',fpga,'#159a7b']]){
    const line=document.createElement('div');line.className='metric-line';line.style.borderLeftColor=color;
    line.textContent=`${name} · 平均 ${value.mean_ms.toFixed(3)} ms · P95 ${value.p95_ms.toFixed(3)} ms · 滤波能力 ${value.filter_fps.toFixed(1)} FPS`;box.append(line);
  }
  renderRecommendations();
}
function showVideo(video){
  if(!video)return;
  $('videoInfo').textContent=(video.error||video.source||'请先上传视频')+' · '+video.status+' · '+video.backend+' · 第 '+video.frame+' 帧 · '+video.fps+' FPS · 丢帧 '+video.dropped+' · 滤波 '+video.filter_ms+' ms · HDMI '+video.display_ms+' ms';
  document.querySelectorAll('#videoModes button[data-mode]').forEach(button=>button.classList.toggle('active',button.dataset.mode===video.mode));
  document.querySelectorAll('#videoBackends button[data-backend]').forEach(button=>button.classList.toggle('active',button.dataset.backend===(video.requested_backend||'ARM')));
  $('uploadedVideoCompare').disabled=videoCompareBusy||!video.source||video.status==='playing';
  if(video.version!==videoVersion&&video.frame>0){videoVersion=video.version;$('videoFrame').style.display='block';$('videoFrame').src='/video/live.jpg?v='+video.version}
}
function showVideoFpga(state){
  const available=Boolean(state.video_fpga_available);
  document.querySelector('#videoBackends button[data-backend="FPGA"]').disabled=!available;
  $('videoFpgaControls').textContent=available?'FPGA 视频处理可用。':'当前硬件未加载视频滤波 FPGA 核；FPGA 选项不可用。';
  $('uploadedVideoCompare').disabled=videoCompareBusy||!available||!state.video.source||state.video.status==='playing';
  const videoRows=latestVideoAnalysis?.rows||[],audioRows=embeddedAudioAnalysis?.rows||[];
  for(const [id,mode,rows] of [['solVBSmooth','smooth',videoRows],['solVBEdge','edge',videoRows],['solVBSharpen','sharpen',videoRows],['solAB0','0',audioRows],['solAB1','1',audioRows],['solAB2','2',audioRows]]){
    const select=$(id);if(!select)continue;
    const row=rows.find(item=>String(item.mode)===String(mode));
    const fpga=select.querySelector('option[value="FPGA"]');
    fpga.disabled=mode==='0'||mode==='1'||mode==='2'?(!window.latestStatus?.audio_fpga_available||Boolean(row&&!row.FPGA)):(!available||!(state.video_fpga_modes||[]).includes(mode));
  }
}
$('uploadedVideoCompare').onclick=async()=>{
  const mode=document.querySelector('#videoModes button.active')?.dataset.mode||'smooth';
  if(mode==='original'){notice('原图模式无需滤波，请先选择平滑、边缘提取或锐化。');return;}
  videoCompareBusy=true;$('uploadedVideoCompare').disabled=true;notice('正在对上传视频抽帧并对比 ARM / FPGA，请稍候…');
  try{
    const response=await fetch('/api/benchmark/video-upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
    const result=await response.json();if(!response.ok)throw Error(result.error||'视频对比失败');
    renderUploadedVideoComparison(result);notice('视频测量完成。可以切换图像效果、播放视频查看 HDMI/网页画面，并在右侧切换音频滤波。');
  }catch(error){notice(error.message)}finally{videoCompareBusy=false;await poll()}
};
$('confirmSolution').onclick=()=>{
  const query=new URLSearchParams({vm:'smooth',am:'0',vb_smooth:$('solVBSmooth').value,vb_edge:$('solVBEdge').value,vb_sharpen:$('solVBSharpen').value,ab_0:$('solAB0').value,ab_1:$('solAB1').value,ab_2:$('solAB2').value,source:'measured-media'});
  location.href='/monitor?'+query.toString();
};
window.addEventListener('resize',drawEmbeddedWave);
renderRecommendations();
