<#
.SYNOPSIS
  Build secrets/lp1_signer.json from WALLET_PRIVATE_KEY and set SOLANA_KEYPAIR_PATH in .env.

.EXAMPLE
  .\scripts\export_keypair.ps1
#>
param(
    [string]$OutPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction Stop; $pyExe = "py"; $pyArgs = @("-3") }
else { $pyExe = "python"; $pyArgs = @() }

$code = @"
import json, sys
from pathlib import Path
from raydium_lp1.wallet_secrets import export_signer_keypair_file
out = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
result = export_signer_keypair_file(out_path=Path(out) if out else None)
print(json.dumps(result, indent=2))
"@
$tmp = Join-Path $env:TEMP "lp1_export_keypair.py"
Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
& $pyExe @pyArgs $tmp $OutPath
Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Next: verify CLMM signer" -ForegroundColor Cyan
Write-Host "  `$env:PYTHONPATH='src'; python -m raydium_lp1.raydium_clmm" -ForegroundColor DarkGray
