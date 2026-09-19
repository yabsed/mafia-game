/* All model-generated text goes through textContent, never innerHTML. */
'use strict';
const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
let config = null, state = null, tab = 'public', replay = null, selected = null, suspects = new Set();
let feedSignature = '', stageSignature = '', detailSignature = '', lastGame = '', requestBusy = false, pollBusy = false;
const roles = {human:'인간', ai:'잠입 AI', detective:'분석가', doctor:'수리공'};
const phases = {discussion:'낮 · 도란도란 토론', vote:'낮 · 비밀 투표', runoff:'낮 · 결선 투표', night:'밤 · 비밀스러운 선택', ended:'이야기의 끝'};
const icons = {discussion:'☀', vote:'◇', runoff:'◇', night:'☾', ended:'✳'};
const positions = [[21,35],[50,27],[78,35],[83,62],[65,79],[33,79],[17,61]];
const money = (v) => '$' + Number(v || 0).toFixed(4);
let toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4000); }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Session-Token':config.token},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청을 처리하지 못했습니다.');
  return result;
}
async function poll() {
  if (pollBusy || !config) return;
  pollBusy = true;
  try {
    state = await api('/api/state?reveal=' + ($('#reveal').checked ? '1' : '0'));
    $('#connection').textContent = '로컬 연결됨'; render();
  } catch (_) { $('#connection').textContent = '연결 끊김'; $('#error').textContent = '서버와 연결이 끊겼습니다. 터미널에서 python3 run.py가 실행 중인지 확인하세요.'; $('#error').hidden = false; }
  finally { pollBusy = false; }
}
async function command(action, more = {}) {
  if (requestBusy) return;
  requestBusy = true;
  try { await api('/api/control', {action, ...more}); await poll(); }
  catch (e) { toast(e.message); }
  finally { requestBusy = false; }
}
function portrait(p, index) {
  // Template contains only locally controlled geometry and validated palette data.
  const color = /^#[0-9a-f]{6}$/i.test(p.color) ? p.color : '#bdcba3';
  const hats = [
    '<path d="M28 26Q26 7 39 13q9-12 17-2 13-5 16 12" fill="#e4dac3" stroke="#514f3c" stroke-width="2"/><path d="M27 26h47v9H27Z" fill="#e4dac3"/>',
    '<path d="M28 31q-7-26 22-26 28 0 24 26Z" fill="#687967"/><rect x="27" y="24" width="48" height="10" rx="4" fill="#80947a"/><circle cx="51" cy="6" r="6" fill="#94a88a"/>',
    '<path d="M26 31Q30 7 58 12q19 6 16 20" fill="#675b77"/><path d="M24 44v23m53-23v23" stroke="#d9bc8f" stroke-width="6" stroke-linecap="round"/>',
    '<ellipse cx="50" cy="30" rx="38" ry="9" fill="#ab895b"/><path d="M28 28l5-19h33l8 19" fill="#c8a676"/><path d="M29 25h42" stroke="#817354" stroke-width="5"/>',
    '<path d="M29 31Q23 12 50 13 79 10 73 33L55 24 36 33Z" fill="#6a7778"/>',
    '<path d="M29 31q-3-25 26-25 22 0 22 15L62 33Z" fill="#986b6b"/><path d="M37 21q22-16 37 2" stroke="#b88786" stroke-width="6" fill="none"/>',
    '<path d="M28 29q7-25 36-14l11 14" fill="#aca976"/><ellipse cx="51" cy="29" rx="33" ry="7" fill="#bec08b"/>'
  ];
  const glasses = index === 4 ? '<g fill="none" stroke="#384a44" stroke-width="2"><circle cx="37" cy="49" r="10"/><circle cx="62" cy="49" r="10"/><path d="M47 49h5"/></g>' : '';
  return `<svg class="avatar" viewBox="0 0 100 120" aria-hidden="true"><ellipse cx="51" cy="110" rx="26" ry="5" fill="#162c2230"/><path d="M34 94l-1 14m33-14 2 14" stroke="#414e3b" stroke-width="8" stroke-linecap="round"/><path d="M24 72q-11 7-9 16m61-16q11 7 9 16" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"/><path d="M23 48q-1-24 26-25 29-2 30 25l-1 38q-1 18-28 19-27-1-27-19Z" fill="${color}" stroke="#3c4938" stroke-width="1.5"/>${hats[index]}<g fill="#354334"><circle cx="37" cy="50" r="2.7"/><circle cx="63" cy="50" r="2.7"/></g>${glasses}<path d="M46 61q4 4 8 0" fill="none" stroke="#4d5140" stroke-width="1.8" stroke-linecap="round"/><g fill="#bc8870" opacity=".35"><ellipse cx="29" cy="59" rx="6" ry="3"/><ellipse cx="71" cy="59" rx="6" ry="3"/></g><path d="M35 79q15 6 29 0v19H35Z" fill="#ecdfbe" opacity=".26"/><path d="M46 81v13" stroke="#ede2c8" stroke-width="1.5" opacity=".55"/></svg>`;
}
function renderStage(g) {
  const signature = g ? JSON.stringify([g.id,g.phase,g.active,state.busy,g.players.map(p=>[p.alive,p.role,p.mood]),selected,[...suspects]]) : 'empty';
  if (signature === stageSignature) return;
  stageSignature = signature;
  const seats = $('#seats'); seats.replaceChildren();
  if (!g) return;
  let spots = positions;
  if (g.players.length === 5) spots = [[23,35],[50,27],[78,36],[70,74],[28,73]];
  if (g.players.length === 6) spots = [[22,35],[50,27],[78,35],[80,68],[50,79],[21,68]];
  g.players.forEach((p, i) => {
    const b = el('button', 'resident' + (!p.alive?' gone':'') + (g.active===p.id?' active':'') + (selected===p.id?' selected':'') + (suspects.has(p.id)?' suspect':''));
    b.style.left=spots[i][0]+'%'; b.style.top=spots[i][1]+'%'; b.style.setProperty('--lag',(-i*.71)+'s');
    b.setAttribute('aria-label',`${p.name}, ${p.job}, ${p.alive?'생존':'퇴장'}${p.role?', '+roles[p.role]:''}. 클릭하여 관찰`);
    const art = document.createElement('span'); art.innerHTML = portrait(p,i); b.append(art);
    b.append(el('span','bubble-dot',state.busy?'•••':'·'));
    b.append(el('span','resident-name',p.name));
    b.append(el('span',p.role?'resident-role':'resident-job',p.role?roles[p.role]:p.job));
    b.onclick=()=>{selected=p.id;render();}; seats.append(b);
  });
}
function renderDetail(g) {
  const signature = JSON.stringify([g?.id,g?.winner,g?.reveal,selected,[...suspects],g?.turn]);
  if (signature === detailSignature) return;
  detailSignature = signature;
  const box=$('#resident-detail'); box.replaceChildren();
  const p=g?.players.find(p=>p.id===selected);
  const icon=el('span','detail-icon',g?.winner?'✧':'✳'); box.append(icon);
  const content=el('div'); box.append(content);
  if (!p) {
    content.append(el('strong','',g?.winner?({human:'인간의 서툰 진심이 이겼어요.',ai:'너무 자연스러웠던 우리 이웃들.',draw:'이 수상한 우정은 다음에 계속.'}[g.winner]):'누가 가장 수상한가요?'));
    const correct=g?.players.filter(p=>p.role==='ai'&&suspects.has(p.id)).length;
    content.append(el('p','',g?.winner?`표시해 둔 ${suspects.size}명 중 잠입 AI는 ${correct}명. 이야기가 끝나면 모든 정체가 공개됩니다.`:'주민을 누르면 나만의 의심 표시를 남길 수 있어요. 게임에는 영향을 주지 않아요.')); return;
  }
  content.append(el('strong','',`${p.name} · ${p.job}${p.role?' · '+roles[p.role]:''}`));
  content.append(el('p','',p.last || p.persona));
  const b=el('button','outline',suspects.has(p.id)?'의심 해제':'의심 표시 ?'); b.disabled=!!g.winner;
  b.onclick=()=>{suspects.has(p.id)?suspects.delete(p.id):suspects.add(p.id);render();}; box.append(b);
}
function renderFeed(g) {
  const events=g?g.events.filter(e=>tab==='public'?e.audience===null:e.audience!==null):[];
  const max=events.length;
  const upto=replay===null?max:Math.min(replay,max);
  $('#rewind').max=max; $('#rewind').value=upto; $('#event-count').textContent=max;
  const signature=[g?.id,g?.turn,g?.reveal,tab,upto,max].join(':');
  if (feedSignature===signature) return;
  feedSignature=signature;
  const feed=$('#feed'); const nearBottom=feed.scrollHeight-feed.scrollTop-feed.clientHeight<95;
  const previousScroll=feed.scrollTop; feed.replaceChildren();
  if (!max) {
    const box=el('div','feed-empty'); box.append(el('span','',tab==='secret'?'♧':'☕'));
    box.append(el('h3','',tab==='secret'?'작은 비밀은 조용히':'아직은 조용한 마을'));
    box.append(el('p','',tab==='secret'?'감독 모드를 켜면 정체와 캐릭터의 짧은 일기를 볼 수 있어요. 일기는 연출용 메모이며 모델의 내부 추론이 아닙니다.':'모닥불을 켜면 작은 이야기들이 모이기 시작해요.')); feed.append(box); return;
  }
  events.slice(0,upto).forEach(e=>{
    if (['speech','diary','secret','ballot'].includes(e.kind)) {
      const p=g.players.find(p=>p.id===e.actor);
      const row=el('article','message'+(e.audience?' secret':''));
      const face=el('div','mini-avatar','··'); if(p) face.style.background=p.color; row.append(face);
      const main=el('div','message-main');const meta=el('div','message-meta');
      meta.append(el('strong','',p?.name||'마을'),el('small','',e.audience?'비밀 기록':p?.job||''),el('time','',`${e.day}일 ${e.phase==='night'?'밤':'낮'}`));
      main.append(meta,el('div','message-text',e.text));
      if(e.kind==='ballot') main.append(el('small','muted','선택: '+(g.players.find(p=>p.id===e.target)?.name||'기권')));
      row.append(main);feed.append(row);
    } else feed.append(el('div','system-event '+e.kind,e.text));
  });
  if (replay!==null||nearBottom||!g||g.turn<3) feed.scrollTop=feed.scrollHeight; else feed.scrollTop=previousScroll;
}
function render() {
  if(!state) return;
  const g=state.game, l=state.ledger;
  if(g&&g.id!==lastGame){lastGame=g.id;selected=null;suspects=new Set();replay=null;feedSignature='';}
  $('#error').hidden=!state.error; $('#error').textContent=state.error;
  $('#empty').hidden=!!g; $('#stage').dataset.phase=g?.phase||'discussion';
  $('#phase-label').textContent=g?`${g.day}일째 ${phases[g.phase]}`:'어서 와요, 모닥불 마을';
  $('#phase-icon').textContent=g?icons[g.phase]:'☀';
  $('#mode-badge').textContent=g?.mode==='deepseek'?'DEEPSEEK LIVE':'무료 데모 · $0';
  const active=g?.players.find(p=>p.id===g.active);
  $('#stage-status').textContent=!g?'잠시 쉬어 가기 좋은 곳':g.winner?'오늘도 조금 가까워진 우리':state.busy?`${active?.name||'주민'} 님이 ${g.phase==='discussion'?'말을 고르는':'조용히 선택하는'} 중…${!state.playing?' · 이 차례 후 멈춤':''}`:state.playing?'이야기가 천천히 흐르고 있어요':'일시정지 · 차 한 잔 마실까요?';
  $('#play').disabled=!g||!!g.winner; $('#play').textContent=state.playing?'Ⅱ 일시정지':'▶ 자동 관전';
  $('#step').disabled=!g||!!g.winner||state.busy||state.playing;
  $('#new').disabled=state.busy; $('#export').disabled=!g;
  $('#turn-count').textContent=(g?.turn||0)+'번의 작은 선택';
  $('#speed').value=String(state.delay);
  $('#total-cost').replaceChildren(document.createTextNode(money(l.total_usd)+' '),el('span','',`/ $${Number(l.limit_usd).toFixed(2)}`));
  $('#game-cost').textContent=money(l.game_usd)+(g?` / $${g.budget}`:'');
  $('#budget-fill').style.width=Math.min(100,Number(l.total_usd)/Math.max(.001,Number(l.limit_usd))*100)+'%';
  $('#token-count').textContent=`실제 API 호출 ${l.calls}회 · ${(l.input_tokens+l.output_tokens).toLocaleString()} tokens`;
  $('#reservation-note').textContent=Number(l.reserved_usd)>0?`미확정 요청 예약 ${money(l.reserved_usd)} 포함. 공급자 청구 여부가 불확실해 안전하게 예산에서 차감해 두었습니다.`:'API 키는 로컬 서버에만 보관됩니다. GPU도, 복잡한 설치도 필요 없어요.';
  renderStage(g);renderDetail(g);renderFeed(g);
}
function openSetup(){ $('#setup-error').textContent='';$('#setup-dialog').showModal();updateMode(); }
function updateMode(){
  const live=$('input[name=mode]:checked').value==='deepseek';
  $('#live-settings').hidden=!live;
  $('#key-note').hidden=!live;
  $('#key-note').textContent=config?.key_configured?'로컬 API 키가 준비되었습니다. 입력 $0.30 / 출력 $1.20 (Flash, 100만 토큰당 피크 기준). 모델과 단가는 README를 확인하세요.':'.env에 DEEPSEEK_API_KEY를 설정하고 서버를 다시 시작하세요. 키가 없어도 무료 데모는 바로 실행할 수 있어요.';
  $('#start').disabled=!config||(live&&!config.key_configured);
}
$('#new').onclick=openSetup;$('#welcome-start').onclick=openSetup;
$$('input[name=mode]').forEach(r=>r.onchange=updateMode);
function $$(s){return [...document.querySelectorAll(s)];}
$$('[data-close]').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.close).close());
$('#setup-form').onsubmit=async(e)=>{
  e.preventDefault(); const form=new FormData(e.target);const live=form.get('mode')==='deepseek';
  if(live&&form.get('consent')!=='on') {$('#setup-error').textContent='실제 API 과금 동의를 확인해 주세요.';return;}
  $('#start').disabled=true;
  try { await api('/api/new',{mode:form.get('mode'),model:form.get('model'),count:Number(form.get('count')),rounds:Number(form.get('rounds')),budget:form.get('budget'),seed:Number(form.get('seed')),max_days:Number(form.get('max_days')),consent:form.get('consent')==='on',autoplay:true});
    $('#setup-dialog').close(); await poll();
  } catch(err){$('#setup-error').textContent=err.message;} finally{updateMode();}
};
$('#play').onclick=()=>command(state?.playing?'pause':'play');
$('#step').onclick=()=>command('step');$('#speed').onchange=e=>command('speed',{delay:Number(e.target.value)});
$('#reveal').onchange=()=>{feedSignature='';poll();};
function setTab(value){tab=value;replay=null;$('#public-tab').classList.toggle('active',value==='public');$('#secret-tab').classList.toggle('active',value==='secret');$('#public-tab').setAttribute('aria-selected',String(value==='public'));$('#secret-tab').setAttribute('aria-selected',String(value==='secret'));render();}
$('#public-tab').onclick=()=>setTab('public');$('#secret-tab').onclick=()=>setTab('secret');
$('#rewind').oninput=e=>{replay=Number(e.target.value);renderFeed(state?.game);};
$('#follow').onclick=()=>{replay=null;feedSignature='';renderFeed(state?.game);$('#feed').scrollTop=$('#feed').scrollHeight;};
$('#export').onclick=async()=>{
  try {const data=await api('/api/export?reveal='+($('#reveal').checked?'1':'0'));const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download=`village-${data.game.id.slice(0,8)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('현재 보기의 기록을 저장했습니다. 감독 모드는 비밀도 포함합니다.');} catch(e){toast(e.message);}
};
$('#history').onclick=async()=>{
  if(state?.playing) await command('pause');
  $('#history-dialog').showModal();const list=$('#history-list');list.replaceChildren(el('p','muted','서랍을 여는 중…'));
  try {const entries=await api('/api/history');list.replaceChildren();if(!entries.length)list.append(el('p','muted','아직 저장된 마을이 없어요.'));
    entries.forEach(g=>{const b=el('button','history-entry');const wrap=el('span','',new Date(g.created).toLocaleString('ko-KR'));wrap.append(el('small','',`${g.mode==='demo'?'무료 데모':'DeepSeek'} · ${g.day}일차 · ${g.turn}번의 선택 · ${g.winner?'완결':'이어보기'}`));b.append(wrap,el('span','','↗'));b.onclick=async()=>{try{await api('/api/load',{id:g.id});$('#history-dialog').close();await poll();}catch(e){toast(e.message);}};list.append(b);});
  }catch(e){list.replaceChildren(el('p','form-error',e.message));}
};
let audio=null, gain=null, sounding=false;
$('#sound').onclick=async()=>{
  try {
    if(!audio){audio=new (window.AudioContext||window.webkitAudioContext)();gain=audio.createGain();gain.gain.value=0;gain.connect(audio.destination);
      [130.81,196,261.63].forEach((freq,i)=>{const o=audio.createOscillator();o.type='sine';o.frequency.value=freq;o.detune.value=i*2;const g=audio.createGain();g.gain.value=.2/(i+1);o.connect(g);g.connect(gain);o.start();});}
    await audio.resume();sounding=!sounding;gain.gain.setTargetAtTime(sounding?.07:0,audio.currentTime,.5);$('#sound span').textContent=sounding?'소리 끄기':'소리 켜기';$('#sound').setAttribute('aria-pressed',String(sounding));
  } catch(_){toast('이 브라우저에서는 배경음을 시작할 수 없어요.');}
};
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!document.querySelector('dialog[open]')&&!['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement.tagName)){e.preventDefault();if(state?.game&&!state.game.winner)command(state.playing?'pause':'play');}});
(async()=>{try{config=await api('/api/config');$('input[name=budget]').max=config.total_budget;await poll();setInterval(poll,700);}catch(_){$('#connection').textContent='연결 실패';$('#error').hidden=false;$('#error').textContent='로컬 서버에 연결하지 못했습니다. 페이지를 새로고침하세요.';}})();
