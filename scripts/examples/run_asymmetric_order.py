#!/usr/bin/env python3
"""Example: asymmetric single-asset range (bullish / bearish). Run from repo root with PYTHONPATH=src."""

from raydium_lp1.lp_order_strategies import execute_asymmetric_order

if __name__ == "__main__":
    for label, spot in [("bullish", 2500.0), ("bearish", 2500.0)]:
        band = execute_asymmetric_order(spot, order_type=label, width_pct=5.0)
        print(f"Asymmetric {label} @ spot {spot}: {band['lower']:.4f} .. {band['upper']:.4f}")
