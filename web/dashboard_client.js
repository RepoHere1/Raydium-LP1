
'use strict';
(function(){
  const boot = JSON.parse(document.getElementById('boot').textContent || '{}');
  const SECTIONS = boot.form_sections || [];
  const LP_STRATEGY_CARDS = boot.lp_strategy_cards || [];
  const LP_EXPERIMENT_LOOP = boot.lp_experiment_loop || null;
  var REJECT_LABELS = {
    hard_exit_red_line: 'hard_exit_min_tvl_usd (exit depth too shallow to sell to SOL)',
    tvl_below_threshold: 'TVL below your minimum',
    apr_below_threshold: 'APR below your minimum',
    volume_below_threshold: '24h volume below your minimum',
    price_impact_too_high: 'Sell price impact above your cap',
    no_sell_route: 'No sell route to allowed quotes',
    quote_symbol_not_allowed: 'Quote token not allowed',
    pool_not_verified: 'Pool verification failed',
    pool_age: 'Pool age outside window',
    lp_burn_too_low: 'LP burn too low',
    blocked_list: 'Blocked token/mint',
    missing_pool_id: 'Missing pool id',
    momentum_below_threshold: 'Momentum score too low',
    other: 'Other'
  };
  function rejectLabel(key){ return REJECT_LABELS[key] || String(key||'').replace(/_/g,' '); }
  var lastDash = null;
  var lastRuntime = null;
  var UI_MODE_KEY = 'raydium_lp1_ui_mode';

  function getStoredUiMode(){
    try{
      var m=sessionStorage.getItem(UI_MODE_KEY);
      if(m==='live'||m==='demo') return m;
    }catch(e){}
    return null;
  }
  function setStoredUiMode(m){
    try{ sessionStorage.setItem(UI_MODE_KEY, String(m||'demo').toLowerCase()); }catch(e){}
  }
  function $(s,r=document){return r.querySelector(s);}
  function esc(t){var d=document.createElement('div');d.textContent=t==null?'':String(t);return d.innerHTML;}
  function num(n){return (Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});}
  function fmtUsd(n){
    var x=Number(n); if(!isFinite(x)) x=0;
    return x.toLocaleString(undefined,{maximumFractionDigits:0});
  }
  function fmtFeesUsd(n){
    var x=Number(n);
    if(!isFinite(x)) return '—';
    return '$'+x.toLocaleString(undefined,{maximumFractionDigits:2,minimumFractionDigits:2});
  }
  function fmtAprPct(n){
    var x=Number(n); if(!isFinite(x)) return '0';
    return String(Math.round(x));
  }
  function poolIdWithProof(p){
    var pv=p&&p.pool_verification||{};
    var tag=String(pv.proof_tag||'').trim();
    var id=String((p&&(p.id||p.pool_id))||'');
    if(!tag) return id;
    return id+' ['+tag+']';
  }
  function poolIdCell(rawId, proofTag){
    var id=window.LP1Copy?LP1Copy.normalizePoolId(rawId):String(rawId||'');
    if(!id) return '<span class="muted">—</span>';
    if(window.LP1Copy) return LP1Copy.cellHtml(id,{proofTag:proofTag||''});
    return '<span class="mono">'+esc(id)+'</span>';
  }
  function poolIdCellFromPool(p){
    var pv=p&&p.pool_verification||{};
    return poolIdCell((p&&(p.id||p.pool_id))||'', pv.proof_tag||'');
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

  function renderExperimentLoop(parent){
    var loop=LP_EXPERIMENT_LOOP;
    if(!parent||!loop||!loop.steps) return;
    var html='<div class="lp-experiment-loop"><h3>'+esc(loop.title||'Experiment loop')+'</h3>';
    if(loop.subtitle) html+='<p class="loop-sub">'+esc(loop.subtitle)+'</p>';
    html+='<ol>';
    for(var i=0;i<loop.steps.length;i++){
      var s=loop.steps[i];
      html+='<li><strong>Step '+esc(String(s.n||i+1))+': '+esc(s.title||'')+'</strong> — '+esc(s.body||'')+'</li>';
    }
    html+='</ol>';
    if(loop.active_management) html+='<p class="loop-foot">'+esc(loop.active_management)+'</p>';
    html+='</div>';
    parent.insertAdjacentHTML('beforeend', html);
  }

  function renderStrategyCards(parent, raw){
    if(!parent||!LP_STRATEGY_CARDS.length) return;
    var active=String(raw.lp_active_strategy||'auto_volatility_pick');
    var grid=document.createElement('div');
    grid.className='lp-strategy-grid';
    grid.setAttribute('role','radiogroup');
    grid.setAttribute('aria-label','LP order entry style');
    LP_STRATEGY_CARDS.forEach(function(card){
      var id=String(card.id||'');
      var btn=document.createElement('button');
      btn.type='button';
      btn.className='lp-strategy-card'+(id===active?' active':'');
      btn.dataset.strategyId=id;
      btn.setAttribute('role','radio');
      btn.setAttribute('aria-checked', id===active?'true':'false');
      btn.innerHTML='<div class="st-band">'+esc(card.band_hint||card.short_label||'')+'</div>'+
        '<div class="st-title">'+esc(card.title||card.short_label||id)+'</div>'+
        '<div class="st-body">'+esc(card.summary||'')+'</div>'+
        (card.when_to_use?'<div class="st-when">When: '+esc(card.when_to_use)+'</div>':'');
      btn.onclick=function(){
        grid.querySelectorAll('.lp-strategy-card').forEach(function(el){
          el.classList.remove('active');
          el.setAttribute('aria-checked','false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-checked','true');
        var hid=document.querySelector('[data-sk="lp_active_strategy"]');
        if(hid) hid.value=id;
        var blurb=document.getElementById('lp-strategy-blurb');
        if(blurb) blurb.textContent=(card.title||id)+': '+(card.summary||'');
      };
      grid.appendChild(btn);
    });
    parent.appendChild(grid);
    var hidden=document.createElement('input');
    hidden.type='hidden';
    hidden.dataset.sk='lp_active_strategy';
    hidden.value=active;
    parent.appendChild(hidden);
    var blurb=document.createElement('div');
    blurb.id='lp-strategy-blurb';
    blurb.className='muted';
    blurb.style.cssText='margin:0 0 .75rem;font-size:.82rem;max-width:56rem';
    var cur=null;
    for(var j=0;j<LP_STRATEGY_CARDS.length;j++){ if(LP_STRATEGY_CARDS[j].id===active){ cur=LP_STRATEGY_CARDS[j]; break; } }
    blurb.textContent=cur ? ((cur.title||'')+': '+(cur.summary||'')) : '';
    parent.insertBefore(blurb, grid);
  }

  function mountSectionFields(sec, fg, raw){
    for(var fi=0;fi<(sec.fields||[]).length;fi++){
      var f=sec.fields[fi]; var kk=f.key, ty=f.type;
      if(ty==='strategy_picker') continue;
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
  }

  function mount(raw){
    var rootStd=$('#fo'); var rootLp=$('#fo-lp');
    if(rootStd) rootStd.innerHTML='';
    if(rootLp) rootLp.innerHTML='';
    for(var si=0;si<SECTIONS.length;si++){
      var sec=SECTIONS[si];
      var isLp=sec.section_id==='lp_order_entry';
      var root=isLp?(rootLp||rootStd):rootStd;
      if(!root) continue;
      if(sec.section_help||sec.section_rec){
        var st=[(sec.section_help||'').trim(),(sec.section_rec||'').trim()].filter(Boolean).join('\n\n');
        var hw=document.createElement('div'); hw.className='sec-hw';
        var sg=document.createElement('div'); sg.className='sg sg-h'; sg.textContent=sec.title;
        var sp=document.createElement('div'); sp.className='sec-pop fw-pop'; sp.textContent=st;
        hw.appendChild(sg); hw.appendChild(sp); root.appendChild(hw);
      } else if(!isLp) {
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
      if(isLp){
        renderExperimentLoop(root);
        renderStrategyCards(root, raw);
        var adv=document.createElement('div');
        adv.className='lp-advanced-label';
        adv.textContent='Fine tuning (band %, paper wallet, optional legs)';
        root.appendChild(adv);
      }
      var fg=document.createElement('div'); fg.className='fg';
      mountSectionFields(sec, fg, raw);
      root.appendChild(fg);
    }
  }

  function jumpToLpEntry(){
    activateTab('tab-funnel');
    var el=document.getElementById('lp-order-entry');
    if(el){
      if(location.hash!=='#lp-order-entry') location.hash='lp-order-entry';
      el.scrollIntoView({behavior:'smooth',block:'start'});
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

  function walletConfigured(w){
    return !!(w && (w.configured || w.address));
  }
  function walletAddrLine(wc){
    var w=(wc&&wc.wallet)||{};
    if(!walletConfigured(w)) return '<p class="muted" style="margin:.45rem 0 0">Wallet not configured — import via <code>scripts/import_wallet.ps1</code>.</p>';
    var addr=String(w.address||'?');
    var short=addr.length>14?addr.slice(0,6)+'…'+addr.slice(-4):addr;
    return '<p class="muted" style="margin:.45rem 0 0">Wallet <span class="mono" title="'+esc(addr)+'">'+esc(short)+'</span> · '+esc(String(w.source||''))+'</p>';
  }

  function renderWalletCapacity(el, wc, zone){
    if(!el) return;
    wc=wc||{};
    var cap=wc.capacity||{}, bal=wc.balance||{};
    var sol=bal.sol!=null?Number(bal.sol):Number(cap.sol_balance||0);
    if(!isFinite(sol)) sol=0;
    var mx=cap.max_positions;
    if(zone==='demo' && cap.simulated_slots!=null) mx=cap.simulated_slots;
    var psz=cap.position_size_sol, rs=cap.reserved_sol, av=cap.available_sol;
    var tBal=zone==='demo'?'Dry-run paper SOL (not on-chain).':'Native SOL from RPC for your imported wallet.';
    var tMx=zone==='demo'
      ? 'Pools that passed filters this scan (simulated slots — not wallet-capped).'
      : 'Real slots from funded SOL: floor(available / position_size_sol).';
    var note=(cap.note||'').trim();
    el.innerHTML='<div class="kp">'+
      kpi(tBal,'', 'SOL (wallet)', sol.toFixed(4))+
      kpi(tMx,'', zone==='demo'?'simulated_slots':'max_positions', mx==null?'—':String(mx))+
      kpi('SOL per slot.','', 'position_size_sol', psz==null?'—':String(psz))+
      kpi('Fee buffer.','', 'reserved_sol', rs==null?'—':String(rs))+
      kpi('Spendable after reserve.','', 'available_sol', av==null?'—':(Number(av).toFixed(4)))+
      kpi('Estimated fees on open LPs (paper model from 24h vol × share).','', 'fees collected', fmtFeesUsd(cap.fees_collected_usd))+
      '</div>'+walletAddrLine(wc)+
      (note?('<p class="muted" style="margin:.35rem 0 0">'+esc(note)+'</p>'):'');
  }

  function renderTradesTable(el, rows, zone){
    if(!el) return;
    rows=rows||[];
    var tag=zone==='demo'
      ? 'Paper trades — same live rows LIVE would open before signing (<code>demo_simulated_trades</code>).'
      : 'On-chain / tracked opens (<code>live_open_positions</code> or <code>active_positions.json</code>).';
    if(!rows.length){
      el.innerHTML='<p class="muted">No '+esc(zone)+' trades in this snapshot. '+esc(tag)+'</p>';
      return;
    }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — '+tag+'</p>'+
      '<div class="tbl-scroll wide-trades"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>Size</th><th>TVL</th><th>Action</th><th>LP style</th><th>NFT mint</th><th>Pool id</th><th>Tx</th></tr></thead><tbody>'+
      rows.map(function(p,i){
        var ix=p.index!=null?p.index:(i+1);
        var act=p.action||p.status||'';
        var strat=p.strategy_name||p.strategy_id||'';
        if(strat) act=act+(act?' · ':'')+strat;
        var lpStyle=p.lp_style_label||p.lp_placement||'—';
        var size=p.value_usd!=null?('$'+Number(p.value_usd).toFixed(2)):(
          p.input_amount_sol!=null?(Number(p.input_amount_sol).toFixed(4)+' SOL'):'—');
        var tx=p.tx||'';
        var txCell=tx?('<a href="https://solscan.io/tx/'+encodeURIComponent(tx)+'" target="_blank" rel="noopener">'+esc(tx.slice(0,8))+'…</a>'):'—';
        var oor=p.in_range_at_open===false||p.out_of_range_at_open?' <span class="muted">(OOR@open)</span>':'';
        return '<tr><td>'+esc(String(ix))+'</td><td>'+esc(p.pair||'')+'</td><td>'+esc(fmtAprPct(p.apr))+'</td><td>'+esc(size)+'</td><td>'+esc(fmtUsd(p.liquidity_usd))+'</td><td>'+
          esc(String(act))+'</td><td title="'+esc(p.lp_style_key||'')+'">'+esc(lpStyle)+oor+'</td><td class="mono">'+esc((p.position_nft_mint||'').slice(0,12))+(p.position_nft_mint?'…':'')+'</td><td>'+poolIdCell(p.pool_id||p.id)+'</td><td class="mono">'+txCell+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderAlerts(el, d){
    if(!el) return;
    var rows=d.recent_alerts||[];
    if(!rows.length){ el.innerHTML='<p class="muted">No recent alerts in this <code>dashboard.json</code> snapshot.</p>'; return; }
    el.innerHTML='<div class="tbl-scroll"><table class="tb2"><thead><tr><th>Timestamp</th><th>Severity</th><th>Pair</th><th>Pool id</th><th>Action</th></tr></thead><tbody>'+
      rows.slice().reverse().map(function(a){
        return '<tr><td class="mono">'+esc(String(a.timestamp||a.at||''))+'</td><td>'+esc(String(a.severity||''))+'</td><td>'+esc(String(a.pair||''))+'</td><td class="mono">'+
          poolIdCell(a.pool_id||'')+'</td><td>'+esc(String(a.action||''))+'</td></tr>';
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

  function effectiveMode(d){
    var stored=getStoredUiMode();
    if(stored) return stored;
    if(lastRuntime&&lastRuntime.mode) return String(lastRuntime.mode).toLowerCase();
    if(d&&d.settings&&d.settings.mode) return String(d.settings.mode).toLowerCase();
    if(d&&d.settings&&d.settings.dry_run!==undefined) return d.settings.dry_run?'demo':'live';
    return 'demo';
  }

  function resolveUiMode(d){
    return effectiveMode(d);
  }

  function applyViewMode(mode){
    if(window.RaydiumMode){ window.RaydiumMode.setStoredUiMode(mode); window.RaydiumMode.applyViewMode(mode); return; }
    var m=(mode||'demo').toLowerCase();
    document.body.classList.remove('view-live','view-demo');
    document.body.classList.add(m==='live'?'view-live':'view-demo');
    updateModeStatus(m);
    updateStampMode(m);
  }

  function updateStampMode(mode){
    var el=$('#stamp');
    if(!el) return;
    var m=String(mode||'demo').toLowerCase();
    var parts=String(el.textContent||'').split(' · ');
    var time=parts.length>1?parts.slice(1).join(' · '):'';
    el.textContent=m+(time?(' · '+time):'');
    el.classList.remove('stamp-demo','stamp-live');
    el.classList.add(m==='live'?'stamp-live':'stamp-demo');
  }

  function updateModeStatus(mode, w){
    var el=$('#mode-status-text');
    if(!el) return;
    var m=(mode||'demo').toLowerCase();
    var demo=m!=='live';
    var wallet='';
    w=w||{};
    if(w.configured){
      var addr=String(w.address||'?');
      var short=addr.length>12?addr.slice(0,4)+'…'+addr.slice(-4):addr;
      wallet=' · wallet '+short;
    } else if(w.address===undefined && lastRuntime&&lastRuntime.wallet) {
      w=lastRuntime.wallet;
      if(w.configured){
        var a2=String(w.address||'?');
        wallet=' · wallet '+(a2.length>12?a2.slice(0,4)+'…'+a2.slice(-4):a2);
      }
    }
    el.textContent=demo
      ? ('DRY_RUN — live Raydium + RPC; on-chain spends blocked'+wallet)
      : ('LIVE armed — runners may sign; dashboard read-only'+wallet);
  }

  async function setTradingMode(next){
    var m=String(next||'demo').toLowerCase();
    if(m==='live'){
      var typed=window.prompt('Type LIVE (all caps) to enable real on-chain spends:');
      if(typed!=='LIVE'){ msg('Live mode not armed (confirmation cancelled).', false); return null; }
    }
    setStoredUiMode(m);
    applyViewMode(m);
    topMsg('Switching to '+m.toUpperCase()+'…', false, true);

    var body={mode:m};
    if(m==='live') body.confirm='LIVE';
    var data=null;
    try{
      data=await gj('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    }catch(e1){
      try{
        var patch={mode:m,dry_run:m!=='live'};
        if(m==='live') patch.confirm='LIVE';
        data=await gj('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
      }catch(e2){
        topMsg('UI is '+m.toUpperCase()+'; server sync failed: '+String(e1.message||e1), false);
        msg('Mode UI set to '+m.toUpperCase()+' but API failed — restart dashboard (.\scripts\restart_dashboard.ps1)', false);
        return null;
      }
    }
    lastRuntime=Object.assign({}, lastRuntime||{}, data);
    var confirmed=(data.mode||m).toLowerCase();
    setStoredUiMode(confirmed);
    applyViewMode(confirmed);
    updateModeStatus(confirmed, data.wallet);
    topMsg('Synced '+confirmed.toUpperCase(), true);
    msg('Mode synced: '+confirmed.toUpperCase(), true);
    return data;
  }

  function getLpSelectionMode(d){
    var s=(d&&d.settings)||{};
    var ls=d&&d.lp_selection;
    if(ls&&ls.lp_selection_mode) return String(ls.lp_selection_mode).toLowerCase();
    return String(s.lp_selection_mode||'apr').toLowerCase();
  }

  function applyLpPickUi(mode){
    mode=(mode||'apr').toLowerCase()==='momentum'?'momentum':'apr';
    var apr=document.getElementById('btn-lp-apr');
    var mom=document.getElementById('btn-lp-mom');
    if(apr){
      apr.classList.toggle('active',mode==='apr');
      apr.setAttribute('aria-pressed',mode==='apr'?'true':'false');
    }
    if(mom){
      mom.classList.toggle('active',mode==='momentum');
      mom.setAttribute('aria-pressed',mode==='momentum'?'true':'false');
    }
  }

  function setLpSelectionMode(mode){
    mode=(mode||'apr').toLowerCase()==='momentum'?'momentum':'apr';
    applyLpPickUi(mode);
    var patch={
      lp_selection_mode:mode,
      sort_candidates_by_momentum:mode==='momentum',
      momentum_enabled:true
    };
    if(mode==='apr'){
      patch.pool_sort_field='apr24h';
      patch.sort_type='desc';
    }
    topMsg('LP pick: '+(mode==='momentum'?'MoM HOT':'APR')+'…', false, true);
    return gj('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)})
      .then(function(){
        topMsg('LP pick → '+(mode==='momentum'?'MoM HOT (tier=hot)':'APR'), true);
        msg('Saved. Re-run scan so shortlist order matches.', true);
        return refresh();
      })
      .catch(function(e){
        topMsg(String(e), false);
        msg(String(e), false);
      });
  }

  function wireLpPickButtons(){
    var apr=document.getElementById('btn-lp-apr');
    var mom=document.getElementById('btn-lp-mom');
    if(apr) apr.onclick=function(){ setLpSelectionMode('apr'); };
    if(mom) mom.onclick=function(){ setLpSelectionMode('momentum'); };
  }

  function renderModeBar(d){
    var mode=resolveUiMode(d);
    applyViewMode(mode);
    updateModeStatus(mode, lastRuntime&&lastRuntime.wallet);
    applyLpPickUi(getLpSelectionMode(d));
    var ls=d&&d.lp_selection;
    if(ls&&ls.top_pick_error){
      msg('LP pick: '+ls.top_pick_error, false);
    }
  }

  function renderFunnel(d){
    var ls=d.last_scan||{}, sc=ls.scanned_count||0, c=ls.candidate_count||0, rej=ls.rejected_count||0;
    var rate=(c+rej)>0?(100*c/(c+rej)):0;
    var stamp=$('#stamp');
    if(stamp){
      stamp.textContent=(d.generated_at||'?').replace('T',' ').slice(11,19)+'Z';
    }
    var bd=Object.entries(ls.rejection_breakdown||{}).sort(function(a,b){return b[1]-a[1];});
    var mx=Math.max.apply(null,bd.map(function(x){return x[1];}).concat([0]))||1;
    var bars=bd.slice(0,18).map(function(kv){
      var lab=rejectLabel(kv[0]);
      return '<div class="bar"><div title="'+esc(kv[0])+'">'+esc(lab)+'</div><div class="tr"><div class="fil" style="width:'+
        ((100*kv[1]/mx).toFixed(1))+'%"></div></div><div style="font-family:var(--mono);font-size:.75rem;color:#334155;text-align:right">'+kv[1]+'</div></div>';
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
      (nar?('<div class="sg sg-funnel-narrative">What this means</div><ul class="z funnel-narrative">'+nar+'</ul>'):'')+
      (pr?('<div class="sg">Suggested levers</div><div class="pr levers">'+pr+'</div>'):'');
  }

  function pairFromPool(p){
    if(p.pair) return p.pair;
    var a=p.mint_a_symbol||'', b=p.mint_b_symbol||'';
    if(a&&b) return a+'/'+b;
    return a||b||'';
  }

  function poolApr(p){ return Number(p.apr!=null?p.apr:p.apr_pct)||0; }

  function isMomentumHot(p, settings){
    settings=settings||{};
    var mom=p.momentum||{};
    var tier=String(mom.tier||p.momentum_tier||'').toLowerCase();
    if(tier==='hot'||tier==='enter_bias') return true;
    var minScore=Number(settings.momentum_hot_min_combined_score!=null?settings.momentum_hot_min_combined_score:72);
    var minApr=Number(settings.momentum_hot_min_apr!=null?settings.momentum_hot_min_apr:200);
    var sc=mom.combined_score!=null?mom.combined_score:mom.score;
    if(sc!=null&&Number(sc)>=minScore&&poolApr(p)>=minApr) return true;
    return false;
  }

  function sortPoolsByMomentumDesc(pools){
    return pools.slice().sort(function(a,b){
      var ma=a.momentum||{}, mb=b.momentum||{};
      var sa=Number(ma.combined_score!=null?ma.combined_score:ma.score)||0;
      var sb=Number(mb.combined_score!=null?mb.combined_score:mb.score)||0;
      return sb-sa;
    });
  }

  function sortPoolsByAprDesc(pools){
    return pools.slice().sort(function(a,b){ return poolApr(b)-poolApr(a); });
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

  function sortPoolsForPick(pools, d){
    var mode=getLpSelectionMode(d);
    if(mode==='momentum'){
      return pools.slice().sort(function(a,b){
        var ma=a.momentum||{}, mb=b.momentum||{};
        var sa=Number(ma.combined_score!=null?ma.combined_score:ma.score)||0;
        var sb=Number(mb.combined_score!=null?mb.combined_score:mb.score)||0;
        return sb-sa;
      });
    }
    return sortPoolsByAprDesc(pools);
  }

  function renderCandidateTable(el, d){
    var pools=sortPoolsForPick(candidateRows(d), d);
    var ls=d.last_scan||{};
    var settings=(d&&d.settings)||{};
    if(!pools.length){ el.innerHTML='<p class="muted">No candidates in this snapshot.</p>'; return; }
    var n=pools.length;
    var pre=ls.candidate_count_pre_capacity!=null?ls.candidate_count_pre_capacity:n;
    var trunc=Number(ls.candidates_truncated||0);
    var exec=ls.candidate_count_executable;
    var sortLbl=getLpSelectionMode(d)==='momentum'?'momentum score (LIVE picks tier=HOT)':'APR high→low';
    var capNote=trunc>0
      ?(' Wallet LIVE cap hides '+trunc+' from execution (max_positions); table shows all '+n+' filter-pass pools.')
      :'';
    el.innerHTML='<p class="muted">'+n+' row(s) — sorted by '+esc(sortLbl)+'. Green = HOT (score≥'+
      esc(String(settings.momentum_hot_min_combined_score!=null?settings.momentum_hot_min_combined_score:72))+
      ', APR≥'+esc(String(settings.momentum_hot_min_apr!=null?settings.momentum_hot_min_apr:200))+
      '). Row #1 = default LIVE target.'+esc(capNote)+' Scroll inside table if needed.</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL USD</th><th>Vol 24h</th><th>Momentum</th><th>Pool id</th></tr></thead><tbody>'+
      pools.map(function(p,i){
        var mom=p.momentum||{};
        var hot=isMomentumHot(p, settings);
        return '<tr'+(hot?' class="row-mom-hot"':'')+'><td>'+(i+1)+'</td><td>'+esc(pairFromPool(p))+'</td><td>'+esc(fmtAprPct(p.apr))+'</td><td>'+esc(fmtUsd(p.liquidity_usd))+'</td><td>'+esc(fmtUsd(p.volume_24h_usd))+'</td><td>'+momScoreCell(mom)+'</td><td>'+poolIdCellFromPool(p)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderMomentumTable(el, rows){
    rows=sortPoolsByMomentumDesc(rows||[]);
    if(!rows.length){ el.innerHTML='<p class="muted">No momentum leaderboard rows (enable momentum in settings).</p>'; return; }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — <code>momentum_hot_top</code> (columns match candidate pools: APR, TVL, vol, score, pool).</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL $</th><th>Vol24 $</th><th>Score (CMB)</th><th>Tier</th><th>Tags</th><th>Pool</th></tr></thead><tbody>'+
      rows.map(function(r,i){
        var H=hotMomentumCells(r);
        var tags=(r.sniff_tags||[]).slice(0,8).join(', ');
        return '<tr><td>'+(i+1)+'</td><td>'+esc(r.pair||'')+'</td><td>'+esc(fmtAprPct(H.apr))+'</td><td>'+esc(fmtUsd(H.tvl))+'</td><td>'+esc(fmtUsd(H.vol))+'</td><td>'+esc(H.scTxt)+'</td><td>'+esc(String(r.tier||''))+'</td><td>'+esc(tags)+'</td><td>'+poolIdCell(H.pool)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  var ANOM_DISPLAY_ROWS = 30;
  var autoRefreshPaused = 0;

  function setAutoRefreshPaused(on){
    if(on){
      autoRefreshPaused++;
      clearInterval(timer);
    }else{
      autoRefreshPaused = Math.max(0, autoRefreshPaused - 1);
      if(!autoRefreshPaused) arm();
    }
  }

  function wireAnomaliesFeedPause(){
    var root=document.getElementById('anom');
    if(!root||root._anomPauseWired) return;
    root._anomPauseWired=true;
    root.addEventListener('mouseenter', function(){
      setAutoRefreshPaused(true);
      root.classList.add('anom-hover-pause');
    });
    root.addEventListener('mouseleave', function(){
      root.classList.remove('anom-hover-pause');
      setAutoRefreshPaused(false);
    });
  }

  function renderCashAnomaliesTable(el, block, settings){
    block=block||{};
    settings=settings||{};
    if(block.enabled===false){
      el.innerHTML='<p class="muted">ANOMALIES (CASH) disabled — set <code>cash_anomaly_enabled</code> true in settings.</p>';
      return;
    }
    var rows=(block.rows||[]).slice(0, ANOM_DISPLAY_ROWS);
    if(!rows.length){
      var floor=block.exit_floor_usd!=null?block.exit_floor_usd:'?';
      var minFee=block.min_fee_24h_usd!=null?block.min_fee_24h_usd:'?';
      el.innerHTML='<p class="muted">No exit-safe low-APR / high-cash rows this scan (probed '+
        esc(String(block.probed_count||0))+' pools with TVL≥'+esc(String(floor))+' USD, fee24≥'+
        esc(String(minFee))+' USD). Widen <code>pages</code> or lower <code>cash_anomaly_min_fee_usd</code>.</p>';
      return;
    }
    var maxApr=block.max_reported_apr!=null?block.max_reported_apr:150;
    var capNote=(block.rows||[]).length>ANOM_DISPLAY_ROWS?' (showing top '+ANOM_DISPLAY_ROWS+')':'';
    el.innerHTML='<p class="muted">'+rows.length+' anomaly row(s)'+capNote+' — exit TVL floor '+esc(String(block.exit_floor_usd||'?'))+
      ' USD · fee24≥'+esc(String(block.min_fee_24h_usd||'?'))+' · low-APR ceiling '+esc(String(maxApr))+
      '%. Hover this panel to pause auto-refresh while clicking links.</p>'+
      '<div class="tbl-scroll anom-tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL $</th><th>Vol24 $</th><th>CASH 24h</th><th>Impl APR</th><th>Gap</th><th>Tags</th><th>Exit</th><th>Pool</th></tr></thead><tbody>'+
      rows.map(function(r,i){
        var tags=(r.anomaly_tags||[]).slice(0,4).join(', ');
        var exitTxt=r.sell_route_ok===true?'route ok':(r.sell_route_ok===false?'route?':'—');
        var cand=r.in_candidates?' cand':'';
        return '<tr class="row-cash-anom"><td>'+(i+1)+'</td><td>'+esc(r.pair||'')+'</td><td>'+
          esc(fmtAprPct(r.apr))+'</td><td>'+esc(fmtUsd(r.tvl_usd))+'</td><td>'+esc(fmtUsd(r.volume_24h_usd))+'</td><td><b>'+
          esc(fmtFeesUsd(r.cash_24h_usd))+'</b></td><td>'+esc(fmtAprPct(r.implied_apr_pct))+'</td><td>'+
          esc(r.apr_gap_pct!=null?((Number(r.apr_gap_pct)>=0?'+':'')+Number(r.apr_gap_pct).toFixed(1)+'%'):'—')+'</td><td>'+
          esc(tags+cand)+'</td><td>'+esc(exitTxt)+'</td><td>'+poolIdCell(r.pool_id)+'</td></tr>';
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
          esc(String(p.momentum_score!=null?p.momentum_score:'')+' '+String(p.momentum_tier||''))+'</td><td>'+poolIdCell(p.pool_id||p.id)+'</td></tr>';
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

  function wireStrategyPicker(catalog){
    if(LP_STRATEGY_CARDS.length) return;
    var sel=document.querySelector('[data-sk="lp_active_strategy"]');
    if(!sel||sel.type==='hidden') return;
    var hint=document.getElementById('lp-strategy-blurb');
    if(!hint) return;
    function show(){
      var id=sel.value;
      var item=null;
      for(var i=0;i<(catalog||[]).length;i++){ if(catalog[i].id===id){ item=catalog[i]; break; } }
      hint.textContent=item ? (item.official_name+': '+item.description) : '';
    }
    sel.onchange=show;
    show();
  }

  function renderLiveStyleStats(el, report){
    if(!el) return;
    report=report||{};
    if(report.error){
      el.innerHTML='<p class="muted">LP style stats: '+esc(report.error)+'</p>';
      return;
    }
    var groups=report.style_groups||[];
    var rec=report.recommendation||'';
    if(!groups.length){
      el.innerHTML='<p class="muted"><strong>LP style experiment</strong> — opens are tagged from <code>lp_active_strategy</code> in settings. No LIVE rows yet.</p>';
      return;
    }
    el.innerHTML='<p class="muted"><strong>LP style experiment</strong> — grouped by how each position was opened. '+esc(rec)+'</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>LP style</th><th>Opens</th><th>Avg APR@open</th><th>In-range@open</th><th>OOR@open</th><th>Fees USD</th></tr></thead><tbody>'+
      groups.map(function(g){
        return '<tr><td title="'+esc(g.lp_style_key||'')+'">'+esc(g.lp_style_label||'')+'</td><td>'+esc(String(g.count))+'</td><td>'+
          esc(g.avg_apr_at_open!=null?String(g.avg_apr_at_open):'—')+'</td><td>'+esc(String(g.in_range_at_open||0))+'</td><td>'+
          esc(String(g.out_of_range_at_open||0))+'</td><td>'+esc(fmtFeesUsd(g.total_fees_usd))+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderAll(d){
    lastDash=d;
    if(d.lp_strategy_catalog) wireStrategyPicker(d.lp_strategy_catalog);
    renderModeBar(d);
    renderFunnel(d);
    renderWalletCapacity($('#wall-live'), d.live_wallet_capacity||d.wallet_capacity, 'live');
    renderWalletCapacity($('#wall-demo'), d.demo_wallet_capacity||d.wallet_capacity, 'demo');
    renderTradesTable($('#live-trades'), d.live_open_positions||[], 'live');
    renderLiveStyleStats($('#live-style-stats'), d.live_lp_style_report);
    var demoFeed=d.demo_simulated_trades||[];
    if(!demoFeed.length && (d.demo_open_positions||[]).length) demoFeed=d.demo_open_positions;
    renderTradesTable($('#demo-trades'), demoFeed, 'demo');
    var ls=d.last_scan||{};
    renderCandidateTable($('#cand'), d);
    renderMomentumTable($('#mom'), d.momentum_hot_top||[]);
    renderCashAnomaliesTable($('#anom-body')||$('#anom'), d.cash_anomalies||{}, d.settings||{});
    renderClosedTable($('#clop'), ls.closed_positions||[]);
    renderAlerts($('#alerts'), d);
    renderRpcHealth($('#rpc'), d);
    renderRawJson(d);
  }

  var lastTunePlan=null;
  var lastScanStatus=null;
  var apiHasScanRoute=null;

  function scanStatusFromTune(plan){
    return (plan&&plan.scan_status)||lastScanStatus||{running:false};
  }

  function fetchScanStatus(){
    if(apiHasScanRoute===true){
      return gj('/api/scan/status').then(function(st){
        lastScanStatus=st;
        return st;
      });
    }
    return Promise.resolve(scanStatusFromTune(lastTunePlan));
  }

  function checkDashboardApi(){
    return gj('/health').then(function(h){
      var feats=h.api_features||[];
      apiHasScanRoute=feats.indexOf('scan_status')>=0;
      if(!apiHasScanRoute&&h.api_version==null){
        apiHasScanRoute=false;
      }
      return h;
    }).catch(function(){
      apiHasScanRoute=false;
      return null;
    });
  }

  function renderTunePanel(plan){
    var el=$('#tune-panel');
    if(!el) return;
    plan=plan||{};
    lastTunePlan=plan;
    if(plan.scan_status) lastScanStatus=plan.scan_status;
    if(plan.error){
      el.innerHTML='<p class="muted" style="color:var(--no)">'+esc(plan.error)+'</p>';
      return;
    }
    var lr=plan.live_readiness||{};
    var ready=!!lr.ready_to_sign;
    var kpHint='';
    if(lr.keypair_path_set && !lr.keypair_file_exists){
      kpHint='<p class="tune-meta" style="color:var(--no)">Keypair missing: <code>'+esc(lr.keypair_path_resolved||lr.keypair_path||'?')+
        '</code> — run <code>.\\scripts\\import_wallet.ps1 -KeypairPath C:\\path\\to\\id.json</code></p>';
    }
    var blockers=(lr.blockers||[]).map(function(b){return '<li>'+esc(b)+'</li>';}).join('');
    var sum=plan.scan_summary||{};
    var head='<p class="muted">Scanned <b>'+esc(String(sum.scanned||'?'))+'</b> · candidates <b>'+esc(String(sum.candidates||'?'))+
      '</b> · rejected <b>'+esc(String(sum.rejected||'?'))+'</b></p>'+
      '<p><span class="'+(ready?'live-ready-ok':'live-ready-no')+'">'+(ready?'LIVE ready to sign':'LIVE blocked')+'</span>'+
      (blockers?('<ul style="margin:.35rem 0;padding-left:1.2rem;font-size:.82rem">'+blockers+'</ul>'):'')+
      kpHint+
      '</p>'+
      '<div class="tune-actions">'+
      '<button type="button" id="scan-run-now" class="p">Run scan now</button>'+
      '<span id="scan-run-status" class="tune-meta"></span>'+
      '<a href="/api/scan_console" target="_blank" rel="noopener" class="tune-meta">Scan log</a>'+
      '<button type="button" id="tune-apply-sel" class="p">Apply checked</button>'+
      '<button type="button" id="tune-apply-all">Apply all with patches</button>'+
      '<button type="button" id="live-open-top" class="p" style="margin-left:auto">Open top CLMM (LIVE)</button>'+
      '<span class="tune-meta" id="lp-pick-hint"></span>'+
      '</div>';
    var items=plan.items||[];
    if(!items.length){
      el.innerHTML=head+'<p class="muted">No tune items — run a scan with <code>--write-reports</code> first.</p>';
      wireTuneButtons();
      return;
    }
    el.innerHTML=head+items.map(function(it){
      var patch=it.settings_patch||{};
      var patchKeys=Object.keys(patch);
      var patchTxt=patchKeys.length?('<div class="tune-meta mono">'+esc(patchKeys.map(function(k){return k+'='+JSON.stringify(patch[k]);}).join(', '))+'</div>'):'';
      var dis=!patchKeys.length?' disabled':'';
      var chk=(it.default_checked===true && patchKeys.length)?' checked':'';
      if(it.kind==='bundle' && patchKeys.length) chk=' checked';
      if(it.kind==='info') chk='';
      return '<div class="tune-item"><label><input type="checkbox" class="tune-chk" data-tid="'+esc(it.id)+'"'+chk+dis+'/>'+
        '<span><strong>'+esc(it.title||'')+'</strong> <span class="risk">'+esc(it.risk||'')+'</span><br/>'+
        esc(it.detail||'')+patchTxt+'</span></label></div>';
    }).join('');
    wireTuneButtons();
    var hint=document.getElementById('lp-pick-hint');
    if(hint&&lastDash&&lastDash.lp_selection){
      var ls=lastDash.lp_selection;
      hint.textContent=(ls.label||'')+' → '+(ls.top_pair||ls.top_pool_id||'');
    }
  }

  var scanPollTimer=null;

  function stopScanPoll(){
    if(scanPollTimer){ clearInterval(scanPollTimer); scanPollTimer=null; }
  }

  function setScanStatus(txt){
    var el=document.getElementById('scan-run-status');
    if(el) el.textContent=txt||'';
  }

  function pollScanUntilDone(){
    stopScanPoll();
    scanPollTimer=setInterval(function(){
      fetchScanStatus().then(function(st){
        if(st.running){
          setScanStatus('Scanning…');
          topMsg('Scan running…', false, true);
          return;
        }
        stopScanPoll();
        var btn=document.getElementById('scan-run-now');
        if(btn) btn.disabled=false;
        if(st.exit_code===0){
          setScanStatus('Done');
          topMsg('Scan complete', true);
          msg('Scan finished — refreshed.', true);
          return refresh();
        }
        setScanStatus('Failed');
        topMsg(st.error||'Scan failed', false);
        msg((st.error||'Scan failed')+' — see Scan log link.', false);
      }).catch(function(e){
        stopScanPoll();
        var btn=document.getElementById('scan-run-now');
        if(btn) btn.disabled=false;
        setScanStatus('');
        topMsg(String(e), false);
      });
    }, 2500);
  }

  function runDashboardScan(){
    if(apiHasScanRoute===false){
      topMsg('Restart dashboard to enable Run scan', false);
      msg('Stop the old server on port 8844, then run .\\scripts\\run_dashboard_web.ps1', false);
      return;
    }
    var btn=document.getElementById('scan-run-now');
    if(btn) btn.disabled=true;
    setScanStatus('Starting…');
    topMsg('Starting scan…', false, true);
    gj('/api/scan/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({write_rejections:true})})
      .then(function(r){
        if(!r.ok){
          if(btn) btn.disabled=false;
          setScanStatus('');
          topMsg(r.error||'Could not start scan', false);
          msg(r.error||'Scan already running?', false);
          return;
        }
        setScanStatus('Scanning…');
        pollScanUntilDone();
      })
      .catch(function(e){
        if(btn) btn.disabled=false;
        setScanStatus('');
        topMsg(String(e), false);
        msg(String(e), false);
      });
  }

  function resumeScanPollIfNeeded(){
    var st=scanStatusFromTune(lastTunePlan);
    if(st&&st.running){
      var btn=document.getElementById('scan-run-now');
      if(btn) btn.disabled=true;
      setScanStatus('Scanning…');
      pollScanUntilDone();
      return;
    }
    if(apiHasScanRoute!==true) return;
    fetchScanStatus().then(function(s){
      if(s&&s.running){
        var btn2=document.getElementById('scan-run-now');
        if(btn2) btn2.disabled=true;
        setScanStatus('Scanning…');
        pollScanUntilDone();
      }
    }).catch(function(){ /* ignore */ });
  }

  function selectedTuneIds(){
    var ids=[];
    document.querySelectorAll('.tune-chk:checked').forEach(function(cb){
      if(cb.dataset.tid) ids.push(cb.dataset.tid);
    });
    return ids;
  }

  function wireTuneButtons(){
    var b0=document.getElementById('scan-run-now');
    var b1=document.getElementById('tune-apply-sel');
    var b2=document.getElementById('tune-apply-all');
    var b3=document.getElementById('live-open-top');
    if(b0) b0.onclick=runDashboardScan;
    if(b1) b1.onclick=function(){
      topMsg('Applying tune…', false, true);
      gj('/api/tune/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:selectedTuneIds()})})
        .then(function(r){
          topMsg('Tune applied ('+(r.applied_ids||[]).length+' items)', true);
          msg('Settings updated — click Run scan now.', true);
          return loadSettings().then(function(){ return refresh(); });
        })
        .catch(function(e){ topMsg(String(e), false); msg(String(e), false); });
    };
    if(b2) b2.onclick=function(){
      topMsg('Applying all…', false, true);
      gj('/api/tune/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({apply_all:true})})
        .then(function(r){
          topMsg('Applied '+((r.applied_ids||[]).length)+' tune(s)', true);
          return loadSettings().then(function(){ return refresh(); });
        })
        .catch(function(e){ topMsg(String(e), false); msg(String(e), false); });
    };
    if(b3) b3.onclick=function(){
      var typed=window.prompt('Type LIVE to open the top verified CLMM candidate on-chain:');
      if(typed!=='LIVE'){ msg('Open cancelled.', false); return; }
      topMsg('Opening CLMM…', false, true);
      gj('/api/live/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:'LIVE'})})
        .then(function(r){
          if(r.ok){
            topMsg('Position opened', true);
            msg('Live open OK — check LIVE trades panel.', true);
          }else{
            topMsg(r.error||'Open failed', false);
            msg(r.error||'Open failed', false);
          }
          return refresh();
        })
        .catch(function(e){ topMsg(String(e), false); msg(String(e), false); });
    };
  }

  async function loadTunePlan(){
    try{
      renderTunePanel(await gj('/api/tune'));
    }catch(e){
      renderTunePanel({error:String(e)});
    }
  }

  function renderDoctorPanel(doc){
    var el=$('#doctor-panel');
    if(!el) return;
    doc=doc||{};
    var recs=doc.recommendations||[];
    if(!recs.length){
      el.innerHTML='<p class="muted">No recommendations yet — run a scan with <code>--write-reports</code> so rejections populate.</p>';
      return;
    }
    el.innerHTML='<p class="muted">Objective: '+esc(doc.objective||'')+'</p>'+
      recs.map(function(r){
        return '<div class="doctor-rec"><h4>'+esc(r.title||'')+
          ' <span class="risk">'+esc(r.risk||'')+'</span></h4><p>'+esc(r.detail||'')+'</p></div>';
      }).join('');
  }

  async function refresh(){
    try{
      if(window.RaydiumMode){
        lastRuntime=await window.RaydiumMode.syncRuntime();
        var uiMode=window.RaydiumMode.getStoredUiMode()||(lastRuntime&&lastRuntime.mode)||'demo';
        updateModeStatus(uiMode, lastRuntime&&lastRuntime.wallet);
      }else{
        lastRuntime=await gj('/api/runtime');
        if(lastRuntime.mode && !getStoredUiMode()) setStoredUiMode(lastRuntime.mode);
        applyViewMode((getStoredUiMode()||lastRuntime.mode||'demo').toLowerCase());
        updateModeStatus(lastRuntime.mode, lastRuntime.wallet);
      }
    }catch(e){ /* runtime optional — keep sessionStorage UI mode */ }
    var dash=await gj('/api/dashboard');
    $('#err').textContent='';
    renderAll(dash);
    try{ await loadTunePlan(); }catch(e){ renderTunePanel({error:String(e)}); }
    resumeScanPollIfNeeded();
    try{ renderDoctorPanel(await gj('/api/doctor')); }catch(e){ renderDoctorPanel(null); }
  }

  async function loadSettings(){
    var s=await gj('/api/settings'); mount(s);
  }

  function msg(t, ok){
    var e=$('#st');
    if(e){ e.textContent=t; e.className=ok?'o':(t?'e':''); }
    topMsg(t, ok);
  }

  var topMsgTimer=null;
  function topMsg(t, ok, busy){
    var el=$('#save-status-top');
    if(!el) return;
    clearTimeout(topMsgTimer);
    el.textContent=t||'';
    el.className='save-status-top'+(busy?' busy':(ok?' ok':(t?' err':'')));
    if(t&&!busy) topMsgTimer=setTimeout(function(){ el.textContent=''; el.className='save-status-top'; }, 5000);
  }

  function flashSaveOk(){
    var b=document.getElementById('save');
    if(!b) return;
    var label='Save settings';
    b.classList.add('saved');
    b.textContent='Saved ✓';
    setTimeout(function(){
      b.classList.remove('saved');
      b.textContent=label;
    }, 2500);
  }

  document.getElementById('reload').onclick=function(){topMsg(''); msg(''); refresh().catch(function(e){msg(String(e),false);}); loadSettings().catch(function(e){msg(String(e),false);});};
  document.getElementById('save').onclick=function(){
    var saveBtn=document.getElementById('save');
    if(saveBtn){ saveBtn.classList.add('saving'); }
    topMsg('Saving…', false, true);
    msg('Saving…',true);
    try{
      var patch=collect();
      if('dry_run' in patch){
        patch.mode=patch.dry_run?'demo':'live';
        if(!patch.dry_run && (!lastRuntime||String(lastRuntime.mode).toLowerCase()!=='live')){
          var typed=window.prompt('Type LIVE (all caps) to arm live mode when saving settings:');
          if(typed!=='LIVE'){
            if(saveBtn) saveBtn.classList.remove('saving');
            msg('Not saved — LIVE not confirmed.', false);
            return;
          }
          patch.confirm='LIVE';
        }
      }
      gj('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)})
        .then(function(d){
          if(d.mode) lastRuntime=Object.assign({}, lastRuntime||{}, d);
          var m=(d.mode||lastRuntime&&lastRuntime.mode||'demo').toLowerCase();
          applyViewMode(m);
          updateModeStatus(m, d.wallet);
          flashSaveOk();
          topMsg('Settings saved ('+m.toUpperCase()+')', true);
          msg('Settings saved.', true);
          if(saveBtn) saveBtn.classList.remove('saving');
          return refresh().then(function(){ return loadSettings(); });
        })
        .catch(function(e){
          if(saveBtn) saveBtn.classList.remove('saving');
          msg(String(e),false);
        });
    }catch(e){
      if(saveBtn) saveBtn.classList.remove('saving');
      msg(String(e),false);
    }
  };

  var timer=null;
  function arm(){
    clearInterval(timer);
    if(autoRefreshPaused>0) return;
    if(document.getElementById('auto').checked) timer=setInterval(function(){refresh().catch(function(){});},4000);
  }
  document.getElementById('auto').onchange=arm;
  wireAnomaliesFeedPause();

  document.getElementById('tabbtn-pos').onclick=function(){activateTab('tab-pos');};
  document.getElementById('tabbtn-funnel').onclick=function(){activateTab('tab-funnel');};
  document.getElementById('tabbtn-raw').onclick=function(){activateTab('tab-raw');};
  var jumpLp=document.getElementById('jump-lp-entry');
  if(jumpLp) jumpLp.onclick=jumpToLpEntry;
  if(location.hash==='#lp-order-entry') setTimeout(jumpToLpEntry, 400);

  var btnDemo=$('#btn-mode-demo'), btnLive=$('#btn-mode-live');
  if(window.RaydiumMode){
    window.RaydiumMode.wireModeButtons(function(r){
      if(r&&r.ok){
        topMsg('Synced '+(r.mode||'').toUpperCase(), true);
        updateModeStatus(r.mode, r.data&&r.data.wallet);
      }else if(r&&!r.ok){
        topMsg(r.error||'Mode sync failed', false);
      }
      refresh().catch(function(){});
    });
  }else{
    if(btnDemo) btnDemo.onclick=function(){ setTradingMode('demo').then(function(r){ if(r) return refresh(); }); };
    if(btnLive) btnLive.onclick=function(){ setTradingMode('live').then(function(r){ if(r) return refresh(); }); };
    var bootMode=getStoredUiMode();
    if(bootMode) applyViewMode(bootMode);
  }

  wireLpPickButtons();
  checkDashboardApi().then(function(h){
    if(h&&apiHasScanRoute===false){
      topMsg('Dashboard needs restart for Run scan', false);
    }
    return refresh();
  }).catch(function(e){$('#err').textContent=String(e);$('#fu').innerHTML='<p style="color:var(--no)">'+esc(String(e))+'</p>';});
  loadSettings().catch(function(e){msg(String(e),false);});
  arm();
})();

