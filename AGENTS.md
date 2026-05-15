# AGENTS.md

## Cursor Cloud specific instructions

This is a pure-Python 3.11+ project with **zero third-party pip dependencies**. Everything uses the Python standard library.

### Quick reference

| Task | Command |
|---|---|
| Run tests | `PYTHONPATH=src python3 -m unittest discover -s tests -v` |
| Run scanner | `PYTHONPATH=src python3 scripts/scan_raydium_lps.py --config config/settings.json` |
| Run scanner + RPC check + reports | `PYTHONPATH=src python3 scripts/scan_raydium_lps.py --config config/settings.json --check-rpc --write-reports` |
| JSON output | Add `--json` to any scanner command |

### Config file setup

Before running the scanner, copy the example configs if they don't exist:

- `cp .env.example .env`
- `cp config/settings.example.json config/settings.json`

Both `.env` and `config/settings.json` are git-ignored.

### Gotchas

- **No linter is configured.** There is no `pyproject.toml`, `ruff.toml`, `.flake8`, or similar. If you need to lint, use `python3 -m py_compile src/raydium_lp1/scanner.py` as a basic syntax check.
- **`PYTHONPATH=src` is required** for both tests and the scanner entry point. The `scripts/scan_raydium_lps.py` wrapper sets `sys.path` itself, but running tests via `unittest discover` needs `PYTHONPATH=src`.
- The scanner requires network access to `https://api-v3.raydium.io` for live data. It will fail with a `RuntimeError` if the API is unreachable.
- One of the three default Solana RPC endpoints (`https://solana.drpc.org`) returns HTTP 400 for `getHealth`. This is expected and does not affect scanner operation.
- The scanner enforces `dry_run=true` and will refuse to start if set to `false`.
