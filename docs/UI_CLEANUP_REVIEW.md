# Dashboard UI cleanup — review list & health notes

Generated for Raydium-LP1 local dashboard (`127.0.0.1:8844`). Use this as a checklist when trimming dead code or hardening the stack.

## Numbered list — redundant / conflicting code to review

1. **`web/dashboard_client.js` (removed)** — Second IIFE block at file bottom (`wireControls`, `mode-live` / `mode-demo`, duplicate `loadSettings`) conflicted with `#btn-mode-demo` / `#btn-mode-live`. **Action:** deleted; only one client bootstrap remains.

2. **`src/raydium_lp1/dashboard_web.py` — `inject_status_strip()` / `top_bar_html()`** — **Removed** in this pass (were unused duplicate top bars).

4. **`scanner.py.bak-*` / `dashboard.py.bak-*` in `src/`** — **Removed**; `*.bak-*` added to `.gitignore`.

5. **`web/index-copy.html`** — **Removed**.

6. **Local `config/settings.json.bak-*`** — Left on disk (user backups); ignored by git via `.gitignore`.

7. **Repo-root `index.html` vs `web/index.html`** — Two landing pages; server serves `web/index.html` at `/index.html`. **Action:** keep one canonical file and link from README only to that path.

8. **`settings.json` path history** — Code now uses `config/settings.json` via `mode_toggle`; old docs may mention repo-root `settings.json`. **Action:** grep docs/scripts for stale paths.

9. **`wallet_capacity` vs `live_wallet_capacity` / `demo_wallet_capacity`** — Legacy field kept for compatibility; UI should prefer split fields. **Action:** eventually deprecate bare `wallet_capacity` in JSON consumers.

10. **`open_positions` vs `live_open_positions` / `demo_simulated_trades`** — `open_positions` can mirror demo trades when no live file exists. **Action:** UI labels must distinguish (done on main dashboard); avoid treating `open_positions` as on-chain fills.

11. **Doctor heal vs `CURSOR_AGENT` / `RAYDIUM_LP1_AI_EDIT`** — Heal intentionally off in agent sandboxes. **Action:** document in stack tab so “doctor not healing” is expected in Cursor.

12. **`RUN_STACK_SCAN_TABS.bat` / `RUN_STACK_SCAN_WINDOWS.bat`** — Overlap with `START_LP1_STACK.bat` / `start_stack_wt.ps1`. **Action:** one launcher in README; mark others deprecated.

## Mode toggle — how it should work

| Control | API | Config |
|--------|-----|--------|
| DEMO / LIVE pills | `POST /api/mode` `{ "mode": "demo" }` or `{ "mode": "live", "confirm": "LIVE" }` | Writes `config/settings.json`: `mode`, `dry_run` |
| Runtime read | `GET /api/runtime` | `mode_toggle.status()` + wallet hint |
| Save settings | `POST /api/settings` | Should keep `mode` in sync when `dry_run` changes (server-side patch) |

**UI:** `body.view-demo` / `body.view-live` highlights the active zone; both LIVE and DEMO data stay on screen.

## Recommendations — script health

1. **Single dashboard client** — Never append a second `<script>` block to `dashboard_client.js`; run `scripts/repair_dashboard_web.ps1` after merges.

2. **Regenerate `reports/dashboard.json` after backend changes** — Old snapshots lack `demo_simulated_trades` / split wallet fields until the scanner runs with `--dashboard`.

3. **Wallet import** — Run `.\scripts\import_wallet.ps1` so LIVE wallet KPIs show non-zero SOL when funded.

4. **Stack smoke test** — `.\scripts\smoke_dashboard.ps1` or manual list in `docs/SMOKE_CHECKLIST.md`.

5. **CI / pre-commit** — Reject files containing `<<<<<<<` in `web/` and `src/raydium_lp1/dashboard_web.py` (already checked in `_page()`).

6. **Remove backup `*.bak-*` from git** — Add `*.bak-*` to `.gitignore` if you still want local backups.

7. **Doctor loop** — Keep monitor tab on `raydium_doctor.py` with heal on; pause heal only during AI edits (`RAYDIUM_LP1_AI_EDIT=1`).

8. **Config reload** — Scanner with `--reload-config-each-scan` so dashboard Save applies on next loop without restart.

## Files changed in this UI pass

- `web/dashboard_shell.html` — unified top bar, dual LIVE/DEMO panels
- `web/dashboard_client.js` — dual wallet/trades, fixed mode toggle, save↔mode sync
- `web/positions.html` — blue tint theme, DEMO/LIVE toggle, dual sections
- `docs/UI_CLEANUP_REVIEW.md` — this document
- `docs/SMOKE_CHECKLIST.md` — manual smoke list
- `scripts/smoke_dashboard.ps1` — automated HTTP smoke
- `.gitignore` — `*.bak-*`, local settings backups
- `src/raydium_lp1/dashboard_web.py` — settings POST uses `mode_toggle.set_mode` for live arm
