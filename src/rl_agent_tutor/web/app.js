let state={plan:null,stats:null,test:null};

async function api(method,path,body){
  const opt={method,headers:{'Content-Type':'application/json'}};
  if(body) opt.body=JSON.stringify(body);
  const r=await fetch(path,opt);
  if(!r.ok){const t=await r.text();throw new Error(t)}
  return await r.json();
}
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1800)}
function escapeHtml(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function md2html(md){
  let h=escapeHtml(md);
  h=h.replace(/```(\w*)\n([\s\S]*?)```/g,(m,l,c)=>`<pre><code>${c}</code></pre>`);
  h=h.replace(/`([^`\n]+)`/g,'<code>$1</code>');
  h=h.replace(/^####\s+(.+)$/gm,'<h4>$1</h4>');
  h=h.replace(/^###\s+(.+)$/gm,'<h3>$1</h3>');
  h=h.replace(/^##\s+(.+)$/gm,'<h2>$1</h2>');
  h=h.replace(/^#\s+(.+)$/gm,'<h1>$1</h1>');
  h=h.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/\*([^*]+)\*/g,'<em>$1</em>');
  h=h.replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  h=h.replace(/^[-*]\s+(.+)$/gm,'<li>$1</li>');
  h=h.replace(/(<li>[\s\S]*?<\/li>(\n|$))+/g,m=>'<ul>'+m+'</ul>');
  h=h.replace(/\n{2,}/g,'</p><p>');h='<p>'+h+'</p>';
  h=h.replace(/<p>(<h\d|<ul|<pre)/g,'$1').replace(/(<\/h\d>|<\/ul>|<\/pre>)<\/p>/g,'$1');
  return h;
}
function setView(v){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.v===v));
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id==='v-'+v));
  if(v==='resources') loadResources();
  if(v==='kb') loadKbNode();
  if(v==='dashboard') loadStats();
  if(v==='library') loadIndexStats();
}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>setView(t.dataset.v));

async function refreshAll(){
  await refreshWorkspaces();
  const r=await api('GET','/api/plan');
  state.plan=r.plan;
  const ws=document.getElementById('wsSelect').value || '';
  document.getElementById('metaLine').textContent=(r.provider||'')+' · ws: '+ws+' · '+(r.plan?(r.plan.state||'idle'):'no plan');
  if(!r.plan){
    document.getElementById('noPlan').style.display='block';
    document.getElementById('hasPlan').style.display='none';
  }else{
    document.getElementById('noPlan').style.display='none';
    document.getElementById('hasPlan').style.display='block';
    renderPlan(r.plan);
    document.getElementById('nextAction').textContent=r.next_action||'';
    renderCurrent();
    renderQAHistory();
  }
}

async function refreshWorkspaces(){
  try{
    const r=await api('GET','/api/workspaces');
    const sel=document.getElementById('wsSelect');
    sel.innerHTML=r.items.map(w=>{
      const prog=w.progress[1]?` (${w.progress[0]}/${w.progress[1]})`:'';
      return `<option value="${w.name}" ${w.active?'selected':''}>${w.name}${prog}</option>`;
    }).join('');
  }catch(e){console.error('workspaces fetch',e)}
}

async function onWsChange(){
  const name=document.getElementById('wsSelect').value;
  try{
    await api('POST','/api/workspaces/switch',{name});
    toast('切换到 '+name);
    // clear transient UI bits so they don't bleed across workspaces
    const pc=document.getElementById('practiceCard');
    if(pc){pc.style.display='none';document.getElementById('practiceContent').innerHTML=''}
    const qh=document.getElementById('qaHistory');if(qh) qh.innerHTML='';
    const kb=document.getElementById('kbContent');if(kb) kb.innerHTML='';
    const rl=document.getElementById('resList');if(rl) rl.innerHTML='';
    const rv=document.getElementById('reviewContent');if(rv) rv.innerHTML='';
    state.test=null;
    await refreshAll();
  }catch(e){alert('切换失败: '+e.message)}
}

function openNewWs(){
  document.getElementById('newWsModal').style.display='flex';
  document.getElementById('newWsName').value='';
  setTimeout(()=>document.getElementById('newWsName').focus(),50);
}
function closeNewWs(){document.getElementById('newWsModal').style.display='none'}
async function confirmNewWs(){
  const name=document.getElementById('newWsName').value.trim().toLowerCase();
  if(!name){toast('请填写任务名');return}
  try{
    await api('POST','/api/workspaces',{name,switch:true});
    closeNewWs();
    toast('已创建 '+name);
    state.test=null;
    await refreshAll();
  }catch(e){alert('创建失败: '+e.message)}
}

function renderPlan(p){
  const root=document.getElementById('planTree');
  root.innerHTML=p.stages.map(s=>{
    const done=s.nodes.filter(n=>n.status==='completed').length;
    return `<div class="stage">
      <div class="stage-name">Stage ${s.id} · ${escapeHtml(s.name)}<span class="pct">${done}/${s.nodes.length}</span></div>
      ${s.nodes.map(n=>{
        const icon={completed:'✅',in_progress:'🔄',self_testing:'🧪',pending:'⬜'}[n.status]||'•';
        const cur=n.id===p.current_node_id?'cur':'';
        return `<div class="node ${cur}" onclick="goTo('${n.id}')"><span class="icon">${icon}</span><span class="id">${n.id}</span> ${escapeHtml(n.name)}</div>`;
      }).join('')}
    </div>`;
  }).join('');
}

function curNode(){
  if(!state.plan||!state.plan.current_node_id) return null;
  return state.plan.stages.flatMap(s=>s.nodes).find(n=>n.id===state.plan.current_node_id);
}

function renderCurrent(){
  const n=curNode();const el=document.getElementById('curBody');
  if(!n){el.innerHTML='<div class="empty">无当前节点</div>';return}
  document.getElementById('curHead').innerHTML=`<span class="dot-state ${state.plan.state||''}"></span>当前节点 · ${n.id} ${escapeHtml(n.name)}`;
  el.innerHTML=`
    <div style="font-size:12px;color:var(--mut)">${escapeHtml(n.description||'')}</div>
    ${n.objectives&&n.objectives.length?`<div style="margin-top:8px"><strong>目标:</strong><ul>${n.objectives.map(o=>'<li>'+escapeHtml(o)+'</li>').join('')}</ul></div>`:''}
    <div style="margin-top:6px;font-size:11px;color:var(--mut)">预估 ${n.estimated_hours[0]}–${n.estimated_hours[1]}h · 状态: ${n.status}</div>
  `;
}

async function goTo(nid){
  await api('POST','/api/goto',{node_id:nid});
  const pcard=document.getElementById('practiceCard');
  if(pcard){pcard.style.display='none';document.getElementById('practiceContent').innerHTML=''}
  const rcard=document.getElementById('inlineResCard');
  if(rcard){rcard.style.display='none';document.getElementById('inlineResList').innerHTML='';document.getElementById('inlineResCount').textContent=''}
  const rescard=document.getElementById('inlineResourcesCard');
  if(rescard){rescard.style.display='none';document.getElementById('inlineResourcesList').innerHTML='';document.getElementById('inlineResourcesCount').textContent=''}
  await refreshAll();
}

async function createPlan(){
  const goal=document.getElementById('goal').value.trim();
  if(!goal){toast('请填写学习目标');return}
  const level=document.getElementById('level').value.trim();
  toast('生成中,通常 20–40 秒...');
  try{await api('POST','/api/plan',{goal,level});await refreshAll();toast('计划已生成')}catch(e){alert('失败: '+e.message)}
}

async function doAsk(){
  const q=document.getElementById('qaInput').value.trim();if(!q)return;
  const btn=document.getElementById('askBtn');btn.disabled=true;btn.textContent='思考中...';
  pushMsg('user',q);document.getElementById('qaInput').value='';
  try{
    const r=await api('POST','/api/ask',{question:q});
    pushMsg('ai',r.answer);
    if(r.citations&&r.citations.length){pushCitations(r.citations)}
  }
  catch(e){pushMsg('ai','⚠️ 失败: '+e.message)}
  btn.disabled=false;btn.textContent='提问';
}
function pushCitations(cits){
  const box=document.getElementById('qaHistory');
  const div=document.createElement('div');
  div.style.cssText='margin:-4px 0 8px 0;padding:6px 10px;background:#f6f8fa;border-left:3px solid var(--pri);border-radius:4px;font-size:11px;color:var(--mut)';
  div.innerHTML='📚 引用来源:<br>'+cits.map(c=>`<span style="display:inline-block;margin:2px 4px 2px 0;padding:2px 6px;background:#fff;border:1px solid var(--bd);border-radius:3px;font-family:ui-monospace,monospace">[${escapeHtml(c.doc_id)} · §${escapeHtml(c.section)} · p.${c.page}]</span>`).join('');
  box.appendChild(div);box.scrollTop=box.scrollHeight;
}
function pushMsg(role,text){
  const box=document.getElementById('qaHistory');
  const div=document.createElement('div');div.className='qa-msg '+role;
  div.innerHTML=role==='ai'?md2html(text):escapeHtml(text);
  box.appendChild(div);box.scrollTop=box.scrollHeight;
}
async function renderQAHistory(){
  const n=curNode();if(!n)return;
  const r=await api('GET','/api/trajectory?node_id='+n.id+'&limit=20');
  const box=document.getElementById('qaHistory');box.innerHTML='';
  for(const e of r.entries){
    if(e.kind==='ask') pushMsg('user',e.content);
    else if(e.kind==='answer') pushMsg('ai',e.content);
  }
}
async function doFetch(){
  toast('抓取中,可能要 30–60 秒(arxiv + git clone + 博客)...');
  const btns=document.querySelectorAll('[onclick*="doFetch"]');
  btns.forEach(b=>{b.disabled=true});
  try{
    const r=await api('POST','/api/fetch');
    const items=r.resources||[];
    const byKind={};
    for(const x of items){byKind[x.kind]=(byKind[x.kind]||0)+1}
    const summary=Object.entries(byKind).map(([k,v])=>`${k}:${v}`).join(' · ')||'(空)';
    toast(`已抓 ${items.length} 项 (${summary})`);
    renderResourceList(items);                 // dedicated 资源 tab
    showInlineResources(items, summary);       // 学习页就近显示
  }catch(e){alert('抓取失败: '+e.message)}
  finally{btns.forEach(b=>{b.disabled=false})}
}

function showInlineResources(items, summary){
  const card=document.getElementById('inlineResourcesCard');
  const list=document.getElementById('inlineResourcesList');
  const cnt=document.getElementById('inlineResourcesCount');
  if(!card) return;
  cnt.textContent=items&&items.length?`(${items.length} 项 · ${summary||''})`:'';
  renderResourceListInto(list, items);
  card.style.display='block';
  card.scrollIntoView({behavior:'smooth',block:'nearest'});
}

async function doCourseware(){
  await loadCoursewareInline({force:false});
}

async function loadCoursewareInline({force=false}={}){
  const card=document.getElementById('inlineResCard');
  const body=document.getElementById('inlineResList');
  const cnt=document.getElementById('inlineResCount');
  if(!card) return;
  card.style.display='block';
  card.scrollIntoView({behavior:'smooth',block:'nearest'});
  cnt.textContent=force?'(重新综合中…)':'(综合中…)';
  body.innerHTML='<div class="empty"><span class="spinner"></span> AI 正在阅读资源并提炼课件,通常 20–40 秒...</div>';
  try{
    const url='/api/courseware'+(force?'?force=true':'');
    const r=await api('POST',url);
    if(!r.markdown||!r.markdown.trim()){
      body.innerHTML=`<div class="empty">课件生成为空。可能是该节点还没抓到任何可读资源。<br>建议先点"📚 抓资源",或在 workspace/library/papers/ 手动放 PDF 后再试。</div>`;
      cnt.textContent='';
      return;
    }
    body.innerHTML=md2html(r.markdown);
    const meta=[];
    if(typeof r.sources_used==='number'){meta.push(`${r.sources_used}/${r.sources_total||r.sources_used} 资源`)}
    if(r.cached){meta.push('缓存')}
    cnt.textContent=meta.length?`(${meta.join(' · ')})`:'';
  }catch(e){
    body.innerHTML='<div class="empty" style="color:var(--danger)">课件生成失败: '+escapeHtml(e.message)+'</div>';
    cnt.textContent='';
  }
}

async function regenCourseware(){
  await loadCoursewareInline({force:true});
}

function renderResourceListInto(list, items){
  if(!items||!items.length){
    list.innerHTML=`<div class="empty">
      没抓到任何资源。可能原因:<br>
      · LLM 没为这个节点想到匹配的论文/仓库(尝试节点描述更具体)<br>
      · 网络中断 / arxiv 临时不可用<br>
      · 见终端日志
    </div>`;
    return;
  }
  list.innerHTML=items.map(x=>{
    const failed=(x.summary||'').toLowerCase().includes('failed') || (x.title||'').startsWith('[search failed');
    return `<div class="res" style="${failed?'opacity:0.55':''}">
    <span class="kind">${x.kind}</span><span class="title">${escapeHtml(x.title)}</span>
    <div class="meta">${x.local_path?'📁 '+escapeHtml(x.local_path)+'<br>':''}${x.url?'🔗 <a href="'+x.url+'" target="_blank" rel="noopener">'+escapeHtml(x.url)+'</a>':''}</div>
    ${x.summary?'<div class="meta">'+escapeHtml(String(x.summary).slice(0,300))+'</div>':''}
  </div>`;
  }).join('');
}

function renderResourceList(items){
  renderResourceListInto(document.getElementById('resList'), items);
}

async function loadResources(){
  const n=curNode();if(!n)return;
  const r=await api('GET','/api/resources/'+n.id);
  renderResourceList(r.resources);
}
async function doPractices(){
  const card=document.getElementById('practiceCard');
  const body=document.getElementById('practiceContent');
  card.style.display='block';
  body.innerHTML='<div class="empty"><span class="spinner"></span> 生成中,通常 10–20 秒...</div>';
  try{
    const r=await api('POST','/api/practices');
    body.innerHTML=md2html(r.text);
    card.scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  catch(e){body.innerHTML='<div class="empty" style="color:var(--danger)">失败: '+escapeHtml(e.message)+'</div>'}
}
async function doArchive(){
  toast('归档中...');
  try{const r=await api('POST','/api/archive',{});toast(`已写 ${r.files.length} 个文件`);loadKbNode()}
  catch(e){alert('失败: '+e.message)}
}
async function doArchiveAll(){
  toast('全量归档中,可能要 1–2 分钟...');
  try{const r=await api('POST','/api/archive',{all_active:true});toast(`已写 ${r.files.length} 个文件`);loadKbIndex()}
  catch(e){alert('失败: '+e.message)}
}
async function doAdvance(){
  if(!confirm('标记当前节点完成并推进到下一个?'))return;
  try{const r=await api('POST','/api/advance');toast(r.next?'→ 下一节点 '+r.next:'🎉 全部完成');refreshAll()}
  catch(e){alert('失败: '+e.message)}
}
async function loadKbIndex(){
  const r=await api('GET','/api/kb');
  document.getElementById('kbContent').innerHTML=md2html(r.markdown);
}
async function loadKbNode(){
  const n=curNode();if(!n){loadKbIndex();return}
  const r=await api('GET','/api/kb/'+n.id);
  document.getElementById('kbContent').innerHTML=md2html(r.markdown);
}
async function startTest(){
  const n=curNode();if(!n)return;
  toast('出题中...');
  try{
    const r=await api('POST','/api/test/start',{node_id:n.id});
    state.test={node_id:n.id,questions:r.questions,attempts:[],idx:0};
    renderTest();
  }catch(e){alert('失败: '+e.message)}
}
function renderTest(){
  const t=state.test;const area=document.getElementById('testArea');
  if(!t){area.innerHTML='<div class="empty">点上方"出 5 题"开始</div>';return}
  if(t.idx>=t.questions.length){
    const avg=t.attempts.length?t.attempts.reduce((s,a)=>s+a.score,0)/t.attempts.length:0;
    area.innerHTML=`<div class="card"><h3>本场结果</h3>
      <div style="font-size:24px;font-weight:700">${avg.toFixed(2)}</div>
      <div class="sub">${t.attempts.length} 题 · 已自动归档到 exercises.jsonl</div>
      <div class="toolbar" style="margin-top:10px"><button class="btn primary" onclick="startTest()">再来一组</button></div>
    </div>`;
    api('POST','/api/test/submit',{node_id:t.node_id,questions:t.questions,attempts:t.attempts}).catch(()=>{});
    return;
  }
  const q=t.questions[t.idx];
  area.innerHTML=`<div class="test-q">
    <div class="qhead">Q${t.idx+1}/${t.questions.length} <span class="qtype">${q.type}</span></div>
    <div style="margin-bottom:8px">${escapeHtml(q.question)}</div>
    <textarea id="ansBox" rows="5" placeholder="作答..."></textarea>
    <div class="toolbar" style="margin-top:8px"><button class="btn primary" onclick="submitAns()">提交</button>
    <button class="btn" onclick="skipAns()">跳过</button></div>
    <div id="fb"></div>
  </div>`;
}
async function submitAns(){
  const t=state.test;const q=t.questions[t.idx];const ans=document.getElementById('ansBox').value;
  const fb=document.getElementById('fb');fb.innerHTML='<div class="feedback warn"><span class="spinner"></span> 评分中...</div>';
  try{
    const r=await api('POST','/api/test/grade',{node_id:t.node_id,qid:q.qid,question:q.question,expected_points:q.expected_points,qtype:q.type,answer:ans});
    t.attempts.push(r);
    const cls=r.score>=0.8?'ok':r.score>=0.6?'warn':'bad';
    fb.innerHTML=`<div class="feedback ${cls}"><strong>${r.score.toFixed(2)}</strong><br>${escapeHtml(r.feedback)}</div>
      <div class="toolbar" style="margin-top:6px"><button class="btn primary" onclick="nextQ()">下一题</button></div>`;
  }catch(e){fb.innerHTML='<div class="feedback bad">评分失败: '+escapeHtml(e.message)+'</div>'}
}
function skipAns(){state.test.attempts.push({qid:state.test.questions[state.test.idx].qid,answer:'',score:0,feedback:'(skipped)',attempted_at:new Date().toISOString()});nextQ()}
function nextQ(){state.test.idx++;renderTest()}

async function loadStats(){
  const r=await api('GET','/api/stats');state.stats=r;
  if(r.empty){document.getElementById('v-dashboard').innerHTML='<div class="empty">No data</div>';return}
  document.getElementById('statGrid').innerHTML=`
    <div class="stat-card"><div class="stat-label">完成节点</div><div class="stat-value">${r.done_nodes}/${r.total_nodes}</div></div>
    <div class="stat-card"><div class="stat-label">连续天数</div><div class="stat-value">${r.streak}</div></div>
    <div class="stat-card"><div class="stat-label">当前节点</div><div class="stat-value" style="font-size:14px">${r.current_node_id||'—'}</div></div>
    <div class="stat-card"><div class="stat-label">状态</div><div class="stat-value" style="font-size:14px">${r.state}</div></div>
  `;
  // heatmap
  const today=new Date();today.setHours(0,0,0,0);
  const hm=document.getElementById('heatmap');hm.innerHTML='';
  const dayOfWeek=today.getDay();
  for(let i=52*7+dayOfWeek;i>=0;i--){
    const d=new Date(today-i*86400000).toISOString().slice(0,10);
    const c=r.by_day[d]||0;
    let cls='';if(c>0)cls='l1';if(c>=3)cls='l2';if(c>=6)cls='l3';if(c>=10)cls='l4';
    hm.innerHTML+=`<div class="hc ${cls}" title="${d}: ${c} 活动"></div>`;
  }
  // scores
  document.getElementById('scoresList').innerHTML=r.scores.length?r.scores.slice(-15).reverse().map(s=>`<div class="res"><span class="kind">${s.node}</span> ${s.date} · <strong>${s.score.toFixed(2)}</strong></div>`).join(''):'<div class="empty">暂无</div>';
}
async function genWeekly(){
  toast('生成周复盘中...');
  try{const r=await api('POST','/api/review/weekly');document.getElementById('reviewContent').innerHTML=md2html(r.markdown);toast('已生成')}
  catch(e){alert('失败: '+e.message)}
}

async function loadIndexStats(){
  try{
    const s=await api('GET','/api/index/stats');
    const el=document.getElementById('indexStat');
    if(!s.n_chunks){el.innerHTML='<span style="color:var(--warn)">⚠️ 还未建索引,点"重新建索引"开始</span>';return}
    el.innerHTML=`已索引 <strong>${s.n_documents}</strong> 篇 PDF · <strong>${s.n_chunks}</strong> 个 chunk`;
    if(s.documents&&s.documents.length){
      el.innerHTML+='<details style="margin-top:6px"><summary style="cursor:pointer">查看文档列表</summary><ul style="margin-top:6px">'+s.documents.map(d=>'<li style="font-family:ui-monospace,monospace;font-size:11px">'+escapeHtml(d)+'</li>').join('')+'</ul></details>';
    }
  }catch(e){document.getElementById('indexStat').innerHTML='<span style="color:var(--danger)">'+escapeHtml(e.message)+'</span>'}
}
async function rebuildIndex(){
  if(!confirm('重建索引会扫描 workspace/library/papers/ 所有 PDF,可能需要 1–3 分钟,继续?'))return;
  toast('索引中,请耐心等待...');
  try{
    const r=await api('POST','/api/index',{});
    toast(`已索引 ${r.n_pdfs} 篇 → ${r.n_chunks} chunks`);
    loadIndexStats();
  }catch(e){alert('失败: '+e.message)}
}
async function doRagQuery(){
  const q=document.getElementById('ragQuery').value.trim();if(!q)return;
  const box=document.getElementById('ragResults');
  box.innerHTML='<div class="empty"><span class="spinner"></span> 检索中(包含 LLM rerank,约 5–10 秒)...</div>';
  try{
    const r=await api('POST','/api/query',{query:q,top_n:5,rerank:true});
    if(!r.hits.length){box.innerHTML='<div class="empty">无匹配。先建索引?</div>';return}
    box.innerHTML=r.hits.map(h=>`<div class="card" style="margin-bottom:8px">
      <div style="font-size:11px;color:var(--mut);font-family:ui-monospace,monospace">[${escapeHtml(h.doc_id)} · §${escapeHtml(h.section)} · p.${h.page}] <span style="color:var(--ok)">score ${h.score}</span></div>
      <div style="font-weight:600;margin:4px 0">${escapeHtml(h.title)}</div>
      <div style="font-size:12px;white-space:pre-wrap;color:#333">${escapeHtml(h.preview)}…</div>
    </div>`).join('');
  }catch(e){box.innerHTML='<div class="empty" style="color:var(--danger)">'+escapeHtml(e.message)+'</div>'}
}

refreshAll();
setInterval(refreshAll,60000);
