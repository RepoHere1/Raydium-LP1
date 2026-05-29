'use strict';
/** Positions page data + DRY_RUN/LIVE (requires mode_shared.js loaded first). */
(function () {
  function esc(t) {
    var d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }
  function num(n) {
    return (Number(n) || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  function $(id) {
    return document.getElementById(id);
  }
  function poolApr(p) {
    return Number(p.apr != null ? p.apr : p.apr_pct) || 0;
  }
  function isMomentumHot(p, settings) {
    settings = settings || {};
    var mom = p.momentum || {};
    var tier = String(mom.tier || p.momentum_tier || '').toLowerCase();
    if (tier === 'hot' || tier === 'enter_bias') return true;
    var minScore = Number(
      settings.momentum_hot_min_combined_score != null ? settings.momentum_hot_min_combined_score : 72
    );
    var minApr = Number(settings.momentum_hot_min_apr != null ? settings.momentum_hot_min_apr : 200);
    var sc = mom.combined_score != null ? mom.combined_score : mom.score;
    if (sc != null && Number(sc) >= minScore && poolApr(p) >= minApr) return true;
    return false;
  }
  function sortPoolsForPick(pools, d) {
    var mode = String(((d && d.settings) || {}).lp_selection_mode || 'apr').toLowerCase();
    if (mode === 'momentum') {
      return pools.slice().sort(function (a, b) {
        var ma = a.momentum || {},
          mb = b.momentum || {};
        var sa = Number(ma.combined_score != null ? ma.combined_score : ma.score) || 0;
        var sb = Number(mb.combined_score != null ? mb.combined_score : mb.score) || 0;
        return sb - sa;
      });
    }
    return sortByApr(pools);
  }
  function sortByApr(pools) {
    return pools.slice().sort(function (a, b) {
      return poolApr(b) - poolApr(a);
    });
  }
  function poolIdWithProof(p) {
    var pv = (p && p.pool_verification) || {};
    var tag = String(pv.proof_tag || '').trim();
    var id = String((p && (p.id || p.pool_id)) || '');
    if (!tag) return id;
    return id + ' [' + tag + ']';
  }
  function poolIdCellFromPool(p) {
    var pv = (p && p.pool_verification) || {};
    var id = (p && (p.id || p.pool_id)) || '';
    if (window.LP1Copy) return LP1Copy.cellHtml(LP1Copy.normalizePoolId(id), { proofTag: pv.proof_tag || '' });
    return '<span class="mono">' + esc(poolIdWithProof(p)) + '</span>';
  }

  function renderKpis(el, wc, zone) {
    wc = wc || {};
    var cap = wc.capacity || {};
    var bal = wc.balance || {};
    var sol = bal.sol != null ? Number(bal.sol) : 0;
    if (!isFinite(sol)) sol = 0;
    var mx = cap.max_positions;
    if (zone === 'demo' && cap.simulated_slots != null) mx = cap.simulated_slots;
    var fees = cap.fees_collected_usd;
    var feesStr = fees != null && isFinite(Number(fees)) ? '$' + Number(fees).toFixed(2) : '—';
    var cells = [
      ['SOL', sol.toFixed(4)],
      [zone === 'demo' ? 'sim slots' : 'max pos', mx == null ? '—' : String(mx)],
      ['pos SOL', cap.position_size_sol != null ? String(cap.position_size_sol) : '—'],
      ['reserved', cap.reserved_sol != null ? String(cap.reserved_sol) : '—'],
      ['available', cap.available_sol != null ? num(cap.available_sol) : '—'],
      ['fees collected', feesStr],
    ];
    el.innerHTML = cells
      .map(function (c) {
        return (
          '<div class="k"><span class="l">' +
          esc(c[0]) +
          '</span><span class="v">' +
          esc(c[1]) +
          '</span></div>'
        );
      })
      .join('');
  }

  function renderTradeRows(tbody, rows) {
    rows = rows || [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="muted">No rows in this snapshot.</td></tr>';
      return;
    }
    tbody.innerHTML = rows
      .map(function (p, i) {
        var ix = p.index != null ? p.index : i + 1;
        var st = p.status || p.action || '';
        var fees = p.fees_collected_usd;
        var fStr = fees != null && isFinite(Number(fees)) ? '$' + Number(fees).toFixed(2) : '—';
        return (
          '<tr><td>' +
          ix +
          '</td><td>' +
          esc(p.pair || '') +
          '</td><td>' +
          num(p.apr) +
          '</td><td>' +
          num(p.liquidity_usd) +
          '</td><td>' +
          num(p.volume_24h_usd) +
          '</td><td>' +
          esc(String(st)) +
          '</td><td title="' +
          esc(p.lp_style_key || '') +
          '">' +
          esc(p.lp_style_label || p.lp_placement || '—') +
          '</td><td>' +
          poolIdCellFromPool(p) +
          '</td><td>' +
          esc(fStr) +
          '</td></tr>'
        );
      })
      .join('');
  }

  async function load() {
    $('err').textContent = '';
    if (window.RaydiumMode) await window.RaydiumMode.syncRuntime();
    var r = await fetch('/api/dashboard');
    var t = await r.text();
    var d;
    try {
      d = JSON.parse(t);
    } catch (e) {
      throw new Error(t.slice(0, 200));
    }
    if (!r.ok) throw new Error(d.error || t);
    $('stamp').textContent = (d.generated_at || '?').replace('T', ' ').slice(11, 19) + 'Z';
    renderKpis($('kp-live'), d.live_wallet_capacity || d.wallet_capacity, 'live');
    renderKpis($('kp-demo'), d.demo_wallet_capacity || d.wallet_capacity, 'demo');
    renderTradeRows($('tb-live'), d.live_open_positions || []);
    var demoFeed = d.demo_simulated_trades || [];
    if (!demoFeed.length && (d.demo_open_positions || []).length) demoFeed = d.demo_open_positions;
    renderTradeRows($('tb-demo'), demoFeed);
    var rpc = d.rpc_health || [];
    $('rpcb').innerHTML = rpc.length
      ? rpc
          .map(function (row, i) {
            var ok = row.ok === true || row.ok === 'true' ? 'yes' : 'no';
            var det = String(row.error || '');
            if (!det && row.response) {
              try {
                det = JSON.stringify(row.response).slice(0, 160);
              } catch (e) {
                det = '';
              }
            }
            return (
              '<tr><td>' +
              esc(String(row.index != null ? row.index : i + 1)) +
              '</td><td class="mono">' +
              esc(String(row.url || '')) +
              '</td><td>' +
              esc(ok) +
              '</td><td class="mono">' +
              esc(det) +
              '</td></tr>'
            );
          })
          .join('')
      : '<tr><td colspan="4">No RPC rows.</td></tr>';
    var cand = sortPoolsForPick((d.last_scan && d.last_scan.candidates) || d.open_positions || [], d);
    var settings = (d && d.settings) || {};
    $('tb-cand').innerHTML = cand.length
      ? cand
          .map(function (p) {
            var mom = p.momentum || {};
            var ms = mom.combined_score != null ? mom.combined_score : mom.score;
            var hot = isMomentumHot(p, settings);
            return (
              '<tr' +
              (hot ? ' class="row-mom-hot"' : '') +
              '><td>' +
              esc(
                p.mint_a_symbol && p.mint_b_symbol
                  ? p.mint_a_symbol + '/' + p.mint_b_symbol
                  : p.pair || ''
              ) +
              '</td><td>' +
              num(p.apr) +
              '</td><td>' +
              num(p.liquidity_usd) +
              '</td><td>' +
              num(p.volume_24h_usd) +
              '</td><td>' +
              esc([ms, mom.tier].filter(Boolean).join(' ')) +
              '</td><td>' +
              poolIdCellFromPool(p) +
              '</td></tr>'
            );
          })
          .join('')
      : '<tr><td colspan="6">No candidates.</td></tr>';
  }

  function onModeChange(r) {
    if (r && !r.ok && r.error) $('err').textContent = r.error;
    else $('err').textContent = '';
    load().catch(function (e) {
      $('err').textContent = String(e);
    });
  }

  function wireMode() {
    if (!window.RaydiumMode) {
      $('err').textContent = 'mode_shared.js failed to load — restart dashboard and hard-refresh.';
      return;
    }
    window.RaydiumMode.wireModeButtons(onModeChange);
  }

  var iv = null;
  function arm() {
    clearInterval(iv);
    if ($('auto').checked) {
      iv = setInterval(function () {
        load().catch(function (e) {
          $('err').textContent = String(e);
        });
      }, 4000);
    }
  }

  function boot() {
    wireMode();
    $('auto').onchange = arm;
    load().catch(function (e) {
      $('err').textContent = String(e);
    });
    arm();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
