"""Dashboard front-end assets."""

_CSS_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Raydium-LP1 · mission control</title>
<style>
:root{--bg:#000;--txt:#eef1f6;--muted:#8b9cb3;--line:#2a2f38;--yellow:#e6c200;--ok:#3dd68c;--warn:#f5c451;--bad:#ff6b6b;--a:#6eb5ff;
--sans:ui-sans-serif,system-ui,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.5 var(--sans)}
header{padding:.75rem 1rem;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;background:#0a0a0a}
h1{font-size:1.05rem;margin:0}.tag{font-size:.62rem;letter-spacing:.06em;color:var(--muted);border:1px solid #444;border-radius:999px;padding:.12rem .45rem;text-transform:uppercase}
.tag.live{border-color:var(--yellow);color:#ffe566}
.tb{margin-left:auto;display:flex;gap:.45rem;flex-wrap:wrap;align-items:center}
button{font:inherit;border-radius:8px;border:1px solid #444;background:#161616;color:var(--txt);padding:.38rem .75rem;cursor:pointer}
button.primary{background:#1a2e1a;border-color:var(--yellow);color:#ffe566;font-weight:650}
label.hdr{font-size:.78rem;color:var(--muted)}
.page{max-width:1440px;margin:0 auto;padding:1rem;display:flex;flex-direction:column;gap:1rem}
.row2{display:grid;gap:1rem;grid-template-columns:1fr 1fr}
@media(max-width:960px){.row2{grid-template-columns:1fr}}
.cd{border:3px solid var(--yellow);border-radius:10px;background:#000;overflow:hidden}
.cd>h2{margin:0;padding:.55rem .85rem;font-size:.88rem;display:flex;align-items:center;gap:.5rem;border-bottom:1px solid #2a2a2a;background:#000;color:var(--txt)}
.cd .bd{padding:.75rem .85rem}
.hint{font-size:.76rem;color:var(--muted);margin:0 0 .55rem;line-height:1.4}
.sg{font-size:.62rem;color:var(--muted);margin:.65rem 0 .3rem;text-transform:uppercase;letter-spacing:.08em;font-weight:650}
.kp{display:grid;gap:.45rem;margin-bottom:.7rem;grid-template-columns:repeat(auto-fit,minmax(100px,1fr))}
.k{border:1px solid #333;border-radius:8px;background:#0a0a0a;padding:.45rem .55rem}
.k span.x{display:block;font-size:.58rem;color:var(--muted);text-transform:uppercase}
.k span.v{font-size:1.05rem;font-weight:650;font-variant-numeric:tabular-nums}
.k.g .v{color:var(--ok)}.k.r .v{color:var(--bad)}
.bar{display:grid;grid-template-columns:minmax(0,140px) 1fr 2rem;font-size:.76rem;gap:.4rem;margin:.28rem 0;align-items:center}
.tr{height:6px;border-radius:4px;background:#1a1a1a;border:1px solid #333;overflow:hidden}
.fil{height:100%;background:linear-gradient(90deg,var(--a),#9fd0ff)}
.ta,.tb2{width:100%;border-collapse:collapse;font-size:.76rem}
.ta th,.ta td,.tb2 th,.tb2 td{padding:.3rem .4rem;border-bottom:1px solid #2a2a2a;text-align:left}
.ta th,.tb2 th{color:var(--muted);font-weight:500;font-size:.7rem}
.tb2 td.mono,.ta td.c{font-family:var(--mono);font-size:.7rem;color:var(--muted)}
.tb2 td.num{text-align:right;font-variant-numeric:tabular-nums}
ul.z{margin:.35rem 0;color:var(--muted);font-size:.8rem;padding-left:1rem;border-left:2px solid #444}
.pr div{padding:.28rem 0;border-bottom:1px dashed #333;font-size:.78rem;color:var(--muted)}
.fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.6rem}
.lb{display:flex;flex-direction:column;gap:.2rem;font-size:.58rem;color:var(--muted);text-transform:uppercase}
.lb.h{flex-direction:row;text-transform:none;font-size:.8rem;color:var(--txt);align-items:center;gap:.4rem}
input,select,textarea{font:inherit;border-radius:6px;border:1px solid #444;background:#111;color:var(--txt);padding:.32rem .45rem;width:100%}
textarea{min-height:56px;font-family:var(--mono);font-size:.75rem}
.livebox{font-family:var(--mono);font-size:.72rem;background:#0a0a0a;border:1px solid #333;border-radius:6px;padding:.45rem .6rem;margin-bottom:.65rem;color:var(--muted);line-height:1.5}
.live-ok{color:var(--ok)}.live-bad{color:var(--bad)}
.ban-row{max-width:1440px;margin:0 auto;padding:.5rem 1rem 0}
.ban{border-radius:8px;padding:.55rem .8rem;margin:0 0 .4rem;border-left:3px solid;font-size:.82rem}
.ban-info{border-color:var(--a);background:#0d1520;color:#b8d4f0}
.ban-ok{border-color:var(--ok);background:#0a1a12;color:#b8f0d0}
.ban-warn{border-color:var(--warn);background:#1a1508;color:#ffe8b0}
.ban-err{border-color:var(--bad);background:#1a0a0a;color:#ffc8c8}
.ban-hide{display:none}
.drift-warn{background:#1a1508;border:1px solid var(--yellow);color:#ffe08a;font-size:.78rem;margin:0 0 .55rem;padding:.45rem .6rem;border-radius:6px}
.pill{display:inline-block;font-size:.62rem;padding:.08rem .35rem;border-radius:4px;text-transform:uppercase;font-weight:650}
.pill.ok{background:#0f2a1a;color:var(--ok)}.pill.warn{background:#2a2208;color:var(--warn)}.pill.bad{background:#2a1010;color:var(--bad)}
.alert-row{padding:.35rem 0;border-bottom:1px solid #222;font-size:.76rem;font-family:var(--mono)}
.alert-row.bad{color:#ffb4b4}
.pos-row{padding:.4rem 0;border-bottom:1px solid #222;font-size:.78rem}
.pos-row .sub{font-size:.72rem;color:var(--muted);margin-top:.15rem}
a{color:var(--a);text-decoration:none}a:hover{text-decoration:underline}

.opt-bar{max-width:1440px;margin:0 auto;padding:.45rem 1rem 0;display:flex;flex-wrap:wrap;gap:.65rem 1rem;align-items:flex-start;border-bottom:1px solid #222}
.opt-toggle{display:flex;align-items:center;gap:.45rem;font-size:.82rem;white-space:nowrap}
.opt-toggle input{accent-color:var(--yellow)}
.opt-pulse{display:flex;flex-wrap:wrap;gap:.35rem .55rem;flex:1;min-width:200px}
.pulse-chip{font-size:.7rem;padding:.22rem .45rem;border-radius:6px;border:1px solid #333;background:#0a0a0a;max-width:280px;line-height:1.3}
.pulse-chip.ok{border-color:#2a4a3a;color:#9fddb0}.pulse-chip.warn{border-color:#5a4a20;color:#ffe08a}.pulse-chip.bad{border-color:#5a2a2a;color:#ffb4b4}
.opt-reco{width:100%;font-size:.75rem;color:var(--muted);margin-top:.2rem}
.catalog details{margin:.4rem 0}.catalog summary{cursor:pointer;color:var(--a);font-size:.8rem}
.catalog ol{margin:.35rem 0 0 1rem;padding:0;font-size:.72rem;color:var(--muted);max-height:220px;overflow:auto}
.settings-scroll{max-height:min(72vh,820px);overflow:auto;padding-right:.25rem}
</style></head><body>
<header><h1>Raydium-LP1 · mission control</h1><span class="tag live">127.0.0.1</span><span class="tag" id="stamp">loading…</span>
<div class="tb"><label class="hdr"><input type="checkbox" id="auto" checked/> Auto 5s</label>
<button type="button" id="reload">Reload</button><button type="button" id="save" class="primary">Save settings</button></div></header>
<div class="opt-bar">
  <label class="opt-toggle"><input type="checkbox" id="opt-auto"/> <b>Auto-tune</b> settings</label>
  <div id="opt-pulse" class="opt-pulse">
  <div id="opt-reco" class="opt-reco"></div>
</div>
<div class="ban-row">
<div class="ban ban-info" id="ban-info"><b>How it works</b> Save updates settings. Scanner reloads on the next page. All panels refresh after each full scan.</div>
<div class="ban ban-hide" id="ban-ok"></div><div class="ban ban-hide" id="ban-warn"></div><div class="ban ban-hide" id="ban-err"></div>
</div>
<div id="js-fatal" class="ban ban-err ban-hide" style="max-width:1440px;margin:0 auto .4rem"></div>
<script type="application/json" id="boot">BOOT_JSON</script>
<main class="page">
<div class="row2">
  <div class="cd"><h2>Funnel <a href="/api/dashboard" style="margin-left:auto;font-size:.7rem;color:var(--muted)">json</a></h2><div id="fu" class="bd"><p class="hint">Loading…</p></div></div>
  <div class="cd"><h2>Settings</h2><div class="bd settings-scroll"><details class="catalog"><summary>All settings (numbered)</summary><ol id="catalog"></ol></details><div id="live" class="livebox">Loading…</div><div id="fo"></div></div></div>
</div>
<div class="cd"><h2>Candidates <span id="cand-note" style="font-weight:400;font-size:.72rem;color:var(--muted);margin-left:.35rem"></span></h2>
<div id="cand" class="bd"><p class="hint">Waiting for scan…</p></div></div>
<div class="row2">
  <div class="cd"><h2>Open positions (dry-run)</h2><div id="pos" class="bd"><p class="hint">—</p></div></div>
  <div class="cd"><h2>Recent alerts</h2><div class="bd"><p class="hint"><b>CRITICAL</b> = liquidity health emergency (TVL down ≥30% from entry and/or volume collapsed). Dry-run: swap-back plan logged only.</p><div id="alerts"></div>
</div>
<div class="row2">
  <div class="cd"><h2>Momentum TOP HOT</h2><div id="mom" class="bd"><p class="hint">—</p></div></div>
  <div class="cd"><h2>Scan &amp; wallet</h2><div id="scan" class="bd"><p class="hint">—</p></div></div>
</div>
</main>
<script>
CLIENT_JS_HERE
</script></body></html>"""

_CLIENT_JS = r"""
'use strict';
(function(){
  function $(s,r){return (r||document).querySelector(s);}
  function esc(t){var d=document.createElement('div');d.textContent=t==null?'':String(t);return d.innerHTML;}
  window.onerror=function(msg,src,line){
    var b=$('#js-fatal'); if(b){b.classList.remove('ban-hide');b.textContent='UI error: '+msg+' (line '+line+')';}
  };
  var boot={};
  try{boot=JSON.parse(($('#boot')||{}).textContent||'{}');}catch(e){
    var b=$('#js-fatal');if(b){b.classList.remove('ban-hide');b.textContent='Boot JSON error: '+e;}
  }
  var SECTIONS=boot.form_sections||[];
  function num(n){return (Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});}
  function aprPct(n){var x=Number(n);return isFinite(x)?x.toLocaleString(undefined,{minimumFractionDigits:1,maximumFractionDigits:2}):'0';}
  function money(n){var x=Number(n);return isFinite(x)?x.toLocaleString(undefined,{maximumFractionDigits:0}):'0';}
  function pill(score){
    var s=String(score||'').toLowerCase();
    if(s==='critical') return '<span class="pill bad">critical</span>';
    if(s==='warning') return '<span class="pill warn">warning</span>';
    return '<span class="pill ok">healthy</span>';
  }
  function sortNote(s){
    if(s&&s.sort_candidates_by_apr) return 'sorted by Raydium day.apr (highest first)';
    if(s&&s.sort_candidates_by_momentum) return 'sorted by momentum';
    return 'page order';
  }
  function displayFor(f,raw){
    var k=f.key;
    if(k==='route_sources_json') return JSON.stringify(raw.route_sources||['jupiter','raydium']);
    if(k==='lp_range_width_candidates_json') return JSON.stringify(raw.lp_range_width_candidates||[12,20,30,50]);
    if(k==='solana_rpc_urls_lines') return (raw.solana_rpc_urls||[]).join('\n');
    if(k==='blocked_mints_lines') return (raw.blocked_mints||[]).join('\n');
    if(k==='allowed_quote_symbols_csv') return (raw.allowed_quote_symbols||[]).join(', ');
    if(k==='blocked_token_symbols_csv') return (raw.blocked_token_symbols||[]).join(', ');
    if(raw[k]===undefined||raw[k]===null) return '';
    return raw[k];
  }
  function mount(raw){
    var root=$('#fo'); root.innerHTML='';
    for(var si=0;si<SECTIONS.length;si++){
      var sec=SECTIONS[si];
      var sg=document.createElement('div'); sg.className='sg'; sg.textContent=sec.title; root.appendChild(sg);
      var fg=document.createElement('div'); fg.className='fg';
      for(var fi=0;fi<(sec.fields||[]).length;fi++){
        var f=sec.fields[fi], kk=f.key, ty=f.type;
        if(ty==='checkbox'){
          var L=document.createElement('label'); L.className='lb h';
          var inp=document.createElement('input'); inp.type='checkbox'; inp.dataset.sk=kk; inp.checked=!!raw[kk];
          L.appendChild(inp); L.appendChild(document.createTextNode(' '+f.label)); fg.appendChild(L); continue;
        }
        var lab=document.createElement('label'); lab.className='lb';
        var cap=document.createElement('span'); cap.textContent=f.label; lab.appendChild(cap);
        var inp2;
        if(ty==='select'){
          inp2=document.createElement('select'); inp2.dataset.sk=kk;
          (f.options||[]).forEach(function(o){var o2=document.createElement('option');o2.value=o;o2.textContent=o;
            if(String(raw[kk])===String(o))o2.selected=true; inp2.appendChild(o2);});
        } else if(ty==='json_text'||ty==='lines'){
          inp2=document.createElement('textarea'); inp2.dataset.sk=kk; inp2.rows=ty==='lines'?3:2;
          inp2.value=displayFor(f,raw);
        } else {
          inp2=document.createElement('input'); inp2.type=(ty==='number'?'number':'text'); inp2.dataset.sk=kk;
          if(f.step) inp2.step=f.step;
          var dh=displayFor(f,raw); inp2.value=(dh!==''&&dh!=null)?dh:'';
        }
        lab.appendChild(inp2); fg.appendChild(lab);
      }
      root.appendChild(fg);
    }
  }
  function collect(){
    var patch={}, els=document.querySelectorAll('[data-sk]');
    for(var i=0;i<els.length;i++){
      var el=els[i], k=el.dataset.sk;
      if(k==='route_sources_json'){patch.route_sources=JSON.parse(el.value.trim()||'[]');continue;}
      if(k==='lp_range_width_candidates_json'){var a=JSON.parse(el.value.trim()||'[]');patch.lp_range_width_candidates=a.map(Number);continue;}
      if(k==='solana_rpc_urls_lines'){patch.solana_rpc_urls=el.value.split(/\r?\n/).map(function(s){return s.trim();}).filter(Boolean);continue;}
      if(k==='blocked_mints_lines'){patch.blocked_mints=el.value.split(/\r?\n/).map(function(s){return s.trim();}).filter(Boolean);continue;}
      if(k==='allowed_quote_symbols_csv'){patch.allowed_quote_symbols=el.value.split(',').map(function(s){return s.trim().toUpperCase();}).filter(Boolean);continue;}
      if(k==='blocked_token_symbols_csv'){patch.blocked_token_symbols=el.value.split(',').map(function(s){return s.trim().toUpperCase();}).filter(Boolean);continue;}
      if(el.type==='checkbox'){patch[k]=el.checked;continue;}
      if(el.tagName==='SELECT'){patch[k]=el.value;continue;}
      if(el.type==='number'){var tv=el.value.trim();if(tv==='')continue;var n=Number(tv);if(isNaN(n))throw new Error(k);patch[k]=n;continue;}
      patch[k]=el.value;
    }
    return patch;
  }
  async function gj(url,opt){
    var r=await fetch(url,opt), t=await r.text(), d;
    try{d=JSON.parse(t);}catch(e){throw new Error((t||'').slice(0,120));}
    if(!r.ok) throw new Error(d.error||t||r.status);
    return d;
  }
  function renderFunnel(d,st){
    var ls=d.last_scan||{}, sc=ls.scanned_count||0, c=ls.candidate_count||0, rej=ls.rejected_count||0;
    var rate=(c+rej)>0?(100*c/(c+rej)):0;
    var snap=d.settings||{}, note='';
    if(st&&st.settings_drift_keys&&st.settings_drift_keys.length){
      var ds=st.dashboard_scan_settings||{}, dk=st.settings_on_disk||{};
      note='<p class="drift-warn"><b>Stale funnel</b> scan min_apr='+esc(ds.min_apr)+' · disk '+esc(dk.min_apr)+'</p>';
    }
    var bd=Object.entries(ls.rejection_breakdown||{}).sort(function(a,b){return b[1]-a[1];});
    var mx=Math.max.apply(null,bd.map(function(x){return x[1];}).concat([0]))||1;
    var bars=bd.slice(0,10).map(function(kv){
      return '<div class="bar"><div>'+esc(kv[0])+'</div><div class="tr"><div class="fil" style="width:'+((100*kv[1]/mx).toFixed(0))+'%"></div></div><div style="text-align:right;color:var(--muted);font-family:var(--mono)">'+kv[1]+'</div></div>';
    }).join('');
    $('#fu').innerHTML=note+
      '<div class="kp"><div class="k"><span class="x">Scanned</span><span class="v">'+sc+'</span></div>'+
      '<div class="k g"><span class="x">Candidates</span><span class="v">'+c+'</span></div>'+
      '<div class="k r"><span class="x">Rejected</span><span class="v">'+rej+'</span></div>'+
      '<div class="k"><span class="x">Pass</span><span class="v">'+rate.toFixed(1)+'%</span></div></div>'+
      (bars?'<motion class="sg">Reject categories</div>'+bars:'');
  }
  function renderCandidates(d){
    var rows=(d.open_positions||[]).slice();
    rows.sort(function(a,b){return (Number(b.apr)||0)-(Number(a.apr)||0);});
    var note=sortNote(d.settings||{});
    $('#cand-note').textContent='('+note+')';
    if(!rows.length){$('#cand').innerHTML='<p class="hint">No candidates yet.</p>';return;}
    $('#cand').innerHTML='<table class="tb2"><thead><tr><th>Pair</th><th class="num">APR%</th><th class="num">TVL</th><th class="num">VOL24</th><th>Mom</th><th>Health</th><th>Pool state</th></tr></thead><tbody>'+
      rows.map(function(p,i){
        var mom=(p.momentum_score!=null)?esc(String(p.momentum_score))+' '+esc(String(p.momentum_tier||'')):'—';
        return '<tr><td>'+esc(p.pair||'')+'</td><td class="num">'+aprPct(p.apr)+'</td><td class="num">'+money(p.liquidity_usd)+'</td><td class="num">'+money(p.volume_24h_usd)+'</td><td>'+mom+'</td><td>'+pill(p.health)+'</td><td class="mono">'+esc(p.pool_id||'')+'</td></tr>';
      }).join('')+'</tbody></table><p class="hint">Dry-run only — no wallet signing.</p>';
  }
  function renderPositions(d){
    var rows=d.open_positions||[];
    if(!rows.length){$('#pos').innerHTML='<p class="hint">None</p>';return;}
    $('#pos').innerHTML=rows.map(function(p){
      var reasons=(p.health_reasons||[]).map(function(r){return esc(r);}).join('; ');
      return '<div class="pos-row"><b>'+esc(p.pair||'')+'</b> '+pill(p.health)+' APR '+aprPct(p.apr)+'% TVL $'+money(p.liquidity_usd)+
        '<div class="sub">pool '+esc(p.pool_id||'')+(reasons?'<br/>'+reasons:'')+'</div></div>';
    }).join('');
  }
  function renderAlerts(d){
    var al=d.recent_alerts||[];
    if(!al.length){$('#alerts').innerHTML='<p class="hint">No recent emergency alerts.</p>';return;}
    $('#alerts').innerHTML=al.slice().reverse().map(function(a){
      var sev=String(a.severity||'').toLowerCase();
      var cls=sev==='critical'?'alert-row bad':'alert-row';
      var rs=(a.reasons||[]).slice(0,2).join(' · ');
      return '<div class="'+cls+'">'+esc((a.timestamp||'').replace('T',' ').slice(0,19))+'Z <b>'+esc(String(a.severity||'').toUpperCase())+'</b> '+esc(a.pair||'')+
        ' pool='+esc(a.pool_id||'')+(rs?'<br/><span style="color:var(--muted)">'+esc(rs)+'</span>':'')+'</div>';
    }).join('');
  }
  function renderMomentum(d){
    var hot=d.momentum_hot_top||[];
    if(!hot.length){$('#mom').innerHTML='<p class="hint">Momentum sniffer off or no HOT list.</p>';return;}
    $('#mom').innerHTML='<table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>CMB</th><th class="num">TVL</th><th class="num">VOL</th><th class="num">APR</th></tr></thead><tbody>'+
      hot.slice(0,25).map(function(p,i){
        return '<tr><td class="c">'+(i+1)+'</td><td>'+esc(p.pair||'')+'</td><td>'+esc(String(p.combined_score!=null?p.combined_score:(p.momentum&&p.momentum.combined_score)||0))+'</td>'+
          '<td class="num">'+money(p.liquidity_usd||p.tvl)+'</td><td class="num">'+money(p.volume_24h_usd||p.vol)+'</td><td class="num">'+aprPct(p.apr)+'</td></tr>';
      }).join('')+'</tbody></table>';
  }
  function renderScan(d){
    var s=d.settings||{}, ls=d.last_scan||{}, w=d.wallet_capacity||{}, cap=(w.capacity||{}), bal=(w.balance||{});
    var hs=ls.health_summary||{};
    var rej=Object.entries(ls.rejection_breakdown||{}).sort(function(a,b){return b[1]-a[1];}).slice(0,4)
      .map(function(kv){return kv[0]+':'+kv[1];}).join(' · ');
    $('#scan').innerHTML=
      '<div class="sg">Settings</div><p class="hint">strategy='+esc(s.strategy)+' · APR≥'+esc(s.min_apr)+'% · TVL≥$'+money(s.min_liquidity_usd)+
      ' · pages '+esc(s.pages)+'×'+esc(s.page_size)+' · sort '+esc(s.pool_sort_field||'liquidity')+'</p>'+
      '<div class="sg">Last scan</div><p class="hint">'+esc((ls.scanned_at||'').replace('T',' ').slice(0,19))+'Z · scanned '+esc(ls.scanned_count)+
      ' · candidates '+esc(ls.candidate_count)+' · rejected '+esc(ls.rejected_count)+'</p>'+
      (rej?'<p class="hint">Rejects: '+esc(rej)+'</p>':'')+
      '<p class="hint">Health: healthy='+esc(hs.healthy||0)+' warning='+esc(hs.warning||0)+' critical='+esc(hs.critical||0)+'</p>'+
      '<div class="sg">Wallet</div><p class="hint">balance '+(bal.sol!=null?Number(bal.sol).toFixed(4)+' SOL':'n/a')+
      ' · max_positions='+esc(cap.max_positions!=null?cap.max_positions:'0')+' · dry_run='+esc(s.dry_run)+'</p>';
  }
  function renderLive(st){
    var el=$('#live'); if(!el)return;
    var hb=st.heartbeat||{}, sync='';
    if(st.scanner_scanning) sync='<span class="live-bad">Scanning page '+esc(hb.page||'?')+'/'+esc(hb.pages_total||'?')+'</span>';
    else if(st.dashboard_mtime) sync='<span class="live-ok">Dashboard fresh</span>';
    else sync='<span class="live-bad">Waiting for first scan</span>';
    if(hb.last_error&&!String(hb.last_error).match(/git pull/i))
      sync+='<br/><span class="live-bad">'+esc(hb.last_error)+'</span>';
    el.innerHTML='<strong>settings</strong> '+esc(st.settings_path)+'<br/>mtime '+esc(st.settings_mtime||'?')+
      '<br/><strong>dashboard</strong> mtime '+esc(st.dashboard_mtime||'?')+'<br/>'+sync;
  }
  function showBan(id,html){
    ['ban-ok','ban-warn','ban-err'].forEach(function(b){
      var el=$('#'+b); if(!el)return;
      if(b===id){el.innerHTML=html;el.classList.remove('ban-hide');} else el.classList.add('ban-hide');
    });
  }
  function renderAll(d,st){
    $('#stamp').textContent=(d.generated_at||'?').replace('T',' ').slice(11,19)+'Z';
    renderFunnel(d,st); renderCandidates(d); renderPositions(d); renderAlerts(d); renderMomentum(d); renderScan(d);
  }

  function renderCatalog(){
    var cat=(boot.settings_catalog||[]);
    var el=$('#catalog'); if(!el||!cat.length) return;
    el.innerHTML=cat.map(function(it){
      return '<li><b>'+esc(it.n)+'. '+esc(it.title)+'</b> — '+esc(it.detail)+'</li>';
    }).join('');
  }
  function pulseClass(level){return level==='bad'?'bad':(level==='warn'?'warn':'ok');}
  function renderOptimizer(opt){
    if(!opt) return;
    var auto=$('#opt-auto');
    if(auto) auto.checked=!!opt.auto_apply_enabled;
    var pulse=opt.market_pulse||[];
    var pel=$('#opt-pulse');
    if(pel){
      pel.innerHTML=pulse.map(function(p){
        return '<span class="pulse-chip '+pulseClass(p.level)+'" title="'+esc(p.text)+'"><b>'+esc(p.label)+'</b> '+esc(p.text)+'</span>';
      }).join('');
    }
    var rec=$('#opt-reco');
    if(rec){
      var keys=Object.keys(opt.recommended_patch||{});
      if(!keys.length) rec.textContent='Optimizer waiting for dashboard.json…';
      else if(opt.auto_apply_enabled) rec.innerHTML='<span class="live-ok">Auto-tune ON</span> — last targets: '+keys.map(function(k){return esc(k)+'='+esc(String(opt.recommended_patch[k]));}).join(', ');
      else rec.innerHTML='<span class="live-warn">Auto-tune OFF</span> — suggestions only: '+keys.slice(0,6).map(function(k){return esc(k)+'='+esc(String(opt.recommended_patch[k]));}).join(', ')+
        (opt.budget_usd&&opt.budget_usd.example?'<br/>'+esc(opt.budget_usd.example):'');
    }
  }
  async function pollOptimizer(){
    try{
      var opt=await gj('/api/optimizer');
      renderOptimizer(opt);
    }catch(e){}
  }
  var optAuto=$('#opt-auto');
  if(optAuto){
    optAuto.onchange=function(){
      fetch('/api/optimizer/toggle',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({enabled:optAuto.checked})})
        .then(function(r){return r.json();})
        .then(function(d){renderOptimizer(d); showBan('ban-ok', optAuto.checked?'<b>Auto-tune ON</b>':'<b>Auto-tune OFF</b> (still analyzing)'); loadSettings().catch(function(){});})
        .catch(function(e){showBan('ban-err',esc(String(e)));});
    };
  }

  async function refresh(){
    var st=null; try{st=await gj('/api/status');}catch(e){}
    try{
      var dash=await gj('/api/dashboard');
      renderAll(dash,st);
    }catch(e){
      $('#fu').innerHTML='<p class="drift-warn"><b>Dashboard not ready</b> — '+esc(String(e))+
        '<br/>Keep Scanner tab running until <code>reports/dashboard.json</code> exists.</p>';
      $('#cand').innerHTML='<p class="hint">Candidates appear after first scan.</p>';
    }
    try{
      if(st&&st.scanner_scanning) showBan('ban-warn','<b>Scanner running</b> — tables update when scan completes.');
    }catch(e){}
  }
  async function loadSettings(){var s=await gj('/api/settings'); mount(s);}
  async function pollStatus(){try{var st=await gj('/api/status'); renderLive(st);}catch(e){}}
  $('#reload').onclick=function(){showBan(null,''); refresh().catch(function(e){showBan('ban-err',esc(String(e)));}); loadSettings().catch(function(){}); pollStatus();};
  $('#save').onclick=function(){
    showBan('ban-warn','<b>Saving…</b>');
    try{
      fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())})
        .then(function(r){return r.text().then(function(t){return {r:r,t:t};});})
        .then(function(x){
          var d; try{d=JSON.parse(x.t);}catch(e){throw new Error(x.t.slice(0,160));}
          if(!x.r.ok) throw new Error(d.error||x.t);
          showBan('ban-ok','<b>Saved</b> '+esc((d.keys_patched||[]).join(', ')));
          pollStatus();
        }).catch(function(e){showBan('ban-err',esc(String(e)));});
    }catch(e){showBan('ban-err',esc(String(e)));}
  };
  var timer=null;
  function arm(){clearInterval(timer); if($('#auto').checked) timer=setInterval(function(){refresh().catch(function(){});},5000);}
  $('#auto').onchange=arm;
  refresh().catch(function(){}); loadSettings().catch(function(){}); pollStatus(); setInterval(pollStatus,12000); arm();
})();
"""
