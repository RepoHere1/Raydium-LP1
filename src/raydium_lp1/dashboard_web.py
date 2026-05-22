"""Local funnel + settings dashboard (loopback-only HTTP).

``GET /`` serves a single-page UI. ``GET /api/dashboard`` and ``GET /api/settings`` return JSON.
``POST /api/settings`` merges an object into ``config/settings.json`` (scanner-known keys only).

Use with::

    python -m raydium_lp1.dashboard_web

and run the scanner with ``--dashboard --loop --reload-config-each-scan`` while you tune gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from raydium_lp1.dashboard import DEFAULT_DASHBOARD_PATH
from raydium_lp1.dashboard_field_help import attach_field_help, attach_section_help
from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch
from raydium_lp1.strategies import ALLOWED_STRATEGIES

DEFAULT_SETTINGS_PATH = Path("config/settings.json")

_FORM_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "Liquidity gates",
        "fields": [
            {"key": "min_apr", "label": "Min APR %", "type": "number", "step": "any"},
            {"key": "min_liquidity_usd", "label": "Min TVL (USD)", "type": "number", "step": "any"},
            {"key": "min_volume_24h_usd", "label": "Min Vol 24h (USD)", "type": "number", "step": "any"},
            {"key": "hard_exit_min_tvl_usd", "label": "Hard reject if TVL < (USD)", "type": "number", "step": "any"},
            {"key": "max_position_usd", "label": "Max position USD", "type": "number", "step": "any"},
        ],
    },
    {
        "title": "Raydium paging",
        "fields": [
            {"key": "apr_field", "label": "APR field key", "type": "text"},
            {"key": "pool_sort_field", "label": "Pool sort field", "type": "text"},
            {"key": "sort_type", "label": "Sort direction", "type": "select", "options": ["desc", "asc"]},
            {"key": "pages", "label": "Pages fetched", "type": "number"},
            {"key": "page_size", "label": "Page size", "type": "number"},
            {"key": "pool_type", "label": "pool_type", "type": "text"},
            {"key": "page_delay_seconds", "label": "Page delay (s)", "type": "number", "step": "any"},
            {"key": "http_timeout_seconds", "label": "HTTP timeout", "type": "number"},
        ],
    },
    {
        "title": "Age, burn, verification",
        "fields": [
            {"key": "max_pool_age_hours", "label": "Max pool age hrs (0=off)", "type": "number", "step": "any"},
            {"key": "min_pool_age_hours", "label": "Min pool age hrs", "type": "number", "step": "any"},
            {"key": "min_burn_percent", "label": "Min LP burn %", "type": "number", "step": "any"},
            {"key": "verify_pool_on_chain", "label": "Verify pool on-chain", "type": "checkbox"},
            {"key": "verify_pool_raydium_api", "label": "Raydium API verify", "type": "checkbox"},
            {"key": "require_verified_raydium_pool", "label": "Require verified Raydium pool", "type": "checkbox"},
            {"key": "require_pool_id", "label": "Require pool id", "type": "checkbox"},
        ],
    },
    {
        "title": "Momentum",
        "fields": [
            {"key": "momentum_enabled", "label": "Momentum enabled", "type": "checkbox"},
            {"key": "min_momentum_score", "label": "Min momentum score", "type": "number", "step": "any"},
            {"key": "require_momentum_score", "label": "Require momentum score pass", "type": "checkbox"},
            {"key": "momentum_hold_hours", "label": "Hold window hrs", "type": "number", "step": "any"},
            {"key": "momentum_top_hot", "label": "TOP HOT size", "type": "number"},
            {"key": "sort_candidates_by_momentum", "label": "Sort candidates by momentum", "type": "checkbox"},
            {"key": "momentum_min_volume_tvl_ratio", "label": "Min Vol/TVL ratio", "type": "number", "step": "any"},
            {"key": "momentum_sweet_min_pool_age_hours", "label": "Sweet min pool age hrs", "type": "number", "step": "any"},
            {"key": "momentum_sweet_max_pool_age_hours", "label": "Sweet max pool age hrs", "type": "number", "step": "any"},
            {"key": "momentum_min_tvl_usd", "label": "Momentum min TVL USD", "type": "number", "step": "any"},
            {"key": "momentum_detective_enabled", "label": "Momentum detective", "type": "checkbox"},
            {"key": "momentum_probe_market_lists", "label": "Probe market lists", "type": "checkbox"},
        ],
    },
    {
        "title": "Routes and reporting",
        "fields": [
            {"key": "require_sell_route", "label": "Require sell route", "type": "checkbox"},
            {"key": "use_robust_routing", "label": "Robust routing", "type": "checkbox"},
            {"key": "max_route_price_impact_pct", "label": "Max quote price impact %", "type": "number", "step": "any"},
            {"key": "route_sources_json", "label": "route_sources (JSON array)", "type": "json_text"},
            {"key": "write_rejections", "label": "Write rejections CSV", "type": "checkbox"},
            {"key": "rejections_csv_path", "label": "Rejections CSV path", "type": "text"},
        ],
    },
    {
        "title": "Wallet and emergency",
        "fields": [
            {"key": "position_size_sol", "label": "Position SOL", "type": "number", "step": "any"},
            {"key": "reserve_sol", "label": "Reserve SOL", "type": "number", "step": "any"},
            {"key": "emergency_close_enabled", "label": "Emergency close", "type": "checkbox"},
            {"key": "emergency_max_slippage_pct", "label": "Emergency max slip (0-1 frac)", "type": "number", "step": "any"},
            {"key": "emergency_base_symbol", "label": "Emergency base symbol", "type": "text"},
            {"key": "emergency_alerts_path", "label": "Alerts path", "type": "text"},
            {"key": "track_liquidity_health", "label": "Track liquidity health", "type": "checkbox"},
            {"key": "liquidity_history_path", "label": "Liquidity history path", "type": "text"},
        ],
    },
    {
        "title": "LP paper planning",
        "fields": [
            {"key": "lp_planning_enabled", "label": "LP planning", "type": "checkbox"},
            {"key": "lp_range_mode", "label": "Range mode", "type": "text"},
            {"key": "lp_default_range_width_pct", "label": "Default band %", "type": "number", "step": "any"},
            {"key": "lp_range_width_candidates_json", "label": "Band width candidates JSON", "type": "json_text"},
            {"key": "lp_skew_use_momentum", "label": "Skew bands via momentum", "type": "checkbox"},
            {"key": "lp_full_range_parallel", "label": "Parallel full-range paper leg", "type": "checkbox"},
            {"key": "lp_full_range_budget_fraction", "label": "Full-range budget frac", "type": "number", "step": "any"},
            {"key": "lp_main_budget_fraction", "label": "Main budget frac", "type": "number", "step": "any"},
            {"key": "lp_max_positions_per_mint", "label": "Max LP positions/mint", "type": "number"},
        ],
    },
    {
        "title": "Network metadata",
        "fields": [
            {"key": "strategy", "label": "strategy", "type": "select", "options": list(ALLOWED_STRATEGIES)},
            {"key": "network", "label": "network", "type": "text"},
            {"key": "risk_profile", "label": "risk_profile", "type": "text"},
            {"key": "dry_run", "label": "Dry run only", "type": "checkbox"},
            {"key": "raydium_api_base", "label": "Raydium API base", "type": "text"},
            {"key": "solana_rpc_urls_lines", "label": "RPC URLs (one per line)", "type": "lines"},
            {"key": "allowed_quote_symbols_csv", "label": "Allowed quotes CSV", "type": "csv"},
            {"key": "blocked_token_symbols_csv", "label": "Blocked symbols CSV", "type": "csv"},
            {"key": "blocked_mints_lines", "label": "Blocked mints lines", "type": "lines"},
            {"key": "dashboard_path", "label": "Dashboard JSON path", "type": "text"},
            {"key": "scan_loop", "label": "scan_loop (prefer CLI)", "type": "checkbox"},
            {"key": "scan_loop_interval_seconds", "label": "Loop interval hint (s)", "type": "number"},
            {"key": "spawn_verdict_watcher", "label": "Spawn verdict watcher", "type": "checkbox"},
        ],
    },
]

attach_field_help(_FORM_SECTIONS)
attach_section_help(_FORM_SECTIONS)

_CSS_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Raydium-LP1 · dashboard</title>
<style>
:root{--bg:#eef2f7;--card:#fff;--line:#d5dbe8;--txt:#1e293b;--muted:#64748b;--a:#2563eb;--ok:#059669;--no:#dc2626;--amber:#d97706;
--sans:ui-sans-serif,system-ui,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(165deg,#f8fafc 0%,var(--bg) 42%,#e8eef6 100%);color:var(--txt);font:15px/1.5 var(--sans)}
.topbar{padding:1rem 1.25rem;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:.65rem 1rem;align-items:center;background:rgba(255,255,255,.92);backdrop-filter:blur(8px)}
.topbar h1{font-size:1.15rem;margin:0;font-weight:700;letter-spacing:-.02em}
.badge{font-size:.68rem;letter-spacing:.06em;border:1px solid var(--line);border-radius:999px;padding:.2rem .55rem;color:var(--muted);text-transform:uppercase;background:#fff}
.badge-warn{border-color:#fcd34d;color:var(--amber);background:#fffbeb}
.tb{margin-left:auto;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
button{font:inherit;border-radius:10px;border:1px solid var(--line);background:#fff;color:var(--txt);padding:.45rem .85rem;cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.06)}
button:hover{border-color:#c7d2e8;background:#f8fafc}
button.p{background:#eff6ff;border-color:#93c5fd;color:#1d4ed8;font-weight:600}
.hint-bar{margin:0;padding:.55rem 1.25rem;font-size:.82rem;color:var(--muted);background:rgba(255,255,255,.65);border-bottom:1px solid var(--line)}
.mode-bar{margin:0;padding:.65rem 1.25rem;font-size:.9rem;line-height:1.45;border-bottom:1px solid var(--line)}
.mode-bar.mode-demo{background:#fffbeb;border-color:#fde68a;color:#92400e}
.mode-bar.mode-live{background:#ecfdf5;border-color:#a7f3d0;color:#065f46}
.mode-tag{display:inline-block;font-weight:800;font-size:.72rem;letter-spacing:.08em;margin-right:.5rem;padding:.12rem .45rem;border-radius:6px;background:rgba(0,0,0,.06)}
.page{max-width:1280px;margin:0 auto;padding:1rem 1.25rem 2.5rem;display:flex;flex-direction:column;gap:1.1rem}
.panel{border:1px solid var(--line);border-radius:14px;background:var(--card);box-shadow:0 4px 24px rgba(15,23,42,.06);overflow:visible}
.panel>h2{margin:0;padding:.75rem 1rem;font-size:1rem;font-weight:650;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fafbfe,#fff);border-radius:14px 14px 0 0;display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.panel>h2 .sub{font-weight:400;font-size:.82rem;color:var(--muted);margin-left:auto}
.bd{padding:1rem;overflow:visible}
.pill{font-size:.68rem;font-weight:700;padding:.18rem .5rem;border-radius:6px;margin-left:.35rem;vertical-align:middle}
.pill-demo{background:#fef3c7;color:#92400e;border:1px solid #fcd34d}
.pill-live{background:#d1fae5;color:#065f46;border:1px solid #6ee7b7}
.muted{color:var(--muted);font-size:.88rem;margin:.25rem 0 .75rem}
.tbl-scroll{max-height:70vh;overflow:auto;border:1px solid var(--line);border-radius:10px}
.tbl-scroll .tb2{margin:0}
.sg{font-size:.68rem;color:var(--muted);margin:.85rem 0 .4rem;text-transform:uppercase;letter-spacing:.07em;font-weight:700}
.sg:first-child{margin-top:0}
.fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.85rem}
.lb{display:flex;flex-direction:column;gap:.28rem;font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.lb.h{flex-direction:row;text-transform:none;letter-spacing:normal;font-size:.88rem;color:var(--txt);align-items:center;gap:.45rem}
.fw{position:relative;padding-bottom:.2rem}
.fw-pop{display:none;position:absolute;left:0;top:calc(100% - 2px);z-index:80;min-width:260px;max-width:min(440px,92vw);padding:.75rem .9rem;background:#fff;border:1px solid #c7d2e8;border-radius:10px;box-shadow:0 12px 36px rgba(15,23,42,.14);font-size:.82rem;line-height:1.45;font-weight:400;color:var(--txt);text-transform:none;letter-spacing:normal;white-space:pre-wrap}
.fw:hover .fw-pop,.fw:focus-within .fw-pop{display:block}
.sec-hw{position:relative;margin-bottom:.15rem}
.sec-hw .sec-pop{display:none;position:absolute;left:0;top:100%;z-index:75;min-width:280px;max-width:min(480px,94vw);margin-top:4px;padding:.75rem .9rem;background:#fff;border:1px solid #c7d2e8;border-radius:10px;box-shadow:0 12px 36px rgba(15,23,42,.12);font-size:.82rem;line-height:1.45;color:var(--txt);white-space:pre-wrap}
.sec-hw:hover .sec-pop{display:block}
.sg-h{cursor:help;text-decoration:underline dotted rgba(100,116,139,.5);text-underline-offset:3px}
.hint-line{font-size:.78rem;color:var(--muted);line-height:1.38;margin:.15rem 0 0;font-weight:500;text-transform:none;letter-spacing:.01em;max-width:48rem}
.sec-blurb-wrap{margin:.15rem 0 .65rem;max-width:54rem}
.sec-blurb{font-size:.8rem;line-height:1.45;color:var(--muted);border-left:3px solid #93c5fd;padding:.2rem 0 .2rem .65rem}
.sec-blurb .sr{margin-top:.35rem;color:var(--txt);font-weight:500}
input,select,textarea{font:inherit;border-radius:10px;border:1px solid var(--line);background:#f8fafc;color:var(--txt);padding:.42rem .55rem}
input:focus,select:focus,textarea:focus{outline:2px solid #bfdbfe;outline-offset:0;border-color:#93c5fd;background:#fff}
textarea{min-height:64px;font-family:var(--mono);font-size:.8rem}
.kp{display:grid;gap:.55rem;margin-bottom:1rem;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
.hb{position:relative}
.hb.k{border:1px solid var(--line);border-radius:10px;background:#f8fafc;padding:.55rem .65rem}
.hb.k .x{display:block;font-size:.65rem;color:var(--muted);letter-spacing:.05em;text-transform:uppercase}
.hb.k .v{font-size:1.15rem;font-weight:700;font-variant-numeric:tabular-nums}
.hb.k.g .v{color:var(--ok)}.hb.k.r .v{color:var(--no)}
.hb-pop{left:0;right:auto}
.hb:hover .hb-pop{display:block}
.bar{display:grid;grid-template-columns:minmax(0,180px) 1fr 2.25rem;font-size:.82rem;gap:.45rem;margin:.35rem 0;align-items:center;color:var(--muted)}
.tr{height:8px;border-radius:5px;background:#e2e8f0;border:1px solid var(--line);overflow:hidden}
.fil{height:100%;border-radius:4px;background:linear-gradient(90deg,#60a5fa,#93c5fd)}
.ta{width:100%;border-collapse:collapse;font-size:.82rem}.ta th,.ta td{padding:.32rem .45rem;border-bottom:1px solid var(--line)}
.ta th{text-align:left;color:var(--muted);font-weight:600;font-size:.76rem}.ta td.c{font-family:var(--mono);width:2.75rem}
ul.z{margin:.5rem 0;color:var(--muted);font-size:.88rem;padding-left:1rem;border-left:3px solid #cbd5e1}
.pr div{padding:.35rem 0;border-bottom:1px dashed var(--line);font-size:.84rem;color:var(--muted)}.pr div:last-child{border:0}
.tb2{width:100%;font-size:.8rem;border-collapse:collapse}.tb2 th,.tb2 td{border-bottom:1px solid var(--line);padding:.4rem .45rem;text-align:left}
.tb2 th{color:var(--muted);font-weight:600;position:sticky;top:0;background:#f8fafc;z-index:1}
.tb2 .mono{font-family:var(--mono);font-size:.74rem;word-break:break-all}
#st{margin-top:.75rem;font:.82rem var(--mono);color:var(--muted)}#st.e{color:var(--no)}#st.o{color:var(--ok)}
#err:empty{display:none}#err{color:var(--no);font-size:.88rem;padding:.5rem 1.25rem;background:#fef2f2;border-bottom:1px solid #fecaca}
a{color:var(--a)}a#rj{margin-left:auto;font-size:.78rem;font-weight:500;color:var(--muted)}
.settings-wide{max-width:100%}
@media(min-width:1100px){.page{display:grid;grid-template-columns:1fr 1fr;grid-auto-flow:dense;align-items:start}.settings-wide{grid-column:1/-1}}
</style></head><body>
<header class="topbar"><h1>Raydium-LP1</h1><span class="badge badge-warn">127.0.0.1 only</span><span class="badge" id="stamp">…</span>
<div class="tb"><label style="font-size:.84rem;color:var(--muted)"><input type="checkbox" id="auto" checked/> Auto 5s</label>
<button type="button" id="reload">Reload</button><button type="button" id="save" class="p">Save settings</button></div></header>
<p class="hint-bar">Hover any <strong>setting row</strong> for the full field guide (CSS popover). Tables scroll inside the shaded box — full lists, not truncated.</p>
<div id="err"></div>
<div id="mode-bar" class="mode-bar mode-demo">Loading mode…</div>
<script type="application/json" id="boot">BOOT_JSON</script>
<main class="page">
<section class="panel"><h2>Scan funnel <a id="rj" href="api/dashboard">raw JSON →</a></h2><div id="fu" class="bd"></div></section>
<section class="panel"><h2>Candidates <span class="pill pill-demo">demo data</span><span class="sub">Every pool that passed filters this cycle</span></h2><div id="cand" class="bd"></div></section>
<section class="panel"><h2>Momentum <span class="pill pill-demo">demo data</span><span class="sub">Hot leaderboard from last scan</span></h2><div id="mom" class="bd"></div></section>
<section class="panel"><h2>Open / watchlist <span class="pill pill-demo">demo</span><span class="sub">Dry-run stand-in for positions (not on-chain fills)</span></h2><div id="openp" class="bd"></div></section>
<section class="panel"><h2>Closed <span class="pill pill-live">live slot</span><span class="sub">Reserved for real exits when your tracker writes them</span></h2><div id="clop" class="bd"></div></section>
<section class="panel settings-wide"><h2>Settings</h2><div class="bd"><div id="fo"></div><div id="st"></div></div></section>
</main>
<script>
CLIENT_JS_HERE
</script></body></html>"""

