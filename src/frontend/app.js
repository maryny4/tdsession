const $ = s => document.querySelector(s);
let selectedPath = null, activeTabId = null, launching = false, showCtrlBar = true;
const tabs = new Map();

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
async function api(url, o) { return (await fetch(url, o)).json(); }
function stem(p) { return (p||'').split('/').pop()?.replace('.session','') || p; }
function vncUrl(id) {
  return '/vnc/'+id+'/?path=vnc/'+id+'/websockify&resize=remote&clipboard_up=true&clipboard_down=true&clipboard_seamless=true'+(showCtrlBar?'&show_control_bar=true':'');
}

function toggleSidebar() { $('#sidebar').classList.toggle('collapsed'); }
function toggleFullscreen() { document.body.classList.toggle('fullscreen'); }
document.addEventListener('keydown', e => { if (e.key==='Escape'&&document.body.classList.contains('fullscreen')) toggleFullscreen(); });
function toggleControlBar() {
  showCtrlBar = !showCtrlBar;
  $('#btn-ctrlbar').classList.toggle('active', showCtrlBar);
  tabs.forEach((tab, id) => { tab.iframe.src = vncUrl(id); });
}

async function init() {
  await refreshTree();
  await restoreTabs();
  await refreshStatus();
  setInterval(refreshStatus, 3000);
  const es = new EventSource('/api/sessions/watch');
  es.addEventListener('tree_update', () => refreshTree());
}

async function restoreTabs() {
  try {
    const s = await api('/api/status');
    for (const sess of (s.sessions||[])) {
      if (sess.status==='running'||sess.status==='starting') addTab(sess.session_id, sess.source_path);
    }
  } catch(e) { console.warn('restoreTabs', e); }
}

async function refreshTree() {
  try {
    const data = await api('/api/sessions');
    const el = $('#tree'), open = new Set();
    el.querySelectorAll('.ti.dir.open').forEach(d => open.add(d.dataset.path));
    el.innerHTML = '';
    buildTree(data.tree, el, 0, open);
    if (selectedPath) el.querySelectorAll('.ti.file').forEach(n => { if (n.dataset.path===selectedPath) n.classList.add('selected'); });
    markRunning();
  } catch(e) { console.warn(e); }
}

function buildTree(items, parent, depth, open) {
  for (const item of items) {
    if (item.type==='dir') {
      const d = document.createElement('div');
      d.className='ti dir'; d.dataset.path=item.path||item.name;
      d.style.paddingLeft=(10+depth*16)+'px';
      d.innerHTML='<span class="ti-icon ti-chev"><i class="icon-chevron-right" style="font-size:12px"></i></span><span class="ti-icon"><i class="icon-folder" style="font-size:14px;color:var(--accent)"></i></span><span class="ti-name">'+esc(item.name)+'</span>';
      const ch=document.createElement('div'); ch.className='tc';
      if (open.has(d.dataset.path)){d.classList.add('open');ch.classList.add('open')}
      buildTree(item.children||[],ch,depth+1,open);
      d.onclick=e=>{e.stopPropagation();d.classList.toggle('open');ch.classList.toggle('open')};
      parent.appendChild(d);parent.appendChild(ch);
    } else {
      const f=document.createElement('div');
      f.className='ti file';f.dataset.path=item.path;
      f.style.paddingLeft=(10+depth*16+24)+'px';
      f.innerHTML='<span class="ti-icon"><i class="icon-file" style="font-size:14px"></i></span><span class="ti-name">'+esc(item.name)+'</span>';
      f.onclick=e=>{e.stopPropagation();document.querySelectorAll('.ti.selected').forEach(x=>x.classList.remove('selected'));f.classList.add('selected');selectedPath=item.path;updateBtn()};
      parent.appendChild(f);
    }
  }
}

function markRunning() {
  document.querySelectorAll('.ti-badge').forEach(b=>b.remove());
  tabs.forEach(tab=>{
    const f=document.querySelector('.ti.file[data-path="'+CSS.escape(tab.source_path)+'"]');
    if(f){const b=document.createElement('span');b.className='ti-badge '+(tab.status||'starting');b.textContent=tab.status||'starting';f.appendChild(b)}
  });
}

