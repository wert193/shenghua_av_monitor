// Extend the existing controls without replacing the page layout.
let comparisonPending=false;
const videoCompareButtons=[];
async function compareVideo(mode){
 comparisonPending=true;videoCompareButtons.forEach(b=>b.disabled=true);
 notice('正在测量'+effects[mode]+'，请稍候…');
 try{await act('/api/benchmark/video',{mode})}finally{comparisonPending=false;await poll()}
}
for(const mode of ['smooth','edge','sharpen']){
 const button=mode==='smooth'?$('videoBenchmark'):document.createElement('button');
 button.textContent='对比'+effects[mode];button.onclick=()=>compareVideo(mode);
 if(mode!=='smooth')$('videoBackends').appendChild(button);
 videoCompareButtons.push(button);
}
const comparisonTable=document.createElement('div');
comparisonTable.innerHTML='<p class="sub">同一张 320×180 测试图；双方预热 3 次、各测量 20 次，逐次核对结果。单位 ms，FPGA 含传输；不含解码、合成、显示或音频。</p><table><thead><tr><th>效果</th><th>ARM 平均 / P95</th><th>FPGA 平均 / P95</th><th>耗时比</th><th>误差</th></tr></thead><tbody id="videoCompareRows"></tbody></table><a class="link" href="/api/export" download>导出三种滤波记录</a>';
comparisonTable.querySelector('p').textContent+=' 与下方图片测试共用同一套 ARM 算法；不同尺寸的结果不要直接比较。';
$('videoMeasurement').after(comparisonTable);
const roundMode=document.createElement('select');roundMode.id='roundMode';roundMode.setAttribute('aria-label','分轮测试视频效果');
roundMode.style.cssText='font:inherit;padding:9px 12px;border:1px solid #dce4e9;border-radius:8px;background:white;color:#182634';
for(const mode of ['smooth','edge','sharpen']){const option=document.createElement('option');option.value=mode;option.textContent=effects[mode];roundMode.appendChild(option)}
$('roundStart').before(roundMode);$('roundStart').onclick=()=>act('/api/benchmark/rounds/start',{mode:roundMode.value});
$('roundPanel').querySelector('p').textContent='固定同源 MV 和所选视频效果，音频为 800 Hz 低通。先 ARM、后 FPGA，各播放 30 秒；先核对结果并预热，测试中锁定参数。';
const imageBackends=document.createElement('div');imageBackends.className='row';imageBackends.id='imageBackends';imageBackends.style.marginTop='12px';
for(const backend of ['ARM','FPGA']){const b=document.createElement('button');b.dataset.backend=backend;b.textContent=backend+' 图片处理';b.onclick=()=>act('/api/image/backend',{backend});imageBackends.appendChild(b)}
$('imageModes').after(imageBackends);
const imageCompare=$('bench').nextElementSibling;imageCompare.id='imageCompare';imageCompare.textContent='对比 ARM / FPGA 图片';imageCompare.title='固定当前图片与效果，含 FPGA 分块传输';imageCompare.onclick=()=>act('/api/benchmark/image');
const matchedCompare=document.createElement('button');matchedCompare.id='imageMatched';matchedCompare.textContent='与上表同图同尺寸测量';matchedCompare.onclick=()=>act('/api/benchmark/image',{same_input:true});imageCompare.after(matchedCompare);
$('mean').nextElementSibling.id='imageFpgaMean';$('p95').nextElementSibling.id='imageFpgaP95';
const imageResult=document.createElement('p');imageResult.className='sub';imageResult.id='imageCompareInfo';$('benchInfo').after(imageResult);
$('bench').closest('.card').querySelector('p').textContent='固定当前完整图片与效果，预热 3 次、测量 30 次。双后端对比逐次核对结果；FPGA 含分块、传输与拼接，不含解码、显示和音频。';
$('bench').closest('.card').querySelector('p').textContent+=' 两处共用 ARM 实现；“同图同尺寸”使用上表的 320×180 测试图，预热 3 次、测量 20 次，不更换已上传图片。';
function showComparisons(s){
 const running=s.round_benchmark.status==='running';
 const busy=comparisonPending||running||s.video.status==='playing'||['starting','running','stopping','measuring'].includes(s.audio.status)||s.benchmark.status==='running'||s.audio_measurement.status==='running';
 videoCompareButtons.forEach(b=>b.disabled=busy);
 roundMode.disabled=busy;$('roundStart').disabled=busy;
 $('imageCompare').disabled=busy||!s.image_fpga_available;
 $('imageMatched').disabled=busy||!s.image_fpga_available;
 document.querySelectorAll('#imageBackends button').forEach(b=>{b.disabled=busy||(b.dataset.backend==='FPGA'&&!s.image_fpga_available);b.classList.toggle('active',b.dataset.backend===s.image.backend)});
 const m=s.image.metrics,f=m&&m.fpga_result;
 $('imageFpgaMean').textContent=f?f.mean_ms.toFixed(3)+' ms':'待测量';$('imageFpgaP95').textContent=f?f.p95_ms.toFixed(3)+' ms':'待测量';
 $('imageCompareInfo').textContent=f?effects[m.mode]+' · ARM/FPGA 耗时比 '+m.speedup.toFixed(2)+'× · 最大像素误差 '+m.max_error+' · '+m.shape[1]+'×'+m.shape[0]+' · '+(m.same_input?'与上表相同测试图':'当前完整图片')+' · 统一 ARM 实现 · 原始记录已保存':'选择图片效果后，可对比同尺寸 ARM / FPGA 结果。旧版图片的 ARM 参考实现较慢，请以本版重新测量为准。';
 const body=$('videoCompareRows');body.replaceChildren();
 for(const mode of ['smooth','edge','sharpen']){
  const row=(s.video_measurements||{})[mode],tr=document.createElement('tr');
  const values=row?[effects[mode],row.ARM.mean_ms.toFixed(3)+' / '+row.ARM.p95_ms.toFixed(3),row.FPGA.mean_ms.toFixed(3)+' / '+row.FPGA.p95_ms.toFixed(3),row.speedup.toFixed(2)+'×',row.max_error]:[effects[mode],'待测量','待测量','—','—'];
  for(const v of values){const td=document.createElement('td');td.textContent=v;tr.appendChild(td)}body.appendChild(tr);
 }
 if(s.round_benchmark.result)$('roundProgress').textContent=(s.round_benchmark.error||s.round_benchmark.progress)+' · '+effects[s.round_benchmark.result.parameters.video_mode];
}
