# Stack & dashboard smoke checklist

Use after UI changes or before trusting a live session.

## Start stack

1. **Dashboard only:** `.\RUN_DASHBOARD.bat` or `.\scripts\run_dashboard_web.ps1`
2. **Full stack (scanner + dashboard):** `.\START_LP1_STACK.bat` or `.\scripts\start_stack_wt.ps1`
3. **Replace old process on 8844:** `.\scripts\restart_dashboard.ps1`
4. Wait for `http://127.0.0.1:8844/health` → should return `"service": "raydium-lp1-dashboard"`
5. Smoke: `.\scripts\smoke_dashboard.ps1`

There is **no** `dashboard_web.py` in the repo root. The module is `src\raydium_lp1\dashboard_web.py` — always start via the scripts above or `python -m raydium_lp1.dashboard_web` with `PYTHONPATH=src`.

## Dashboard `/`

- [ ] Single top bar (no duplicate Auto / Reload / Save on the right)
- [ ] DEMO pill active when `config/settings.json` has `"mode": "demo"`
- [ ] Click **LIVE** → prompt → type `LIVE` → stamp and status line show `live`
- [ ] Click **DEMO** → returns to demo without prompt
- [ ] LIVE panel (green) and DEMO panel (blue) both visible; active mode has stronger highlight
- [ ] DEMO trades table has rows after a scan (`demo_simulated_trades`)
- [ ] **Funnel & settings** tab loads; **Save settings** does not error
- [ ] Unchecking **Dry Run** and saving either prompts for LIVE or returns a clear API error (not silent live arm)

## Positions `/positions.html`

- [ ] Blue-tint panels (not black)
- [ ] DEMO/LIVE toggle matches main dashboard
- [ ] Live + demo KPI rows populate after scan

## Scanner data

- [ ] `reports/dashboard.json` exists and is recent
- [ ] Scanner run includes `--dashboard` (and ideally `--reload-config-each-scan`)

## Wallet (optional)

- [ ] `.\scripts\import_wallet.ps1` if you need non-zero SOL on LIVE wallet KPIs

## Doctor

- [ ] Doctor tab running; `reports/doctor_report.json` updates after scan
- [ ] Heal paused only when `RAYDIUM_LP1_AI_EDIT=1` or Cursor agent env is set