_CLIENT_JS = r"""
'use strict';
(function(){
  const boot = JSON.parse(document.getElementById('boot').textContent || '{}');
  const SECTIONS = boot.form_sections || [];
  function $(s,r=document){return r.querySelector(s);}
  function esc(t){var d=document.createElement('div');d.textContent=t==null?'':String(t);return d.innerHTML;}
  function num(n){return (Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});}

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
      return '<div class="bar"><div>'+esc(kv[0])+'</div><div class="tr"><div class="fil" style="width:'+
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
      (pr?('<div class="sg">Suggested levers</div><div class="pr">'+pr+'</div>'):'');
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
        var mtxt=(mom.score!=null)?(String(Math.round(mom.score))+' '+String(mom.tier||'')): '';
        return '<tr><td>'+(i+1)+'</td><td>'+esc(pairFromPool(p))+'</td><td>'+num(p.apr)+'</td><td>'+num(p.liquidity_usd)+'</td><td>'+num(p.volume_24h_usd)+'</td><td>'+esc(mtxt)+'</td><td class="mono">'+esc(p.id||'')+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderMomentumTable(el, rows){
    rows=rows||[];
    if(!rows.length){ el.innerHTML='<p class="muted">No momentum leaderboard rows (enable momentum in settings).</p>'; return; }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — full <code>momentum_hot_top</code> from dashboard JSON.</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>Score</th><th>TVL</th><th>Vol24</th><th>APR %</th><th>Tier</th><th>Tags</th></tr></thead><tbody>'+
      rows.map(function(r,i){
        var tags=(r.sniff_tags||[]).slice(0,6).join(', ');
        return '<tr><td>'+(i+1)+'</td><td>'+esc(r.pair||'')+'</td><td>'+num(r.combined_score)+'</td><td>'+num(r.tvl_usd)+'</td><td>'+num(r.volume_24h_usd)+'</td><td>'+num(r.apr)+'</td><td>'+esc(String(r.tier||''))+'</td><td>'+esc(tags)+'</td></tr>';
      }).join('')+'</tbody></table></div>';
  }

  function renderOpenTable(el, rows, demo){
    rows=rows||[];
    var tag=demo?'demo watchlist (not on-chain)':'from dashboard open_positions';
    if(!rows.length){ el.innerHTML='<p class="muted">No open/watchlist rows. '+esc(tag)+'.</p>'; return; }
    el.innerHTML='<p class="muted">'+rows.length+' row(s) — '+esc(tag)+'.</p>'+
      '<div class="tbl-scroll"><table class="tb2"><thead><tr><th>#</th><th>Pair</th><th>APR %</th><th>TVL</th><th>Vol24</th><th>Health</th><th>Mom</th><th>Pool id</th></tr></thead><tbody>'+
      rows.map(function(p,i){
        return '<tr><td>'+(i+1)+'</td><td>'+esc(p.pair||'')+'</td><td>'+num(p.apr)+'</td><td>'+num(p.liquidity_usd)+'</td><td>'+num(p.volume_24h_usd)+'</td><td>'+esc(String(p.health||''))+'</td><td>'+
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
    renderModeBar(d);
    renderFunnel(d);
    var ls=d.last_scan||{};
    renderCandidateTable($('#cand'), d);
    renderMomentumTable($('#mom'), d.momentum_hot_top||[]);
    var demo=!!(d.settings&&d.settings.dry_run)||String(ls.scan_mode||'').indexOf('dry')>=0||ls.scan_mode==='trade_disabled_in_this_build';
    renderOpenTable($('#openp'), d.open_positions||[], demo);
    renderClosedTable($('#clop'), ls.closed_positions||[]);
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
    if(document.getElementById('auto').checked) timer=setInterval(function(){refresh().catch(function(){});},5000);
  }
  document.getElementById('auto').onchange=arm;

  refresh().catch(function(e){$('#err').textContent=String(e);$('#fu').innerHTML='<p style="color:var(--no)">'+esc(String(e))+'</p>';});
  loadSettings().catch(function(e){msg(String(e),false);});
  arm();
})();
"""


