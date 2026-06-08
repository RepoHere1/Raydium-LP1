"""
Native Raydium-LP1 dashboard (tkinter).

Replaces the browser UI at http://127.0.0.1:8844/ by calling the same Python
modules the HTTP server uses — no HTML/JS required.

Launch::

    py -3 -m raydium_lp1.dashboard_gui
    .\\scripts\\launch_dashboard_gui.ps1
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog, ttk
import tkinter as tk
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = REPO_ROOT / "config" / "settings.json"
DEFAULT_DASHBOARD = REPO_ROOT / "reports" / "dashboard.json"
REFRESH_MS = 4000


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S UTC")


def _load_dashboard_payload(settings_path: Path, dashboard_path: Path) -> dict[str, Any]:
    if not dashboard_path.is_file():
        return {"error": f"Missing {dashboard_path} — run a scan first."}
    data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    from raydium_lp1.dashboard_enrich import enrich_dashboard_payload

    return enrich_dashboard_payload(data, settings_path)


def _settings_to_form_values(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    urls = raw.get("solana_rpc_urls") or []
    if isinstance(urls, list):
        out["solana_rpc_urls_lines"] = "\n".join(str(u) for u in urls)
    mints = raw.get("blocked_mints") or []
    if isinstance(mints, list):
        out["blocked_mints_lines"] = "\n".join(str(m) for m in mints)
    aq = raw.get("allowed_quote_symbols") or []
    if isinstance(aq, list):
        out["allowed_quote_symbols_csv"] = ", ".join(str(s) for s in aq)
    bt = raw.get("blocked_token_symbols") or []
    if isinstance(bt, list):
        out["blocked_token_symbols_csv"] = ", ".join(str(s) for s in bt)
    widths = raw.get("lp_range_width_candidates")
    if widths is not None:
        out["lp_range_width_candidates_json"] = json.dumps(widths)
    routes = raw.get("route_sources")
    if routes is not None:
        out["route_sources_json"] = json.dumps(routes)
    return out


def _collect_settings_patch(widgets: dict[str, tk.Widget]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, w in widgets.items():
        if key == "route_sources_json":
            patch["route_sources"] = json.loads(_wtext(w) or "[]")
            continue
        if key == "lp_range_width_candidates_json":
            arr = json.loads(_wtext(w) or "[]")
            if not isinstance(arr, list):
                raise ValueError("lp_range_width_candidates must be a JSON array")
            patch["lp_range_width_candidates"] = [float(x) for x in arr]
            continue
        if key == "solana_rpc_urls_lines":
            patch["solana_rpc_urls"] = [ln.strip() for ln in _wtext(w).splitlines() if ln.strip()]
            continue
        if key == "blocked_mints_lines":
            patch["blocked_mints"] = [ln.strip() for ln in _wtext(w).splitlines() if ln.strip()]
            continue
        if key == "allowed_quote_symbols_csv":
            patch["allowed_quote_symbols"] = [
                s.strip().upper() for s in _wtext(w).split(",") if s.strip()
            ]
            continue
        if key == "blocked_token_symbols_csv":
            patch["blocked_token_symbols"] = [
                s.strip().upper() for s in _wtext(w).split(",") if s.strip()
            ]
            continue
        if isinstance(w, tk.BooleanVar):
            patch[key] = bool(w.get())
            continue
        if isinstance(w, ttk.Combobox):
            patch[key] = w.get()
            continue
        val = _wtext(w).strip()
        if not val and key not in ("lp_pay_prefer_symbol", "lp_range_mode", "mode"):
            continue
        if key.endswith("_sol") or "pct" in key or "fraction" in key or key in (
            "min_apr", "page_size", "pages", "min_liquidity_usd", "min_volume_24h_usd",
            "max_position_usd", "position_size_sol", "reserve_sol", "demo_paper_sol",
            "lp_fee_bps", "lp_default_range_width_pct", "lp_max_positions_per_mint",
            "scan_loop_interval_seconds", "dashboard_port", "min_clmm_deposit_sol",
            "max_priority_fee_micro_lamports", "max_open_retries", "max_session_spend_sol",
            "max_fee_pct_of_deposit", "clmm_open_rent_sol", "lp_pay_funding_buffer_pct",
            "lp_pay_funding_dust_usd", "lp_pay_funding_slippage_bps", "lp_pay_funding_sol_price_usd",
            "lp_close_trash_swap_attempts",
            "manual_live_min_pool_liquidity_usd",
            "manual_live_max_route_price_impact_pct",
            "super_brainiac_min_liquidity_usd",
            "super_brainiac_deposit_usd",
            "super_brainiac_target_apr_pct",
            "super_brainiac_prefer_fee_pct_min",
            "super_brainiac_prefer_fee_pct_max",
            "super_brainiac_min_confidence",
            "super_brainiac_continuous_interval_sec",
        ):
            try:
                patch[key] = float(val) if "." in val else int(val)
            except ValueError:
                patch[key] = val
            continue
        patch[key] = val
    return patch


def _wtext(w: tk.Widget) -> str:
    if isinstance(w, (tk.Entry, ttk.Combobox)):
        return w.get()
    if isinstance(w, scrolledtext.ScrolledText):
        return w.get("1.0", "end-1c")
    return ""


class RaydiumDashboardGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Raydium-LP1 Dashboard")
        self.geometry("1280x860")
        self.minsize(960, 640)

        self.settings_path = DEFAULT_SETTINGS
        self.dashboard_path = DEFAULT_DASHBOARD
        self._auto = tk.BooleanVar(value=True)
        self._refresh_timer: str | None = None
        self._setting_widgets: dict[str, tk.Widget] = {}
        self._last_dash: dict[str, Any] = {}
        self._tune_checks: dict[str, tk.BooleanVar] = {}

        self._build_chrome()
        self._build_tabs()
        self.status_var = tk.StringVar(value="Starting…")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=8, pady=(0, 6)
        )
        self.after(200, self._initial_load)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_chrome(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)

        ttk.Label(bar, text="Raydium-LP1", font=("", 12, "bold")).pack(side="left")
        self._mode_var = tk.StringVar(value="demo")
        ttk.Button(bar, text="DRY_RUN", command=lambda: self._set_mode("demo")).pack(side="left", padx=4)
        ttk.Button(bar, text="LIVE", command=lambda: self._set_mode_live()).pack(side="left", padx=2)
        ttk.Button(bar, text="APR pick", command=lambda: self._set_lp_pick("apr")).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="MoM HOT", command=lambda: self._set_lp_pick("momentum")).pack(side="left", padx=2)
        ttk.Checkbutton(bar, text="Auto 4s", variable=self._auto, command=self._arm_timer).pack(side="left", padx=12)
        ttk.Button(bar, text="Reload", command=self.refresh).pack(side="left", padx=2)
        ttk.Button(bar, text="Save settings", command=self.save_settings).pack(side="left", padx=2)
        ttk.Button(bar, text="Run scan", command=self.run_scan).pack(side="left", padx=8)
        ttk.Button(bar, text="Open top LIVE", command=self.live_open).pack(side="left", padx=2)

        self._stamp_var = tk.StringVar(value="…")
        ttk.Label(bar, textvariable=self._stamp_var).pack(side="right", padx=4)

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=4)

        self.tab_pos = ttk.Frame(self.notebook)
        self.tab_funnel = ttk.Frame(self.notebook)
        self.tab_raw = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_pos, text="Positions")
        self.notebook.add(self.tab_funnel, text="Funnel & settings")
        self.notebook.add(self.tab_raw, text="Raw JSON")

        self._build_positions_tab()
        self._build_funnel_tab()
        self.raw_text = scrolledtext.ScrolledText(self.tab_raw, font=("Consolas", 10))
        self.raw_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_positions_tab(self) -> None:
        outer = ttk.Frame(self.tab_pos)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.pos_inner = ttk.Frame(canvas)
        self.pos_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.pos_inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        def _sections() -> list[tuple[str, str]]:
            return [
                ("live_wallet", "LIVE wallet"),
                ("live_trades", "LIVE trades"),
                ("demo_wallet", "DRY_RUN wallet"),
                ("demo_trades", "DRY_RUN paper trades"),
                ("candidates", "Candidate pools"),
                ("momentum", "Momentum HOT"),
                ("anomalies", "ANOMALIES (CASH)"),
                ("closed", "Closed positions"),
                ("alerts", "Recent alerts"),
                ("rpc", "RPC health"),
            ]

        self._pos_trees: dict[str, ttk.Treeview] = {}
        for key, title in _sections():
            lf = ttk.LabelFrame(self.pos_inner, text=title)
            lf.pack(fill="x", padx=4, pady=6)
            if key in ("live_wallet", "demo_wallet"):
                self._pos_trees[key] = None  # type: ignore
                lbl = ttk.Label(lf, text="(loading)", wraplength=1100, justify="left")
                lbl.pack(anchor="w", padx=6, pady=4)
                setattr(self, f"_lbl_{key}", lbl)
                continue
            cols = self._columns_for(key)
            tree = ttk.Treeview(lf, columns=cols, show="headings", height=5)
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, width=100, minwidth=60)
            vsb = ttk.Scrollbar(lf, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=vsb.set)
            tree.pack(side="left", fill="x", expand=True, padx=4, pady=4)
            vsb.pack(side="right", fill="y")
            self._pos_trees[key] = tree

    def _columns_for(self, key: str) -> tuple[str, ...]:
        maps = {
            "live_trades": ("pair", "style", "pool", "nft", "fees", "opened"),
            "demo_trades": ("pair", "style", "pool", "fees", "opened"),
            "candidates": ("pair", "apr", "tvl", "vol24", "health", "mom", "pool"),
            "momentum": ("pair", "score", "apr", "tvl", "pool"),
            "anomalies": ("pair", "apr", "cash24", "impl_apr", "tags", "pool"),
            "closed": ("pair", "pool", "closed"),
            "alerts": ("time", "pair", "severity", "action"),
            "rpc": ("url", "ok", "latency"),
        }
        return maps.get(key, ("col1", "col2"))

    def _build_funnel_tab(self) -> None:
        paned = ttk.PanedWindow(self.tab_funnel, orient="vertical")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        top = ttk.Frame(paned)
        paned.add(top, weight=1)
        tune_lf = ttk.LabelFrame(top, text="Scan · Tune · Doctor")
        tune_lf.pack(fill="both", expand=True, padx=2, pady=2)
        btn_row = ttk.Frame(tune_lf)
        btn_row.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_row, text="Apply checked tune", command=self.apply_tune_selected).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Apply all tune", command=self.apply_tune_all).pack(side="left", padx=2)
        self.tune_summary = ttk.Label(tune_lf, text="", wraplength=1000, justify="left")
        self.tune_summary.pack(anchor="w", padx=6, pady=2)
        self.tune_frame = ttk.Frame(tune_lf)
        self.tune_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.doctor_text = scrolledtext.ScrolledText(tune_lf, height=8, font=("Segoe UI", 9))
        self.doctor_text.pack(fill="x", padx=4, pady=4)

        funnel_lf = ttk.LabelFrame(top, text="Scan funnel (last_scan)")
        funnel_lf.pack(fill="x", padx=2, pady=4)
        self.funnel_text = scrolledtext.ScrolledText(funnel_lf, height=10, font=("Consolas", 9))
        self.funnel_text.pack(fill="both", expand=True, padx=4, pady=4)

        settings_outer = ttk.LabelFrame(paned, text="Settings (config/settings.json)")
        paned.add(settings_outer, weight=2)
        sc = tk.Canvas(settings_outer, highlightthickness=0)
        sb = ttk.Scrollbar(settings_outer, orient="vertical", command=sc.yview)
        self.settings_inner = ttk.Frame(sc)
        self.settings_inner.bind("<Configure>", lambda e: sc.configure(scrollregion=sc.bbox("all")))
        sc.create_window((0, 0), window=self.settings_inner, anchor="nw")
        sc.configure(yscrollcommand=sb.set)
        sc.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._build_settings_form()

    def _build_settings_form(self) -> None:
        from raydium_lp1.dashboard_web import _FORM_SECTIONS
        from raydium_lp1.lp_strategy_guide import strategy_cards_for_ui

        strategies = [c.get("id", "") for c in strategy_cards_for_ui()]
        row = 0
        for sec in _FORM_SECTIONS:
            ttk.Label(self.settings_inner, text=sec.get("title", ""), font=("", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(10, 4)
            )
            row += 1
            for fld in sec.get("fields") or []:
                key = str(fld.get("key") or "")
                if not key:
                    continue
                ttk.Label(self.settings_inner, text=str(fld.get("label") or key)).grid(
                    row=row, column=0, sticky="nw", padx=6, pady=2
                )
                ftype = fld.get("type") or "text"
                w: tk.Widget
                if ftype == "checkbox":
                    var = tk.BooleanVar()
                    w = ttk.Checkbutton(self.settings_inner, variable=var)
                    self._setting_widgets[key] = var
                elif ftype == "select":
                    opts = fld.get("options") or []
                    w = ttk.Combobox(self.settings_inner, values=list(opts), width=36)
                    self._setting_widgets[key] = w
                elif ftype == "strategy_picker":
                    w = ttk.Combobox(self.settings_inner, values=strategies, width=36)
                    self._setting_widgets[key] = w
                elif ftype in ("lines", "json_text"):
                    w = scrolledtext.ScrolledText(self.settings_inner, height=3, width=48, font=("Consolas", 9))
                    self._setting_widgets[key] = w
                elif ftype == "number":
                    w = ttk.Entry(self.settings_inner, width=40)
                    self._setting_widgets[key] = w
                else:
                    w = ttk.Entry(self.settings_inner, width=40)
                    self._setting_widgets[key] = w
                w.grid(row=row, column=1, sticky="ew", padx=6, pady=2)
                row += 1
        self.settings_inner.columnconfigure(1, weight=1)

    def _populate_settings_form(self, raw: dict[str, Any]) -> None:
        vals = _settings_to_form_values(raw)
        for key, w in self._setting_widgets.items():
            v = vals.get(key)
            if isinstance(w, tk.BooleanVar):
                w.set(bool(v))
            elif isinstance(w, scrolledtext.ScrolledText):
                w.delete("1.0", "end")
                if v is not None:
                    w.insert("1.0", str(v) if not isinstance(v, (list, dict)) else json.dumps(v, indent=0))
            elif isinstance(w, ttk.Combobox):
                w.set(str(v) if v is not None else "")
            else:
                w.delete(0, "end")
                if v is not None:
                    w.insert(0, str(v))

    def _async(self, fn: Callable[[], Any], done: Callable[[Exception | None, Any], None]) -> None:
        def work() -> None:
            try:
                result = fn()
                self.after(0, lambda: done(None, result))
            except Exception as exc:
                self.after(0, lambda: done(exc, None))

        threading.Thread(target=work, daemon=True).start()

    def _initial_load(self) -> None:
        self.refresh()
        self._load_settings()
        self._arm_timer()

    def _arm_timer(self) -> None:
        if self._refresh_timer:
            self.after_cancel(self._refresh_timer)
            self._refresh_timer = None
        if self._auto.get():
            self._refresh_timer = self.after(REFRESH_MS, self._tick)

    def _tick(self) -> None:
        self.refresh(quiet=True)
        self._arm_timer()

    def _on_close(self) -> None:
        if self._refresh_timer:
            self.after_cancel(self._refresh_timer)
        self.destroy()

    def refresh(self, *, quiet: bool = False) -> None:
        if not quiet:
            self.status_var.set("Refreshing…")

        def work() -> dict[str, Any]:
            dash = _load_dashboard_payload(self.settings_path, self.dashboard_path)
            from raydium_lp1.tune_advisor import build_tune_plan
            from raydium_lp1.doctor_advisor import build_doctor_report

            tune = build_tune_plan(
                latest_path=self.dashboard_path.parent / "latest.json",
                settings_path=self.settings_path,
            )
            doctor = build_doctor_report(
                settings_path=self.settings_path,
                latest_path=self.dashboard_path.parent / "latest.json",
                include_structural=True,
            )
            from raydium_lp1 import mode_toggle
            from raydium_lp1.doctor_advisor import _wallet_runtime

            runtime = {**mode_toggle.status(), "wallet": _wallet_runtime()}
            return {"dashboard": dash, "tune": tune, "doctor": doctor, "runtime": runtime}

        def done(exc: Exception | None, payload: Any) -> None:
            if exc:
                self.status_var.set(f"Error: {exc}")
                if not quiet:
                    messagebox.showerror("Refresh failed", str(exc))
                return
            assert isinstance(payload, dict)
            self._apply_payload(payload)
            mode = str((payload.get("runtime") or {}).get("mode") or "demo").lower()
            self._mode_var.set(mode)
            self._stamp_var.set(f"{mode.upper()} · {_now_stamp()}")
            self.status_var.set(f"Updated {_now_stamp()}")

        self._async(work, done)

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        dash = payload.get("dashboard") or {}
        if dash.get("error"):
            self.status_var.set(str(dash["error"]))
        self._last_dash = dash
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", json.dumps(dash, indent=2, default=str))

        self._fill_wallet("live_wallet", dash.get("live_wallet_capacity") or dash.get("wallet_capacity"))
        self._fill_wallet("demo_wallet", dash.get("demo_wallet_capacity"))
        self._fill_tree("live_trades", self._rows_trades(dash.get("live_open_positions") or []))
        self._fill_tree("demo_trades", self._rows_trades(dash.get("demo_simulated_trades") or []))
        ls = dash.get("last_scan") or {}
        self._fill_tree("candidates", self._rows_candidates(ls.get("candidates") or ls.get("top_candidates") or []))
        self._fill_tree("momentum", self._rows_momentum(dash.get("momentum_hot_top") or []))
        self._fill_tree("anomalies", self._rows_anomalies((dash.get("cash_anomalies") or {}).get("rows") or []))
        self._fill_tree("closed", self._rows_closed(dash.get("demo_closed_positions") or []))
        self._fill_tree("alerts", self._rows_alerts(dash.get("recent_alerts") or []))
        self._fill_tree("rpc", self._rows_rpc(dash.get("rpc_health") or []))

        funnel = ls.get("funnel") or ls
        self.funnel_text.delete("1.0", "end")
        self.funnel_text.insert("1.0", json.dumps(funnel, indent=2, default=str)[:12000])

        self._render_tune(payload.get("tune") or {})
        doc = payload.get("doctor") or {}
        self.doctor_text.delete("1.0", "end")
        lines = [str(doc.get("objective") or "")]
        for rec in doc.get("recommendations") or []:
            if isinstance(rec, dict):
                lines.append(f"\n• {rec.get('title', '')} [{rec.get('risk', '')}]\n  {rec.get('detail', '')}")
        self.doctor_text.insert("1.0", "\n".join(lines))

    def _fill_wallet(self, key: str, cap: dict[str, Any] | None) -> None:
        lbl = getattr(self, f"_lbl_{key}", None)
        if not isinstance(lbl, ttk.Label):
            return
        if not cap:
            lbl.config(text="(no data)")
            return
        bal = (cap.get("balance") or {})
        c = cap.get("capacity") or {}
        w = cap.get("wallet") or {}
        lbl.config(
            text=(
                f"Address: {w.get('address', '?')}\n"
                f"SOL: {bal.get('sol', '?')} · slots: {c.get('max_positions', '?')} · "
                f"reserve: {c.get('reserve_sol', '?')}"
            )
        )

    def _fill_tree(self, key: str, rows: list[tuple]) -> None:
        tree = self._pos_trees.get(key)
        if tree is None:
            return
        for iid in tree.get_children():
            tree.delete(iid)
        for row in rows:
            tree.insert("", "end", values=row)

    def _rows_trades(self, rows: list[dict]) -> list[tuple]:
        out = []
        for r in rows:
            out.append((
                r.get("pair", ""),
                r.get("lp_style_label") or r.get("lp_strategy_id", ""),
                (str(r.get("pool_id") or ""))[:12] + "…",
                (str(r.get("position_nft_mint") or ""))[:10] + "…",
                r.get("fees_usd_est", ""),
                (str(r.get("opened_at") or ""))[:19],
            ))
        return out

    def _rows_candidates(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            mom = r.get("momentum") or {}
            out.append((
                f"{r.get('mint_a_symbol','?')}/{r.get('mint_b_symbol','?')}",
                r.get("apr", ""),
                r.get("liquidity_usd", ""),
                r.get("volume_24h_usd", ""),
                (r.get("health") or {}).get("severity", ""),
                mom.get("combined_score", ""),
                (str(r.get("id") or ""))[:16],
            ))
        return out

    def _rows_momentum(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append((
                f"{r.get('mint_a_symbol','?')}/{r.get('mint_b_symbol','?')}",
                r.get("combined_score", r.get("momentum_score", "")),
                r.get("apr", ""),
                r.get("liquidity_usd", ""),
                (str(r.get("id") or ""))[:16],
            ))
        return out

    def _rows_anomalies(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            tags = ", ".join((r.get("anomaly_tags") or [])[:3])
            out.append((
                r.get("pair", ""),
                r.get("apr", r.get("reported_apr", "")),
                r.get("fee_24h_usd", ""),
                r.get("implied_apr", ""),
                tags,
                (str(r.get("pool_id") or r.get("id") or ""))[:16],
            ))
        return out

    def _rows_closed(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append((r.get("pair", ""), (str(r.get("pool_id") or ""))[:16], (str(r.get("closed_at") or ""))[:19]))
        return out

    def _rows_alerts(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append((
                (str(r.get("timestamp") or ""))[:19],
                r.get("pair", ""),
                r.get("severity", ""),
                r.get("action", ""),
            ))
        return out

    def _rows_rpc(self, rows: list) -> list[tuple]:
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append((r.get("url", r.get("rpc", "")), r.get("ok", ""), r.get("latency_ms", "")))
        return out

    def _render_tune(self, plan: dict[str, Any]) -> None:
        for w in self.tune_frame.winfo_children():
            w.destroy()
        self._tune_checks.clear()
        if plan.get("error"):
            self.tune_summary.config(text=str(plan["error"]))
            return
        lr = plan.get("live_readiness") or {}
        sum_ = plan.get("scan_summary") or {}
        self.tune_summary.config(
            text=(
                f"Scanned {sum_.get('scanned','?')} · candidates {sum_.get('candidates','?')} · "
                f"rejected {sum_.get('rejected','?')} · "
                f"LIVE ready: {'yes' if lr.get('ready_to_sign') else 'NO'}"
            )
        )
        for it in plan.get("items") or []:
            if not isinstance(it, dict):
                continue
            var = tk.BooleanVar(value=bool(it.get("default_checked")))
            self._tune_checks[str(it.get("id") or "")] = var
            ttk.Checkbutton(
                self.tune_frame,
                text=f"{it.get('title', '')} — {it.get('detail', '')}",
                variable=var,
            ).pack(anchor="w", padx=4, pady=2)

    def _load_settings(self) -> None:
        def work() -> dict[str, Any]:
            from raydium_lp1.settings_io import load_settings_json

            return load_settings_json(self.settings_path)

        def done(exc: Exception | None, raw: Any) -> None:
            if exc:
                messagebox.showerror("Settings", str(exc))
                return
            self._populate_settings_form(raw if isinstance(raw, dict) else {})

        self._async(work, done)

    def save_settings(self) -> None:
        try:
            patch = _collect_settings_patch(self._setting_widgets)
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))
            return
        if patch.get("dry_run") is False or str(patch.get("mode", "")).lower() == "live":
            if not messagebox.askokcancel("LIVE mode", "Type OK only if you intend LIVE.\nConfirm arming LIVE on save?"):
                return

        def work() -> Any:
            from raydium_lp1.dashboard_web import _apply_settings_mode_change, _normalize_settings_mode_patch
            from raydium_lp1.settings_io import load_settings_json, merge_known_settings_patch

            pk = _normalize_settings_mode_patch(patch)
            pk, mode_result = _apply_settings_mode_change(
                self.settings_path, pk, source="dashboard_gui"
            )
            if pk:
                merge_known_settings_patch(self.settings_path, pk)
            return {"mode_result": mode_result, "settings": load_settings_json(self.settings_path)}

        def done(exc: Exception | None, result: Any) -> None:
            if exc:
                messagebox.showerror("Save failed", str(exc))
                return
            messagebox.showinfo("Saved", "Settings saved.")
            if isinstance(result, dict) and isinstance(result.get("settings"), dict):
                self._populate_settings_form(result["settings"])
            self.refresh()

        self.status_var.set("Saving settings…")
        self._async(work, done)

    def _set_mode(self, mode: str) -> None:
        def work() -> Any:
            from raydium_lp1 import mode_toggle

            return mode_toggle.set_mode(mode, source="dashboard_gui")

        def done(exc: Exception | None, r: Any) -> None:
            if exc:
                messagebox.showerror("Mode", str(exc))
                return
            self._mode_var.set(mode)
            self.refresh()

        self._async(work, done)

    def _set_mode_live(self) -> None:
        confirm = simpledialog.askstring("LIVE", "Type LIVE to arm live mode:", parent=self)
        if confirm != "LIVE":
            return

        def work() -> Any:
            from raydium_lp1 import mode_toggle

            return mode_toggle.set_mode("live", confirm="LIVE", source="dashboard_gui")

        def done(exc: Exception | None, r: Any) -> None:
            if exc:
                messagebox.showerror("Mode", str(exc))
                return
            self._mode_var.set("live")
            self.refresh()

        self._async(work, done)

    def _set_lp_pick(self, mode: str) -> None:
        def work() -> Any:
            from raydium_lp1.settings_io import merge_known_settings_patch

            merge_known_settings_patch(self.settings_path, {"lp_selection_mode": mode})
            return mode

        def done(exc: Exception | None, _: Any) -> None:
            if exc:
                messagebox.showerror("LP pick", str(exc))
            else:
                self.status_var.set(f"LP selection → {mode}")
                self.refresh()

        self._async(work, done)

    def run_scan(self) -> None:
        def work() -> dict[str, Any]:
            from raydium_lp1.dashboard_scan_runner import start_dashboard_scan

            return start_dashboard_scan(write_rejections=True)

        def done(exc: Exception | None, r: Any) -> None:
            if exc:
                messagebox.showerror("Scan", str(exc))
                return
            if isinstance(r, dict) and not r.get("ok"):
                messagebox.showwarning("Scan", r.get("error") or "Scan not started")
                return
            self.status_var.set("Scan started — watch status…")
            self._poll_scan()

        self.status_var.set("Starting scan…")
        self._async(work, done)

    def _poll_scan(self) -> None:
        def work() -> dict[str, Any]:
            from raydium_lp1.dashboard_scan_runner import scan_status

            return scan_status()

        def done(exc: Exception | None, st: Any) -> None:
            if exc or not isinstance(st, dict):
                return
            if st.get("running"):
                self.status_var.set("Scan running…")
                self.after(2500, self._poll_scan)
                return
            if st.get("exit_code") == 0:
                self.status_var.set("Scan complete")
                self.refresh()
            else:
                self.status_var.set(st.get("error") or "Scan failed")

        self._async(work, done)

    def apply_tune_selected(self) -> None:
        ids = [tid for tid, var in self._tune_checks.items() if var.get()]
        self._apply_tune(ids)

    def apply_tune_all(self) -> None:
        from raydium_lp1.tune_advisor import build_tune_plan

        plan = build_tune_plan(
            latest_path=self.dashboard_path.parent / "latest.json",
            settings_path=self.settings_path,
        )
        ids = [
            str(it["id"])
            for it in (plan.get("items") or [])
            if isinstance(it, dict) and it.get("settings_patch")
        ]
        self._apply_tune(ids)

    def _apply_tune(self, ids: list[str]) -> None:
        def work() -> Any:
            from raydium_lp1.tune_advisor import apply_tune_items

            return apply_tune_items(
                self.settings_path,
                ids,
                latest_path=self.dashboard_path.parent / "latest.json",
            )

        def done(exc: Exception | None, r: Any) -> None:
            if exc:
                messagebox.showerror("Tune", str(exc))
                return
            applied = (r.get("applied_ids") if isinstance(r, dict) else None) or ids
            messagebox.showinfo("Tune", f"Applied {len(applied)} item(s)")
            self._load_settings()
            self.refresh()

        self._async(work, done)

    def live_open(self) -> None:
        confirm = simpledialog.askstring("LIVE open", "Type LIVE to open top CLMM candidate:", parent=self)
        if confirm != "LIVE":
            return

        def work() -> dict[str, Any]:
            from raydium_lp1.lp_live_router import execute_strategy_live_open
            from raydium_lp1.settings_io import load_settings_json

            settings = load_settings_json(REPO_ROOT / "config" / "settings.json")
            return execute_strategy_live_open(
                strategy_id=str(settings.get("lp_active_strategy") or ""),
                fee_guard_settings=settings,
            )

        def done(exc: Exception | None, r: Any) -> None:
            if exc:
                messagebox.showerror("Open failed", str(exc))
                return
            if isinstance(r, dict) and r.get("ok"):
                messagebox.showinfo("Open", "Position opened — see LIVE trades.")
            else:
                err = (r or {}).get("error") if isinstance(r, dict) else str(r)
                if isinstance(r, dict) and r.get("manual_live_blocked"):
                    note = r.get("notification") or ""
                    err = f"{err}\n\nAlert logged: {note}" if note else str(err)
                messagebox.showerror("Open failed", err)
            self.refresh()

        self.status_var.set("Opening CLMM…")
        self._async(work, done)


def main() -> int:
    app = RaydiumDashboardGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
