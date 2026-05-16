"""Local funnel + settings dashboard (loopback-only HTTP).

``GET /`` serves a single-page UI. ``GET /api/dashboard`` and ``GET /api/settings`` return JSON.
``POST /api/settings`` merges an object into ``config/settings.json`` (scanner-known keys only).

Windows Terminal (PowerShell), two windows from repo root::

    .\\scripts\\run_scan_dashboard.ps1
    .\\scripts\\run_dashboard_web.ps1

Then open http://127.0.0.1:8844/
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

_CSS_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Raydium-LP1 · funnel & settings</title>
<style>
:root{--bg:#0e1218;--panel:#171d27;--line:#293241;--txt:#eaf0fa;--m:#93a4ba;--a:#4596ff;--ok:#39d698;--no:#ff6b6b;--wm:#fdb34b;
--sans:ui-sans-serif,system-ui,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 600px at 10% -6%,#1a2638,#0e1218 55%);color:var(--txt);
font:14px/1.45 var(--sans)}header{padding:.85rem 1rem;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;
gap:.5rem 1rem;align-items:center;background:#131a26}h1{font-size:1.06rem;margin:0}
.p{font-size:.65rem;letter-spacing:.06em;color:var(--m);border:1px solid var(--line);border-radius:999px;padding:.15rem .5rem;text-transform:uppercase}
.pl{border-color:#5a4930;color:var(--wm)}.tb{margin-left:auto;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
button{font:inherit;border-radius:8px;border:1px solid var(--line);background:#242d3d;color:var(--txt);padding:.4rem .8rem;cursor:pointer}
button.p{background:rgba(69,150,255,.2);border-color:#3576c9;color:#8ec5ff;font-weight:600}
main{padding:1rem;max-width:1340px;margin:0 auto;display:grid;gap:1rem}@media(min-width:1060px){
main{grid-template-columns:minmax(0,1.06fr) minmax(328px,.94fr)}}
.cd{border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}
.cd>h2{margin:0;padding:.62rem .9rem;background:#151c29;border-bottom:1px solid var(--line);font-size:.93rem;display:flex}
.bd{padding:.88rem}.sg{font-size:.65rem;color:var(--m);margin:.72rem 0 .35rem;text-transform:uppercase;letter-spacing:.08em;font-weight:600}
.sg:first-child{margin-top:0}.fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(204px,1fr));gap:.72rem}
.lb{display:flex;flex-direction:column;gap:.25rem;font-size:.62rem;color:var(--m);text-transform:uppercase;letter-spacing:.04em}
.lb.h{flex-direction:row;text-transform:none;letter-spacing:normal;font-size:.84rem;color:var(--txt);align-items:center;gap:.45rem}
input,select,textarea{font:inherit;border-radius:8px;border:1px solid var(--line);background:#212a3b;color:var(--txt);padding:.38rem .5rem}
textarea{min-height:64px;font-family:var(--mono);font-size:.8rem}.kp{display:grid;gap:.52rem;margin-bottom:.85rem;
grid-template-columns:repeat(auto-fit,minmax(114px,1fr))}.k{border:1px solid var(--line);border-radius:8px;background:#202838;padding:.5rem .65rem}
.k span.x{display:block;font-size:.61rem;color:var(--m);letter-spacing:.05em;text-transform:uppercase}
.k span.v{font-size:1.12rem;font-weight:600;font-variant-numeric:tabular-nums}.k.g .v{color:var(--ok)}.k.r .v{color:var(--no)}
.bar{display:grid;grid-template-columns:minmax(0,168px) 1fr 2.25rem;font-size:.8rem;gap:.45rem;margin:.32rem 0;align-items:center}
.tr{height:7px;border-radius:4px;background:#1e2739;border:1px solid var(--line);overflow:hidden}
.fil{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--a),#9fd0ff)}
.ta{width:100%;border-collapse:collapse;font-size:.8rem}.ta th,.ta td{padding:.28rem .4rem;border-bottom:1px solid var(--line)}
.ta th{text-align:left;color:var(--m);font-weight:500;font-size:.74rem}.ta td.c{font-family:var(--mono);color:var(--m);width:2.75rem}
ul.z{margin:.45rem 0;color:var(--m);font-size:.84rem;padding-left:1rem;border-left:3px solid var(--line)}
.pr div{padding:.32rem 0;border-bottom:1px dashed var(--line);font-size:.8rem;color:var(--m)}.pr div:last-child{border:0}
.tb2{width:100%;font-size:.78rem;border-collapse:collapse}.tb2 th,.tb2 td{border-bottom:1px solid var(--line);padding:.32rem .4rem;text-align:left}
.tb2 th{color:var(--m)}#st{margin-top:.6rem;font:.8rem var(--mono);color:var(--m)}#st.e{color:var(--no)}#st.o{color:var(--ok)}
a{color:var(--a)}
</style></head><body>
<header><h1>Raydium-LP1</h1><span class="p pl">127.0.0.1 only</span><span class="p" id="stamp">waiting…</span>
<div class="tb"><label style="font-size:.8rem;color:var(--m)"><input type="checkbox" id="auto" checked/> Auto 5s</label>
<button type="button" id="reload">Reload</button><button type="button" id="save" class="p">Save settings</button></div></header>
<script type="application/json" id="boot">BOOT_JSON</script>
<main><div><div class="cd"><h2>Funnel <a id="rj" href="api/dashboard" style="margin-left:auto;font-size:.73rem;color:var(--m);font-weight:400;text-decoration:none">raw JSON →</a></h2><div id="fu" class="bd"></div></div>
<div class="cd"><h2>Dry-run shortlist</h2><div id="li" class="bd"></div></div></div>
<div class="cd"><h2>Settings</h2><div class="bd"><div id="fo"></div><div id="st"></div></div></div></main>
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
      var sg=document.createElement('div'); sg.className='sg'; sg.textContent=sec.title; root.appendChild(sg);
      var fg=document.createElement('div'); fg.className='fg';
      for(var fi=0;fi<(sec.fields||[]).length;fi++){
        var f=sec.fields[fi]; var kk=f.key, ty=f.type;
        if(ty==='checkbox'){
          var L=document.createElement('label'); L.className='lb h'; var inp=document.createElement('input');
          inp.type='checkbox'; inp.dataset.sk=kk; inp.checked=!!raw[kk];
          L.appendChild(inp); L.appendChild(document.createTextNode(' '+f.label)); fg.appendChild(L); continue;
        }
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
        lab.appendChild(inp2); fg.appendChild(lab);
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

  function renderFunnel(d){
    var ls=d.last_scan||{}, sc=ls.scanned_count||0, c=ls.candidate_count||0, rej=ls.rejected_count||0;
    var rate=(c+rej)>0?(100*c/(c+rej)):0;
    $('#stamp').textContent='dash '+(d.generated_at||'?').replace('T',' ').slice(11,22)+'Z';
    var bd=Object.entries(ls.rejection_breakdown||{}).sort(function(a,b){return b[1]-a[1];});
    var mx=Math.max.apply(null,bd.map(function(x){return x[1];}).concat([0]))||1;
    var bars=bd.slice(0,18).map(function(kv){
      return '<div class="bar"><div title="'+esc(kv[0])+'">'+esc(kv[0])+'</div><div class="tr"><div class="fil" style="width:'+
        ((100*kv[1]/mx).toFixed(1))+'%"></div></div><div style="font-family:var(--mono);font-size:.72rem;color:var(--m);text-align:right">'+kv[1]+'</div></div>';
    }).join('');
    if(!bars) bars='<p style="color:var(--m);margin:.2rem 0">No breakdown yet.</p>';
    var hist=Object.entries(ls.rejection_reason_histogram||{}).slice(0,26);
    var ht=hist.length?('<div class="sg">Exact first reasons</div><table class="ta"><thead><tr><th class="c">#</th><th>reason</th></tr></thead><tbody>'+
      hist.map(function(kv){return '<tr><td class="c">'+kv[1]+'</td><td>'+esc(kv[0])+'</td></tr>';}).join('')+'</tbody></table>'):'';
    var diag=ls.scan_diagnosis||{};
    var nar=(diag.narrative_lines||[]).map(function(l){return '<li>'+esc(l)+'</li>';}).join('');
    var pr=(diag.setting_pressure||[]).map(function(p){
      return '<div><b>'+esc(p.setting_key||'')+'</b> — '+esc(p.direction||'')+' ('+esc(String(p.reject_share_pct))+'% · '+esc(p.category_driver||'')+')<br><small>'+
        esc(p.concrete_suggestion||p.rationale||'')+'</small></div>';
    }).join('');
    $('#fu').innerHTML='<div class="kp"><div class="k"><span class="x">Scanned</span><span class="v">'+sc+'</span></div>'+
      '<div class="k g"><span class="x">Candidates</span><span class="v">'+c+'</span></div>'+
      '<div class="k r"><span class="x">Rejected</span><span class="v">'+rej+'</span></div>'+
      '<div class="k"><span class="x">Pass share</span><span class="v">'+rate.toFixed(1)+'%</span></div></div>'+
      '<div class="sg">Reject categories</div>'+bars+ht+
      (nar?('<div class="sg">Narrative</div><ul class="z">'+nar+'</ul>'):'')+
      (pr?('<div class="sg">Suggested levers</div><div class="pr">'+pr+'</div>'):'');
  }

  function renderList(rows){
    if(!rows||!rows.length){$('#li').innerHTML='<p style="color:var(--m);margin:0">No candidates.</p>';return;}
    $('#li').innerHTML='<table class="tb2"><thead><tr><th>Pair</th><th>APR</th><th>TVL</th><th>VOL24</th><th>Mom</th><th>Pool</th></tr></thead><tbody>'+
      rows.slice(0,48).map(function(p){
        return '<tr><td>'+esc(p.pair||'')+'</td><td>'+num(p.apr)+'%</td><td>'+num(p.liquidity_usd)+'</td><td>'+num(p.volume_24h_usd)+'</td><td>'+
          (p.momentum_score!=null?esc(String(p.momentum_score))+' '+esc(String(p.momentum_tier||'')):'')+'</td>'+
          '<td style="font-family:var(--mono);font-size:.72rem">'+esc(p.pool_id||p.id||'')+'</td></tr>';
      }).join('')+'</tbody></table>';
  }

  async function refresh(){
    var dash=await gj('/api/dashboard');
    renderFunnel(dash); renderList(dash.open_positions||[]);
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

  refresh().catch(function(e){$('#fu').innerHTML='<p style="color:#f88">'+esc(String(e))+'</p>';});
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