@dataclass(frozen=True)
class WebPaths:
    dashboard_path: Path
    settings_path: Path


def _page() -> bytes:
    boot_payload = {"form_sections": _FORM_SECTIONS}
    html = (
        _CSS_HTML.replace(
            "BOOT_JSON",
            json.dumps(boot_payload, separators=(",", ":")),
        ).replace(
            "CLIENT_JS_HERE",
            _CLIENT_JS,
        )
    )
    return html.encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    import urllib.parse as up  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Raydium-LP1 local dashboard (127.0.0.1 only).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default loopback).")
    parser.add_argument("--port", type=int, default=8844)
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_DASHBOARD_PATH)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS_PATH)
    args = parser.parse_args(argv)

    paths = WebPaths(dashboard_path=args.dashboard, settings_path=args.settings)

    blob = {"page": _page()}

    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, obj: Any) -> None:
            raw = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self._send(code, raw, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = up.urlparse(self.path).path
            if path == "/":
                self._send(200, blob["page"], "text/html; charset=utf-8")
                return
            if path == "/api/dashboard":
                dpath = paths.dashboard_path
                if not dpath.exists():
                    self._send_json(
                        404,
                        {"error": f"Dashboard not found: {dpath} (run scanner with --dashboard)"},
                    )
                    return
                try:
                    data = json.loads(dpath.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            if path == "/api/settings":
                sp = paths.settings_path
                try:
                    data = load_settings_json(sp)
                except (OSError, ValueError) as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, data)
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = up.urlparse(self.path).path
            if path != "/api/settings":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                patch = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            try:
                merge_known_settings_patch(paths.settings_path, patch)
            except (OSError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "path": str(paths.settings_path.resolve())})

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Raydium-LP1 dashboard http://{args.host}:{args.port}/", flush=True)
    print(f"  dashboard JSON: {paths.dashboard_path}", flush=True)
    print(f"  settings file: {paths.settings_path}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
