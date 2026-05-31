"""SUPER-BRAINIAC_POSSIBILITIES — experimental LP fee-capture detective scans."""

from raydium_lp1.super_brainiac.create_pool_analysis import analyze_create_pool_feasibility
from raydium_lp1.super_brainiac.possibilities import (
    BrainiacConfig,
    LOGIC_DOCS,
    load_brainiac_config,
    run_brainiac_cycle,
    scan_brainiac_universe,
    write_brainiac_report,
)

__all__ = [
    "BrainiacConfig",
    "LOGIC_DOCS",
    "analyze_create_pool_feasibility",
    "load_brainiac_config",
    "run_brainiac_cycle",
    "scan_brainiac_universe",
    "write_brainiac_report",
]
