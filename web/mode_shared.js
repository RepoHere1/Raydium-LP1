'use strict';
/** Shared DRY_RUN/LIVE UI for dashboard + positions (sessionStorage + glow row). */
(function(global){
  var UI_MODE_KEY = 'raydium_lp1_ui_mode';

  function getStoredUiMode(){
    try{
      var m = sessionStorage.getItem(UI_MODE_KEY);
      if (m === 'live' || m === 'demo' || m === 'dry_run') return (m === 'dry_run' ? 'demo' : m);
    } catch (e) {}
    return null;
  }

  function setStoredUiMode(m){
    try { sessionStorage.setItem(UI_MODE_KEY, String(m || 'demo').toLowerCase()); } catch (e) {}
  }

  function applyViewMode(mode){
    var m = (mode || 'demo').toLowerCase();
    var isLive = (m === 'live');
    document.body.classList.remove('view-live', 'view-demo');
    document.body.classList.add(isLive ? 'view-live' : 'view-demo');
    var demoBtn = document.getElementById('btn-mode-demo');
    var liveBtn = document.getElementById('btn-mode-live');
    if (demoBtn) {
      demoBtn.classList.toggle('active', !isLive);
      demoBtn.setAttribute('aria-pressed', isLive ? 'false' : 'true');
    }
    if (liveBtn) {
      liveBtn.classList.toggle('active', isLive);
      liveBtn.setAttribute('aria-pressed', isLive ? 'true' : 'false');
    }
    var status = document.getElementById('mode-status-text');
    if (status) {
      status.textContent = isLive
        ? 'LIVE — on-chain spends allowed when runners are armed'
        : 'DRY_RUN — live Raydium + RPC; on-chain spends blocked';
    }
    var stamp = document.getElementById('stamp');
    if (stamp) {
      stamp.classList.remove('stamp-demo', 'stamp-live');
      stamp.classList.add(isLive ? 'stamp-live' : 'stamp-demo');
    }
    try { document.title = (document.title.split('·')[0].trim() || 'Raydium-LP1') + ' · ' + (isLive ? 'LIVE' : 'DRY_RUN'); } catch (e) {}
  }

  async function apiJson(url, opt){
    var r = await fetch(url, opt);
    var t = await r.text();
    var d;
    try { d = JSON.parse(t); } catch (e) { throw new Error(t.slice(0, 160)); }
    if (!r.ok) throw new Error((d && d.error) || t || String(r.status));
    return d;
  }

  async function setTradingMode(next){
    var m = String(next || 'demo').toLowerCase();
    if (m === 'live') {
      var typed = window.prompt('Type LIVE (all caps) to enable real on-chain spends:');
      if (typed !== 'LIVE') return null;
    }
    setStoredUiMode(m);
    applyViewMode(m);
    var body = { mode: m };
    if (m === 'live') body.confirm = 'LIVE';
    var data = null;
    try {
      data = await apiJson('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e1) {
      try {
        var patch = { mode: m, dry_run: m !== 'live' };
        if (m === 'live') patch.confirm = 'LIVE';
        data = await apiJson('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        });
      } catch (e2) {
        return { ok: false, mode: m, error: String(e1.message || e1) };
      }
    }
    var confirmed = (data.mode || m).toLowerCase();
    setStoredUiMode(confirmed);
    applyViewMode(confirmed);
    return { ok: true, mode: confirmed, data: data };
  }

  function wireModeButtons(onChange){
    var demoBtn = document.getElementById('btn-mode-demo');
    var liveBtn = document.getElementById('btn-mode-live');
    if (demoBtn) {
      demoBtn.onclick = function(){
        setStoredUiMode('demo');
        applyViewMode('demo');
        setTradingMode('demo').then(function(r){
          if (onChange) onChange(r);
        });
      };
    }
    if (liveBtn) {
      liveBtn.onclick = function(){
        setTradingMode('live').then(function(r){
          if (onChange) onChange(r);
        });
      };
    }
    var boot = getStoredUiMode();
    if (boot) applyViewMode(boot);
    else applyViewMode('demo');
  }

  async function syncRuntime(){
    try {
      var rt = await apiJson('/api/runtime');
      if (rt.mode && !getStoredUiMode()) setStoredUiMode(rt.mode);
      applyViewMode(getStoredUiMode() || rt.mode || 'demo');
      return rt;
    } catch (e) {
      applyViewMode(getStoredUiMode() || 'demo');
      return null;
    }
  }

  global.RaydiumMode = {
    getStoredUiMode: getStoredUiMode,
    setStoredUiMode: setStoredUiMode,
    applyViewMode: applyViewMode,
    setTradingMode: setTradingMode,
    wireModeButtons: wireModeButtons,
    syncRuntime: syncRuntime,
  };
})(window);