function updateBtn() {
  const btn=$('#btn-launch'),txt=$('#btn-launch-text');
  if(!selectedPath){btn.disabled=true;txt.textContent='Launch';return}
  if(launching)return;
  let exists=false;tabs.forEach(t=>{if(t.source_path===selectedPath)exists=true});
  btn.disabled=false;txt.textContent=exists?'Switch':'Launch';
}

async function refreshStatus() {
  try {
    const s=await api('/api/status'),sessions=s.sessions||[];
    const chip=$('#chip'),running=sessions.filter(x=>x.status==='running'||x.status==='starting');
    if(running.length>0){chip.className='chip live';chip.textContent=running.length+' active';$('#btn-stop-all').disabled=false}
    else{chip.className='chip idle';chip.textContent='idle';$('#btn-stop-all').disabled=tabs.size===0}
    tabs.forEach((tab,id)=>{const ss=sessions.find(x=>x.session_id===id);if(ss)updDot(id,ss.status);else rmTab(id)});
    markRunning();updateBtn();
  }catch(e){console.warn(e)}
}

function addTab(id,path){
  if(tabs.has(id)){swTab(id);return}
  const iframe=document.createElement('iframe');
  iframe.className='vnc-frame hidden';iframe.allow='clipboard-read; clipboard-write';
  iframe.src=vncUrl(id);$('#vnc-wrap').appendChild(iframe);

  const t=document.createElement('div');t.className='tab';t.dataset.id=id;
  t.innerHTML='<span class="tab-dot starting"></span><span>'+esc(stem(path))+'</span><span class="tab-close" title="Stop"><i class="icon-x" style="font-size:12px"></i></span>';
  t.querySelector('.tab-close').onclick=e=>{e.stopPropagation();doStop(id)};
  t.onclick=()=>swTab(id);
  $('#tabs-bar').appendChild(t);$('#placeholder')?.remove();
  tabs.set(id,{source_path:path,iframe,tabEl:t,status:'starting'});swTab(id);
}

function swTab(id){
  if(!tabs.has(id))return;
  tabs.forEach(t=>{t.iframe.classList.add('hidden');t.tabEl.classList.remove('active')});
  const t=tabs.get(id);t.iframe.classList.remove('hidden');t.tabEl.classList.add('active');activeTabId=id;
}

function rmTab(id){
  if(!tabs.has(id))return;
  const t=tabs.get(id);t.iframe.remove();t.tabEl.remove();tabs.delete(id);
  if(activeTabId===id){activeTabId=null;if(tabs.size>0)swTab(tabs.keys().next().value);else showPH()}
  markRunning();updateBtn();
}

function showPH(){
  if(!$('#placeholder')){
    const p=document.createElement('div');p.className='placeholder';p.id='placeholder';
    p.innerHTML='<div class="ph-icon"><i class="icon-monitor"></i></div><p>Select a session and click Launch</p><span class="ph-hint">Sessions appear in the sidebar</span>';
    $('#vnc-wrap').appendChild(p);
  }
}

function updDot(id,status){
  if(!tabs.has(id))return;
  const t=tabs.get(id);t.status=status;
  const d=t.tabEl.querySelector('.tab-dot');if(d)d.className='tab-dot '+status;
}

async function doLaunch(){
  if(!selectedPath)return;
  let eid=null;tabs.forEach((t,i)=>{if(t.source_path===selectedPath)eid=i});
  if(eid){swTab(eid);return}
  launching=true;$('#btn-launch').disabled=true;$('#btn-launch-text').textContent='Launching...';
  try{
    const r=await api('/api/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:selectedPath})});
    if(r.session_id){addTab(r.session_id,r.source_path||selectedPath);refreshStatus()}
    else alert('Failed: '+(r.detail||JSON.stringify(r)));
  }catch(e){alert('Error: '+e.message)}
  finally{launching=false;updateBtn()}
}

async function doStop(id){
  try{await api('/api/stop/'+id,{method:'POST'})}catch(e){}
  rmTab(id);refreshStatus();
}

async function doStopAll(){
  $('#btn-stop-all').disabled=true;
  try{await api('/api/stop-all',{method:'POST'})}catch(e){}
  [...tabs.keys()].forEach(rmTab);refreshStatus();
}

init();
