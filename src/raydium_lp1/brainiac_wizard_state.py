"""Persist Brainiac open-wizard answers (pool id is never saved)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

REPO = Path(__file__).resolve().parents[2]
POOL_PLACEHOLDER = "ENTER_POOL_ADDRESS_HERE"
STATE_PATH = REPO / "config" / "brainiac_wizard_last.json"
EXAMPLE_PATH = REPO / "config" / "brainiac_wizard_last.example.json"
WIZARD_STATE_VERSION = 2

# Shown before each prompt and in --help-fields / example JSON.
FIELD_HELP: dict[str, str] = {
    "pool_id": (
        "Raydium CLMM pool address to open on. Not saved between runs — always starts as "
        "ENTER_POOL_ADDRESS_HERE so you paste a fresh pool each time."
    ),
    "deposit_usd": (
        "Total notional for the LP open in USD. For USDC pools this is USDC; for SOL pools "
        "the executor converts to SOL. SPEND LESS may clamp if wallet/rent caps apply."
    ),
    "fund_non_pay_fraction": (
        "Share of deposit used to Jupiter-swap pay-type → non-pay token before open "
        "(default 0.35 = 35% on deposits under $3). Funds the alt leg for two-sided "
        "wallet_inventory; set skip_fund_swap if you already hold the alt token."
    ),
    "sol_price_usd": (
        "SOL/USD for sizing and USD reports. Enter 0 to use settings (~180). "
        "Do not enter 80 here — that value is Brainiac width % on the next prompt."
    ),
    "wide_width_pct": (
        "Brainiac band width as % of spot (default 80). Skew grid searches within this "
        "width for best 24h price overlap — not Raydium full-range."
    ),
    "min_in_range_factor": (
        "Pre-trade gate: block LIVE if model in-range factor is below this (0–1). "
        "0 = disabled. Example: 0.65 avoids opens when spot is outside the 24h band "
        "even if theoretical APR looks high."
    ),
    "run_pretrade": (
        "Run scripts/_brainiac_pretrade_analysis.py first — wallet headroom, pool TVL, "
        "pay vs non-pay, SPEND LESS, and improvement warnings before spending SOL."
    ),
    "pre_live_consensus_scans": (
        "Before LIVE sign: re-fetch pool this many times (default 5), re-run 80% skew grid "
        "each time, and block if skew is unstable or in-range drops below min_in_range_factor. "
        "Set 0 to disable."
    ),
    "pre_live_scan_delay_sec": (
        "Seconds between consensus pool refreshes (default 2). Total gate time is roughly "
        "(scans - 1) * delay plus API latency."
    ),
    "reset_fee_session": (
        "Clear reports/fee_session_ledger.json before this open so fee-guard attempt "
        "counter does not block after earlier txs in the same session."
    ),
    "skip_fund_swap": (
        "Skip pay→non-pay swap only when wallet already holds enough non-pay for two-sided open. "
        "If short, the system still swaps SOL/USDC -> non-pay automatically."
    ),
    "skip_settle_after": (
        "Do not run post-open junk sweep to pay-type (lp_junk_to_pay / settle_wallet_after_brainiac)."
    ),
    "apply_brainiac_strategy": (
        "Patch config/settings.json (Python): brainiac strategy, mode=live, dry_run=false, "
        "lp_sweep_junk_to_pay_leg=true. Does not use PowerShell set_brainiac_strategy.ps1."
    ),
    "use_auto_live_policy": (
        "When yes, after you enter pool id the wizard applies coded LIVE success defaults "
        "(skip fund on micro deposits, 35% fund fraction if funding, min in-range 0.55, 80% skew grid)."
    ),
    "dry_run_preview_only": (
        "Pretrade + placement plan only; no fund swap and no CLMM sign. Good for checking "
        "skew/ticks and pay-type before typing LIVE."
    ),
}

FieldType = Literal["str", "float", "bool"]


@dataclass(frozen=True)
class WizardFieldSpec:
    key: str
    label: str
    field_type: FieldType
    help_key: str | None = None

    @property
    def description(self) -> str:
        return FIELD_HELP.get(self.help_key or self.key, "")


WIZARD_FIELD_SPECS: tuple[WizardFieldSpec, ...] = (
    WizardFieldSpec(
        "pool_id",
        "Pool ID",
        "str",
    ),
    WizardFieldSpec("deposit_usd", "Deposit USD", "float"),
    WizardFieldSpec(
        "fund_non_pay_fraction",
        "Fund non-pay leg (fraction of deposit)",
        "float",
    ),
    WizardFieldSpec("sol_price_usd", "SOL price USD", "float"),
    WizardFieldSpec("wide_width_pct", "Brainiac width %", "float"),
    WizardFieldSpec("min_in_range_factor", "Min in-range factor (0=off)", "float"),
    WizardFieldSpec("run_pretrade", "Run pre-trade analysis", "bool"),
    WizardFieldSpec("pre_live_consensus_scans", "Pre-LIVE consensus scans (0=off)", "float"),
    WizardFieldSpec("pre_live_scan_delay_sec", "Seconds between consensus scans", "float"),
    WizardFieldSpec("reset_fee_session", "Reset fee session ledger", "bool"),
    WizardFieldSpec("skip_fund_swap", "Skip fund non-pay swap", "bool"),
    WizardFieldSpec("skip_settle_after", "Skip post-open settlement", "bool"),
    WizardFieldSpec("apply_brainiac_strategy", "Apply Brainiac settings (Python)", "bool"),
    WizardFieldSpec("dry_run_preview_only", "Preview only (no on-chain)", "bool"),
    WizardFieldSpec("use_auto_live_policy", "Use coded LIVE success defaults", "bool"),
)


@dataclass
class BrainiacWizardAnswers:
    """User-tunable open parameters (pool_id is prompted separately)."""

    deposit_usd: float = 1.0
    fund_non_pay_fraction: float = 0.35
    sol_price_usd: float = 0.0
    wide_width_pct: float = 80.0
    min_in_range_factor: float = 0.50
    run_pretrade: bool = True
    pre_live_consensus_scans: int = 5
    pre_live_scan_delay_sec: float = 2.0
    reset_fee_session: bool = False
    skip_fund_swap: bool = False
    skip_settle_after: bool = False
    apply_brainiac_strategy: bool = True
    dry_run_preview_only: bool = False
    use_auto_live_policy: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> BrainiacWizardAnswers:
        """Merge saved JSON over class defaults (missing keys use coded defaults)."""
        merged = cls().to_mapping()
        if raw:
            for k in cls.__dataclass_fields__:
                if k in raw and not str(k).startswith("_"):
                    merged[k] = raw[k]
        return cls(**merged)

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def print_field_help_catalog() -> None:
    """Print all field descriptions (for --help-fields)."""
    print("\n=== Brainiac wizard field reference ===\n")
    for spec in WIZARD_FIELD_SPECS:
        print(f"  {spec.label} [{spec.key}]")
        for line in _wrap_text(spec.description, indent=4):
            print(line)
        print()


def _wrap_text(text: str, *, indent: int = 0, width: int = 76) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = " " * indent
    for w in words:
        if len(current) + len(w) + 1 > width and current.strip():
            lines.append(current.rstrip())
            current = " " * indent + w
        else:
            current = current + (" " if current.strip() else "") + w
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _print_field_description(spec: WizardFieldSpec) -> None:
    for line in _wrap_text(spec.description, indent=2):
        print(line)


def load_wizard_state(path: Path | None = None) -> BrainiacWizardAnswers:
    p = path or STATE_PATH
    if not p.is_file():
        return BrainiacWizardAnswers()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if int(raw.get("_wizard_version") or 1) < WIZARD_STATE_VERSION:
            answers = BrainiacWizardAnswers()
            if isinstance(raw.get("deposit_usd"), (int, float)):
                answers.deposit_usd = float(raw["deposit_usd"])
            return normalize_wizard_answers(answers)
        return normalize_wizard_answers(BrainiacWizardAnswers.from_mapping(raw))
    except (OSError, json.JSONDecodeError):
        return BrainiacWizardAnswers()


def apply_auto_policy_to_answers(pool_id: str, answers: BrainiacWizardAnswers) -> BrainiacWizardAnswers:
    """Merge SUPER-BRAINIAC LIVE auto policy after pool id is known."""

    from raydium_lp1.lp_brainiac_cursor_success import resolve_brainiac_live_auto_policy
    from raydium_lp1.lp_selection import fetch_pool_by_id
    from raydium_lp1.scanner import ScannerConfig

    try:
        sc = ScannerConfig.from_file(REPO / "config" / "settings.json")
        pool = fetch_pool_by_id(pool_id.strip(), config=sc)
    except Exception:
        pool = {"id": pool_id}
    auto = resolve_brainiac_live_auto_policy(answers.deposit_usd, pool=pool)
    answers.fund_non_pay_fraction = auto.fund_non_pay_fraction
    answers.skip_fund_swap = auto.skip_fund_swap or auto.prefer_pay_only_open
    answers.skip_settle_after = auto.skip_settle_after
    answers.reset_fee_session = auto.reset_fee_session
    answers.min_in_range_factor = auto.min_in_range_factor
    answers.wide_width_pct = auto.wide_width_pct
    answers.pre_live_consensus_scans = auto.pre_live_consensus_scans
    answers.pre_live_scan_delay_sec = auto.pre_live_scan_delay_sec
    print("\n  === Auto LIVE policy (coded success recipe) ===")
    for line in auto.notes:
        safe = line.replace("\u2192", "->").replace("\u2014", "-")
        print(f"  - {safe}")
    pay_only = " pay_only=True" if auto.prefer_pay_only_open else ""
    print(
        f"  fund={auto.fund_non_pay_fraction:.2f} skip_fund={answers.skip_fund_swap} "
        f"min_ir={auto.min_in_range_factor} reset_ledger={auto.reset_fee_session}{pay_only}\n"
    )
    return answers


def normalize_wizard_answers(answers: BrainiacWizardAnswers) -> BrainiacWizardAnswers:
    """Fix common prompt mistakes (e.g. 80 entered for SOL price instead of width)."""
    sol_px = float(answers.sol_price_usd)
    if sol_px > 50.0:
        # Almost always confused with Brainiac width % — use settings default.
        answers.sol_price_usd = 0.0
    if float(answers.wide_width_pct) < 10.0 or float(answers.wide_width_pct) > 100.0:
        answers.wide_width_pct = 80.0
    frac = float(answers.fund_non_pay_fraction)
    if frac > 1.0:
        answers.fund_non_pay_fraction = frac / 100.0
    answers.fund_non_pay_fraction = max(0.0, min(1.0, float(answers.fund_non_pay_fraction)))
    answers.pre_live_consensus_scans = max(0, int(round(float(answers.pre_live_consensus_scans))))
    answers.pre_live_scan_delay_sec = max(0.0, float(answers.pre_live_scan_delay_sec))
    return answers


def save_wizard_state(answers: BrainiacWizardAnswers, path: Path | None = None) -> Path:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    answers = normalize_wizard_answers(answers)
    body = answers.to_mapping()
    body["_wizard_version"] = WIZARD_STATE_VERSION
    body["_field_descriptions"] = FIELD_HELP
    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return p


def prompt_str(label: str, default: str, *, description: str = "") -> str:
    if description:
        print()
        for line in _wrap_text(description, indent=2):
            print(line)
    hint = f" [{default}]" if default else ""
    raw = input(f"  {label}{hint}: ").strip()
    return raw if raw else default


def prompt_float(label: str, default: float, *, description: str = "") -> float:
    raw = prompt_str(label, str(default), description=description)
    try:
        return float(raw)
    except ValueError:
        return default


def prompt_bool(label: str, default: bool, *, description: str = "") -> bool:
    d = "y" if default else "n"
    raw = prompt_str(f"{label} (y/n)", d, description=description).lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def prompt_pool_id() -> str:
    """Ask for Raydium pool address only (never persisted). Used by ``--live`` without ``--pool``."""

    print("\n=== Brainiac LIVE open (--live) ===\n")
    print("All other settings come from config/brainiac_wizard_last.json + SUPER-BRAINIAC policy.\n")
    spec = WIZARD_FIELD_SPECS[0]
    _print_field_description(spec)
    pool_id = prompt_str(spec.label, POOL_PLACEHOLDER, description=spec.description)
    if pool_id == POOL_PLACEHOLDER:
        print("\n  (Replace placeholder with a real pool id before LIVE.)\n")
    return pool_id.strip()


def _prompt_field(spec: WizardFieldSpec, prev: BrainiacWizardAnswers) -> Any:
    if spec.key == "pool_id":
        return prompt_str(spec.label, POOL_PLACEHOLDER, description=spec.description)
    val = getattr(prev, spec.key)
    if spec.field_type == "float":
        return prompt_float(spec.label, float(val), description="")
    if spec.field_type == "bool":
        return prompt_bool(spec.label, bool(val), description="")
    return prompt_str(spec.label, str(val), description="")


def run_interactive_wizard(
    *,
    pool_id: str | None = None,
    live_mode: bool = False,
) -> tuple[str, BrainiacWizardAnswers]:
    """Return (pool_id, answers). Pool always starts at placeholder unless ``pool_id`` passed."""

    prev = load_wizard_state()
    title = "Brainiac LIVE open wizard (--live)" if live_mode else "Brainiac LIVE open wizard"
    print(f"\n=== {title} ===\n")
    if live_mode:
        print("  All fields below are prompted. On-chain sign runs after (no type-LIVE step).\n")
    print("Core:   src/raydium_lp1/lp_brainiac_cursor_success.py")
    print("Runner: src/raydium_lp1/brainiac_open_runner.py")
    print("CMD:  cd /d C:\\Users\\Taylor\\Raydium-LP1")
    print("      .\\brainiac_wizard.cmd")
    print(f"State:  {STATE_PATH}")
    print("Tip:    python scripts/brainiac_open_wizard.py --help-fields\n")

    if pool_id and pool_id != POOL_PLACEHOLDER:
        print(f"\n  Pool ID (from command line): {pool_id}\n")
    else:
        pool_id = prompt_pool_id()
    print()
    if pool_id == POOL_PLACEHOLDER:
        print("\n  (Replace placeholder with a real pool id before LIVE.)\n")

    kwargs: dict[str, Any] = {}
    for spec in WIZARD_FIELD_SPECS[1:]:
        print()
        _print_field_description(spec)
        kwargs[spec.key] = _prompt_field(spec, prev)

    answers = normalize_wizard_answers(BrainiacWizardAnswers(**kwargs))
    if prev.sol_price_usd > 50 and answers.sol_price_usd == 0:
        print("\n  (Note: reset SOL price USD to 0 — previous save looked like width %, not SOL/USD.)\n")
    if answers.use_auto_live_policy and pool_id != POOL_PLACEHOLDER:
        answers = apply_auto_policy_to_answers(pool_id, answers)
    save_wizard_state(answers)
    print(f"\nSaved wizard defaults to {STATE_PATH} (pool id not saved).\n")
    return pool_id.strip(), answers
