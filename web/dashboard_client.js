
'use strict';
(function(){
  const boot = JSON.parse(document.getElementById('boot').textContent || '{}');
  const SECTIONS = boot.form_sections || [];
  var lastDash = null;
  function $(s,r=document){return r.querySelector(s);}
  function esc(t){var d=document.createElement('div');d.textContent=t==null?'':String(t);return d.innerHTML;}
  function num(n){return (Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});}
  function fmtUsd(n){
    var x=Number(n); if(!isFinite(x)) x=0;
    return x.toLocaleString(undefined,{maximumFractionDigits:0});
  }
  function fmtAprPct(n){
    var x=Number(n); if(!isFinite(x)) return '0';
    return String(Math.round(x));
  }
  function momScoreCell(mom){
    mom=mom||{};
    var v=mom.combined_score;
    if(v==null||v==='') v=mom.score;
    var tier=mom.tier?String(mom.tier):'';
    if(v==null||v===''||!isFinite(Number(v))) return esc(tier||'—');
    var s=(Math.round(Number(v)*10)/10).toString();
    return esc(s+(tier?' '+tier:''));
  }
  function hotMomentumCells(r){
    var apr=r.apr; if(apr==null||apr==='') apr=r.apr_pct;
    var tvl=r.tvl_usd;
    if(tvl==null||tvl===''){ tvl=r.liquidity_usd; if(tvl==null||tvl==='') tvl=r.tvl; }
    var vol=r.volume_24h_usd;
    if(vol==null||vol==='') vol=r.volume24h_usd||r.vol24;
    var sc=r.combined_score;
    if(sc==null||sc==='') sc=r.score||r.momentum_score;
    var pool=r.pool_id||r.id||'';
    var scTxt='—';
    if(sc!=null&&sc!==''&&isFinite(Number(sc))) scTxt=(Math.round(Number(sc)*10)/10).toString();
    return {apr:apr,tvl:tvl,vol:vol,scTxt:scTxt,pool:pool};
  }

  function fieldTip(f){
    var h=(f.help||'').trim(), l=(f.live_hint||'').trim();
    if(h && l) return h + '\n\nSuggested starting point: ' + l;
    if(h) return h;
    if(l) return 'Suggested starting point: ' + l;
    return '';
  }
  function appendSuggested(wrap, f){
    var s=(f.live_hint||'').trim();
    if(!s) return;
    var d=document.createElement('div');
    d.className='hint-line';
    d.textContent='Suggested: '+s;
    wrap.appendChild(d);
  }
  function appendFieldPop(wrap, f){
    var t=fieldTip(f);
    if(!t) return;
    var pop=document.createElement('div');
    pop.className='fw-pop';
    pop.textContent=t;
    wrap.appendChild(pop);
  }

  function displayFor(f, raw){
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
      if(sec.section_help||sec.section_rec){
        var st=[(sec.section_help||'').trim(),(sec.section_rec||'').trim()].filter(Boolean).join('\n\n');
        var hw=document.createElement('div'); hw.className='sec-hw';
        var sg=document.createElement('div'); sg.className='sg sg-h'; sg.textContent=sec.title;
        var sp=document.createElement('div'); sp.className='sec-pop fw-pop'; sp.textContent=st;
        hw.appendChild(sg); hw.appendChild(sp); root.appendChild(hw);
      } else {
        var sg0=document.createElement('div'); sg0.className='sg'; sg0.textContent=sec.title; root.appendChild(sg0);
      }
      if(sec.section_help||sec.section_rec){
        var sw=document.createElement('div'); sw.className='sec-blurb-wrap';
        var sb=document.createElement('div'); sb.className='sec-blurb';
        var p1=document.createElement('div'); p1.textContent=(sec.section_help||'').trim(); sb.appendChild(p1);
        if((sec.section_rec||'').trim()){
          var p2=document.createElement('div'); p2.className='sr'; p2.textContent='Try: '+(sec.section_rec||'').trim(); sb.appendChild(p2);
        }
        sw.appendChild(sb); root.appendChild(sw);
      }
      var fg=document.createElement('div'); fg.className='fg';
      for(var fi=0;fi<(sec.fields||[]).length;fi++){
        var f=sec.fields[fi]; var kk=f.key, ty=f.type;
        if(ty==='checkbox'){
          var wrap=document.createElement('div'); wrap.className='fw';
          var L=document.createElement('label'); L.className='lb h'; var inp=document.createElement('input');
          inp.type='checkbox'; inp.dataset.sk=kk; inp.checked=!!raw[kk];
          L.appendChild(inp); L.appendChild(document.createTextNode(' '+f.label));
          wrap.appendChild(L);
          appendSuggested(wrap, f);
          appendFieldPop(wrap, f);
          fg.appendChild(wrap); continue;
        }
        var wrap=document.createElement('div'); wrap.className='fw';
        var lab=document.createElement('label'); lab.className='lb';
        var cap=document.createElement('span'); cap.textContent=f.label; lab.appendChild(cap); var inp2;
        if(ty==='select'){
          inp2=document.createElement('select'); inp2.dataset.sk=kk;
          (f.options||[]).forEach(function(o){var o2=document.createElement('option');o2.value=o;o2.textContent=o;
            if(String(raw[kk])===String(o))o2.selected=true; inp2.appendChild(o2);});
        } else if(ty==='json_text'){
          inp2=document.createElement('textarea'); inp2.dataset.sk=kk; inp2.rows=2;
          inp2.value=displayFor(f, raw);
        } else if(ty==='lines'){
          inp2=document.createElement('textarea'); inp2.dataset.sk=kk; inp2.rows=3;
          inp2.value=displayFor(f, raw);
        } else if(ty==='csv'){
          inp2=document.createElement('input'); inp2.type='text'; inp2.dataset.sk=kk;
          inp2.value=displayFor(f, raw);
        } else {
          inp2=document.createElement('input'); inp2.type=(ty==='number'?'number':'text'); inp2.dataset.sk=kk;
          if(f.step) inp2.step=f.step; var dh=displayFor(f, raw); inp2.value=(dh!=='' && dh!==null && dh!==undefined)?dh:'';
        }
        lab.appendChild(inp2);
        wrap.appendChild(lab);
        appendSuggested(wrap, f);
        appendFieldPop(wrap, f);
        fg.appendChild(wrap);
      }
      root.appendChild(fg);
    }
  }

  function collect(){
    var patch={}, els=document.querySelectorAll('[data-sk]');
    for(var i=0;i<els.length;i++){
      var el=els[i], k=el.dataset.sk;
      if(k==='route_sources_json'){ patch.route_sources=JSON.parse(el.value.trim()||'[]'); continue; }
      if(k==='lp_range_width_candidates_json'){
        var arr=JSON.parse(el.value.trim()||'[]'); if(!Array.isArray(arr)) throw new Error('not array');
        patch.lp_range_width_candidates=arr.map(Number); continue;
      }
      if(k==='solana_rpc_urls_lines'){
        patch.solana_rpc_urls=el.value.split(/\r?\n/).map(function(s){return s.trim();}).filter(Boolean); continue;
      }
      if(k==='blocked_mints_lines'){
        patch.blocked_mints=el.value.split(/\r?\n/).map(function(s){return s.trim();}).filter(Boolean); continue;
      }
      if(k==='allowed_quote_symbols_csv'){
        patch.allowed_quote_symbols=el.value.split(',').map(function(s){return s.trim().toUpperCase();}).filter(Boolean); continue;
      }
      if(k==='blocked_token_symbols_csv'){
        patch.blocked_token_symbols=el.value.split(',').map(function(s){return s.trim().toUpperCase();}).filter(Boolean); continue;
      }
      if(el.type==='checkbox'){ patch[k]=el.checked; continue; }
      if(el.tagName==='SELECT'){ patch[k]=el.value; continue; }
      if(el.type==='number'){
        var tv=el.value.trim(); if(tv==='') continue; var n=Number(tv); if(isNaN(n)) throw new Error(k);
        patch[k]=n; continue;
      }
      patch[k]=el.value;
    }
    return patch;
  }

  async function gj(url,opt){
    var r=await fetch(url,opt), t=await r.text(), d;
    try{d=JSON.parse(t);}catch(e){throw new Error(t.slice(0,160));}
    if(!r.ok) throw new Error(d.error||t||r.status);
    return d;
  }

  function kpi(tip, cls, label, val){
    return '<div class="hb k '+cls+'"><div class="hb-pop fw-pop">'+esc(tip)+'</div><span class="x">'+esc(label)+'</span><span class="v">'+esc(String(val))+'</span></div>';
  }

  function activateTab(panelId){
    var panels=['tab-pos','tab-funnel','tab-raw'];
    var btns=['tabbtn-pos','tabbtn-funnel','tabbtn-raw'];
    for(var i=0;i<panels.length;i++){
      var on=(panels[i]===panelId);
      var p=document.getElementById(panels[i]);
      if(!p) continue;
      p.classList.toggle('active',on);
      p.setAttribute('aria-hidden', on?'false':'true');
      var b=document.getElementById(btns[i]);
      if(b) b.setAttribute('aria-selected', on?'true':'false');
    }
  }

  function renderWalletStrip(el, d){
    if(!el) return;
    var wc=d.wallet_capacity||{}, cap=wc.capacity||{}, bal=wc.balance||{};
    var sol=bal.sol!=null?Number(bal.sol):Number(cap.sol_balance||0);
    if(!isFinite(sol)) sol=0;
    var mx=cap.max_positions, psz=cap.position_size_sol, rs=cap.reserved_sol, av=cap.available_sol;
    var dry=!!(d.settings&&d.settings.dry_run);
    var w=wc.wallet;
    var tBal='Native SOL from RPC for the configured wallet (0 if no wallet / RPC miss).';
    var tMx='floor(available_sol / position_size_sol). In dry-run this does not hide rows in the tables below.';
    var tAv='Spendable SOL after reserve_sol.';
    var parts=[];
    if(dry) parts.push('Dry-run: <strong>max_positions=0</strong> is normal for an empty wallet — candidate + momentum tables stay the full filter pass until you fund SOL and turn off dry_run for live sizing.');
    if(!w) parts.push('No wallet configured — balances stay at 0. Add your keypair / <code>WALLET_ADDRESS</code> flow when you want live reads.');
    var note=parts.length?('<p class="muted" style="margin:.55rem 0 0">'+parts.join(' ')+'</p>'):'';
    el.innerHTML='<div class="kp">'+
      kpi(tBal,'', 'SOL (wallet)', sol.toFixed(4))+
      kpi(tMx,'', 'max_positions', mx==null?'—':String(mx))+
      kpi('SOL per slot.','', 'position_size_sol', psz==null?'—':String(psz))+
      kpi('Fee buffer.','', 'reserved_sol', rs==null?'—':String(rs))+
      kpi(tAv,'', 'available_sol', av==null?'—':(Number(av).toFixed(4)))+
      '</div>'+note;
  }

  function renderAlerts(el, d){
    if(!el) return;
    var rows=d.recent_alerts||[];
    if(!rows.length){ el.innerHTML='<p class="muted">No recent alerts in this <code>dashboard.json</code> snapshot.</p>'; return; }
    el.innerHTML='<div class="tbl-scroll"><table class="tb2"><thead><tr><th>Timestamp</th><th>Severity</th><th>Pair</th><th>Pool id</th><th>Action</th></tr></thead><tbody>'+
      rows.slice().reverse().map(function(a){
        return '<tr><td class="mono">'+esc(String(a.timestamp||a.at||''))+'</td><td>'+esc(String(a.severity||''))+'</td><td>'+esc(String(a.pair||''))+'</td><td class="mono">'+
          esc(String(a.pool_id||''))+'</td><td>'+esc(String(a.action||''))+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderRpcHealth(el, d){
    if(!el) return;
    var rows=d.rpc_health||[];
    if(!rows.length){
      el.innerHTML='<p class="muted">No RPC checks in this snapshot. Add <code>solana_rpc_urls</code> in settings and run the scanner with <code>--dashboard</code> so <code>rpc_health</code> fills.</p>';
      return;
    }
    el.innerHTML='<p class="muted">'+rows.length+' endpoint(s) — labeled table mirrors <code>rpc_health</code> in dashboard.json.</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>RPC URL (masked)</th><th>OK</th><th>Detail</th></tr></thead><tbody>'+
      rows.map(function(r,i){
        var ok=r.ok===true||r.ok==='true'?'yes':'no';
        var det=String(r.error||'');
        if(!det && r.response) try{ det=JSON.stringify(r.response).slice(0,160);}catch(e){ det='(response)'; }
        return '<tr><td>'+esc(String(r.index!=null?r.index:(i+1)))+'</td><td class="mono">'+esc(String(r.url||''))+'</td><td>'+esc(ok)+'</td><td class="mono">'+esc(det)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderRawJson(d){
    var pre=document.getElementById('rawjson');
    if(!pre) return;
    try{ pre.textContent=JSON.stringify(d,null,2); }catch(e){ pre.textContent=String(e); }
  }

  function renderModeBar(d){
    var bar=$('#mode-bar');
    if(!bar) return;
    var dry=!!(d.settings&&d.settings.dry_run);
    var sm=String((d.last_scan&&d.last_scan.scan_mode)||'');
    var demo=dry || sm.indexOf('dry')>=0 || sm==='trade_disabled_in_this_build';
    if(demo){
      bar.className='mode-bar mode-demo';
      bar.innerHTML='<span class="mode-tag">DEMO</span> Scanner snapshot only — no fills, no LP adds from this page. Tables are full pass lists from JSON.';
    } else {
      bar.className='mode-bar mode-live';
      bar.innerHTML='<span class="mode-tag">LIVE SETTINGS</span> dry_run is off in saved settings — custody and runner are on you; this UI still only reads dashboard JSON.';
    }
  }

  function renderFunnel(d){
    var ls=d.last_scan||{}, sc=ls.scanned_count||0, c=ls.candidate_count||0, rej=ls.rejected_count||0;
    var rate=(c+rej)>0?(100*c/(c+rej)):0;
    var dry=!!(d.settings&&d.settings.dry_run);
    $('#stamp').textContent=(dry?'demo':'live')+' · '+(d.generated_at||'?').replace('T',' ').slice(11,19)+'Z';
    var bd=Object.entries(ls.rejection_breakdown||{}).sort(function(a,b){return b[1]-a[1];});
    var mx=Math.max.apply(null,bd.map(function(x){return x[1];}).concat([0]))||1;
    var bars=bd.slice(0,18).map(function(kv){
      return '<div class="bar"><div title="'+esc(kv[0])+'">'+esc(kv[0])+'</div><div class="tr"><div class="fil" style="width:'+
        ((100*kv[1]/mx).toFixed(1))+'%"></div></div><div style="font-family:var(--mono);font-size:.75rem;color:var(--muted);text-align:right">'+kv[1]+'</div></div>';
    }).join('');
    if(!bars) bars='<p style="color:var(--muted);margin:.2rem 0">No breakdown yet.</p>';
    var hist=Object.entries(ls.rejection_reason_histogram||{}).slice(0,26);
    var ht=hist.length?('<div class="sg">Exact first reasons</div><table class="ta"><thead><tr><th class="c">#</th><th>reason</th></tr></thead><tbody>'+
      hist.map(function(kv){return '<tr><td class="c">'+kv[1]+'</td><td>'+esc(kv[0])+'</td></tr>';}).join('')+'</tbody></table>'):'';
    var diag=ls.scan_diagnosis||{};
    var nar=(diag.narrative_lines||[]).map(function(l){return '<li>'+esc(l)+'</li>';}).join('');
    var pr=(diag.setting_pressure||[]).map(function(p){
      return '<div><b>'+esc(p.setting_key||'')+'</b> — '+esc(p.direction||'')+' ('+esc(String(p.reject_share_pct))+'% · '+esc(p.category_driver||'')+')<br><small>'+
        esc(p.concrete_suggestion||p.rationale||'')+'</small></div>';
    }).join('');
    var tScan='Rows returned from Raydium list API this pass (before CSV export).';
    var tCand='Pools that passed liquidity, volume, APR, and downstream gates.';
    var tRej='Rejected rows; first reason string feeds the histogram.';
    var tRate='Pass share = candidates / scanned.';
    var tCat='Category counts from verdict classifier on first rejection reason.';
    $('#fu').innerHTML='<div class="kp">'+
      kpi(tScan,'', 'Scanned', sc)+
      kpi(tCand,'g','Candidates', c)+
      kpi(tRej,'r','Rejected', rej)+
      kpi(tRate,'','Pass share', rate.toFixed(1)+'%')+'</div>'+
      '<div class="sec-hw" style="margin-top:.5rem"><div class="sg sg-h">Reject categories</div><div class="sec-pop fw-pop">'+esc(tCat)+'</div></div>'+bars+ht+
      (nar?('<div class="sg">Narrative</div><ul class="z">'+nar+'</ul>'):'')+
      (pr?('<div class="sg">Suggested levers</div><div class="pr levers">'+pr+'</div>'):'');
  }

  function pairFromPool(p){
    if(p.pair) return p.pair;
    var a=p.mint_a_symbol||'', b=p.mint_b_symbol||'';
    if(a&&b) return a+'/'+b;
    return a||b||'';
  }

  function candidateRows(d){
    var ls=d.last_scan||{};
    var c=ls.candidates;
    if(c&&c.length) return c;
    return (d.open_positions||[]).map(function(o){
      return {id:o.pool_id,pair:o.pair,mint_a_symbol:'',mint_b_symbol:'',apr:o.apr,liquidity_usd:o.liquidity_usd,volume_24h_usd:o.volume_24h_usd,
        momentum:{score:o.momentum_score,tier:o.momentum_tier}};
    });
  }

  function renderCandidateTable(el, d){
    var pools=candidateRows(d);
    if(!pools.length){ el.innerHTML='<p class="muted">No candidates in this snapshot.</p>'; return; }
    var n=pools.length;
    el.innerHTML='<p class="muted">'+n+' row(s) — same list as <code>last_scan.candidates</code> in dashboard JSON (scroll inside box).</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL USD</th><th>Vol 24h</th><th>Momentum</th><th>Pool id</th></tr></thead><tbody>'+
      pools.map(function(p,i){
        var mom=p.momentum||{};
        return '<tr><td>'+(i+1)+'</td><td>'+esc(pairFromPool(p))+'</td><td>'+esc(fmtAprPct(p.apr))+'</td><td>'+esc(fmtUsd(p.liquidity_usd))+'</td><td>'+esc(fmtUsd(p.volume_24h_usd))+'</td><td>'+momScoreCell(mom)+'</td><td class="mono">'+esc(p.id||'')+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderMomentumTable(el, rows){
    rows=rows||[];
    if(!rows.length){ el.innerHTML='<p class="muted">No momentum leaderboard rows (enable momentum in settings).</p>'; return; }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — <code>momentum_hot_top</code> (columns match candidate pools: APR, TVL, vol, score, pool).</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL $</th><th>Vol24 $</th><th>Score (CMB)</th><th>Tier</th><th>Tags</th><th>Pool</th></tr></thead><tbody>'+
      rows.map(function(r,i){
        var H=hotMomentumCells(r);
        var tags=(r.sniff_tags||[]).slice(0,8).join(', ');
        return '<tr><td>'+(i+1)+'</td><td>'+esc(r.pair||'')+'</td><td>'+esc(fmtAprPct(H.apr))+'</td><td>'+esc(fmtUsd(H.tvl))+'</td><td>'+esc(fmtUsd(H.vol))+'</td><td>'+esc(H.scTxt)+'</td><td>'+esc(String(r.tier||''))+'</td><td>'+esc(tags)+'</td><td class="mono">'+esc(H.pool)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderOpenTable(el, rows, demo){
    rows=rows||[];
    var tag=demo?'demo watchlist (not on-chain)':'from dashboard open_positions';
    if(!rows.length){ el.innerHTML='<p class="muted">No open/watchlist rows. '+esc(tag)+'.</p>'; return; }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — '+esc(tag)+'.</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL</th><th>Vol24</th><th>Health</th><th>Mom</th><th>Pool id</th></tr></thead><tbody>'+
      rows.map(function(p,i){
        return '<tr><td>'+(i+1)+'</td><td>'+esc(p.pair||'')+'</td><td>'+esc(fmtAprPct(p.apr))+'</td><td>'+esc(fmtUsd(p.liquidity_usd))+'</td><td>'+esc(fmtUsd(p.volume_24h_usd))+'</td><td>'+esc(String(p.health||''))+'</td><td>'+
          esc(String(p.momentum_score!=null?p.momentum_score:'')+' '+String(p.momentum_tier||''))+'</td><td class="mono">'+esc(p.pool_id||'')+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderClosedTable(el, rows){
    rows=rows||[];
    if(!rows.length){
      el.innerHTML='<p class="muted">No closed positions in this JSON yet. When your executor writes <code>closed_positions</code> into the scan report / dashboard pipeline, they will list here.</p>';
      return;
    }
    el.innerHTML='<p class="muted">'+rows.length+' closed row(s).</p><div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Data</th></tr></thead><tbody>'+
      rows.map(function(r,i){return '<tr><td>'+(i+1)+'</td><td class="mono">'+esc(JSON.stringify(r))+'</td></tr>';}).join('')+'</tbody></table></div>';
  }

  function renderAll(d){
    lastDash=d;
    renderModeBar(d);
    renderFunnel(d);
    renderWalletStrip($('#wall'), d);
    var ls=d.last_scan||{};
    renderCandidateTable($('#cand'), d);
    renderMomentumTable($('#mom'), d.momentum_hot_top||[]);
    var demo=!!(d.settings&&d.settings.dry_run)||String(ls.scan_mode||'').indexOf('dry')>=0||ls.scan_mode==='trade_disabled_in_this_build';
    renderOpenTable($('#openp'), d.open_positions||[], demo);
    renderClosedTable($('#clop'), ls.closed_positions||[]);
    renderAlerts($('#alerts'), d);
    renderRpcHealth($('#rpc'), d);
    renderRawJson(d);
  }

  async function refresh(){
    var dash=await gj('/api/dashboard');
    $('#err').textContent='';
    renderAll(dash);
  }

  async function loadSettings(){
    var s=await gj('/api/settings'); mount(s);
  }

  function msg(t, ok){
    var e=$('#st'); e.textContent=t; e.className=ok?'o':(t?'e':'');
  }

  document.getElementById('reload').onclick=function(){msg(''); refresh().catch(function(e){msg(String(e),false);}); loadSettings().catch(function(e){msg(String(e),false);});};
  document.getElementById('save').onclick=function(){
    msg('Saving…',true);
    try{
      var body=JSON.stringify(collect());
      fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:body})
        .then(function(r){return r.text().then(function(t){return {r:r,t:t};});})
        .then(function(x){
          var d; try{d=JSON.parse(x.t);}catch(e){throw new Error(x.t.slice(0,200));}
          if(!x.r.ok) throw new Error(d.error||x.t);
          msg('Saved · next loop picks up if scanner uses --reload-config-each-scan',true);
        }).catch(function(e){msg(String(e),false);});
    }catch(e){msg(String(e),false);}
  };

  var timer=null;
  function arm(){
    clearInterval(timer);
    if(document.getElementById('auto').checked) timer=setInterval(function(){refresh().catch(function(){});},4000);
  }
  document.getElementById('auto').onchange=arm;

  document.getElementById('tabbtn-pos').onclick=function(){activateTab('tab-pos');};
  document.getElementById('tabbtn-funnel').onclick=function(){activateTab('tab-funnel');};
  document.getElementById('tabbtn-raw').onclick=function(){activateTab('tab-raw');};

  refresh().catch(function(e){$('#err').textContent=String(e);$('#fu').innerHTML='<p style="color:var(--no)">'+esc(String(e))+'</p>';});
  loadSettings().catch(function(e){msg(String(e),false);});
  arm();
})();
