'use strict';
/** Copy-friendly pool IDs + external links (dashboard + positions). */
(function (global) {
  function esc(t) {
    var d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function normalizePoolId(raw) {
    var s = String(raw || '').trim();
    var ix = s.indexOf(' [');
    if (ix >= 0) s = s.slice(0, ix).trim();
    return s;
  }

  function toast(msg) {
    var el = document.getElementById('lp1-copy-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'lp1-copy-toast';
      el.setAttribute('aria-live', 'polite');
      el.style.cssText =
        'position:fixed;bottom:1rem;right:1rem;z-index:9999;padding:.45rem .75rem;' +
        'background:#0f172a;color:#f8fafc;border-radius:8px;font-size:.82rem;' +
        'box-shadow:0 8px 24px rgba(15,23,42,.35);opacity:0;transition:opacity .2s';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(function () {
      el.style.opacity = '0';
    }, 1600);
  }

  function copyText(text) {
    var t = String(text || '');
    if (!t) return Promise.reject(new Error('empty'));
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(t);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement('textarea');
        ta.value = t;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (e) {
        reject(e);
      }
    });
  }

  function cellHtml(poolId, opts) {
    opts = opts || {};
    var id = normalizePoolId(poolId);
    if (!id) return '<span class="muted">—</span>';
    var proof = opts.proofTag ? ' <span class="muted">[' + esc(String(opts.proofTag)) + ']</span>' : '';
    var dex = 'https://dexscreener.com/solana/' + encodeURIComponent(id);
    var ray = 'https://raydium.io/liquidity/increase/?mode=add&pool_id=' + encodeURIComponent(id);
    var sol = 'https://solscan.io/account/' + encodeURIComponent(id);
    return (
      '<span class="pool-id-cell">' +
      '<input type="text" class="pool-id-field" readonly value="' +
      esc(id) +
      '" title="Click to select full pool id" onclick="this.select()"/>' +
      '<button type="button" class="btn-copy" data-copy="' +
      esc(id) +
      '" title="Copy pool id">Copy</button>' +
      '<a class="btn-pool-link" href="' +
      esc(ray) +
      '" target="_blank" rel="noopener" title="Raydium">R</a>' +
      '<a class="btn-pool-link" href="' +
      esc(dex) +
      '" target="_blank" rel="noopener" title="DexScreener">DEX</a>' +
      '<a class="btn-pool-link" href="' +
      esc(sol) +
      '" target="_blank" rel="noopener" title="Solscan">Sol</a>' +
      proof +
      '</span>'
    );
  }

  if (!global._lp1CopyWired) {
    global._lp1CopyWired = true;
    document.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-copy]');
      if (!btn || btn.tagName !== 'BUTTON') return;
      var text = btn.getAttribute('data-copy') || '';
      copyText(text)
        .then(function () {
          toast('Copied pool id');
        })
        .catch(function () {
          toast('Copy failed — select the text field');
        });
    });
  }

  global.LP1Copy = {
    normalizePoolId: normalizePoolId,
    cellHtml: cellHtml,
    copyText: copyText,
  };
})(typeof window !== 'undefined' ? window : globalThis);
