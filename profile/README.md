# Raydium-LP1

Dry-run-first tooling for scanning Raydium liquidity pools, identifying extreme APR candidates, and applying local safety filters before any future LP-opening automation is considered.

The current build only scans and reports candidates; it does not trade, sign transactions, or request wallet secrets.


## Beginner note

This repo is named Raydium-LP1. It is currently a dry-run scanner only: it reads live pool data, applies filters, and prints candidates. It does not buy or open LP positions.
