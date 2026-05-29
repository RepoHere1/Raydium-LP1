<#
.SYNOPSIS
  Import Solana wallet into .env AND config/settings.json (both stay in sync).

.DESCRIPTION
  Sets:
    WALLET_ADDRESS          (base58 pubkey)
    WALLET_PRIVATE_KEY      (optional; .env only — never committed)
    SOLANA_KEYPAIR_PATH     (optional; Solana CLI JSON array file)

  Also writes wallet_address into config/settings.json for the dashboard/scanner.

.EXAMPLE
  # Interactive (prompts; private key hidden):
  .\scripts\import_wallet.ps1

.EXAMPLE
  # From existing keypair file (derives pubkey automatically):
  .\scripts\import_wallet.ps1 -KeypairPath "$env:USERPROFILE\.config\solana\id.json"

.EXAMPLE
  # Explicit address + keypair path:
  .\scripts\import_wallet.ps1 -Address "YourBase58..." -KeypairPath "C:\keys\mainnet.json"
#>
param(
    [string]$Address = "",
    [string]$KeypairPath = "",
    [switch]$SkipPrivateKeyPrompt
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$env:PYTHONPATH = Join-Path $RepoRoot "src"

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { $pyExe = "py"; $pyArgs = @("-3") } else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Install Python 3 and retry." }
    $pyExe = "python"; $pyArgs = @()
}

function Invoke-WalletSync {
    param(
        [string]$Addr,
        [string]$Priv = "",
        [string]$KpPath = ""
    )
    $code = @"
import json, sys
from raydium_lp1.wallet_secrets import sync_wallet_both, pubkey_from_keypair_file
addr = sys.argv[1].strip()
priv = sys.argv[2].strip()
kp = sys.argv[3].strip()
if not addr and kp:
    addr = pubkey_from_keypair_file(kp)
if not addr:
    raise SystemExit('address required')
out = sync_wallet_both(address=addr, private_key=priv, keypair_path=kp)
print(json.dumps({'ok': True, 'address': addr, 'env_keys': list(out.keys())}))
"@
    $tmp = Join-Path $env:TEMP "lp1_import_wallet.py"
    Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
    & $pyExe @pyArgs $tmp $Addr $Priv $KpPath
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host "Raydium-LP1 wallet import (writes .env + config\settings.json)" -ForegroundColor Cyan

if ($KeypairPath) {
    $KeypairPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KeypairPath)
    if (-not (Test-Path -LiteralPath $KeypairPath)) { throw "Keypair file not found: $KeypairPath" }
}

if (-not $Address -and $KeypairPath) {
    Write-Host "Deriving public key from keypair file..." -ForegroundColor DarkGray
    $pub = & $pyExe @pyArgs -c "import sys; sys.path.insert(0,'src'); from raydium_lp1.wallet_secrets import pubkey_from_keypair_file; print(pubkey_from_keypair_file(sys.argv[1]))" $KeypairPath
    $Address = ($pub | Select-Object -Last 1).Trim()
}

if (-not $Address) {
    $Address = (Read-Host "Solana wallet address (base58 public key)").Trim()
}

$privateKey = ""
if (-not $SkipPrivateKeyPrompt) {
    $ans = Read-Host "Add WALLET_PRIVATE_KEY to .env now? (y/N)"
    if ($ans -match '^[yY]') {
        $sec = Read-Host "Paste private key (base58 or array — input hidden)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try { $privateKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
        }
    }
}

if (-not $KeypairPath) {
    $kpAns = Read-Host "Solana CLI keypair JSON path for SOLANA_KEYPAIR_PATH (Enter to skip)"
    if ($kpAns.Trim()) { $KeypairPath = $kpAns.Trim() }
}

Invoke-WalletSync -Addr $Address -Priv $privateKey -KpPath $KeypairPath

$short = if ($Address.Length -gt 12) { $Address.Substring(0,4) + "..." + $Address.Substring($Address.Length-4) } else { $Address }
Write-Host ""
Write-Host "Done. Wallet $short synced to:" -ForegroundColor Green
Write-Host "  .env                  -> WALLET_ADDRESS (+ optional key fields)"
Write-Host "  config\settings.json  -> wallet_address"
Write-Host ""
Write-Host "Verify:" -ForegroundColor Cyan
Write-Host "  `$env:PYTHONPATH='src'; python -m raydium_lp1.scanner --check-rpc   # prints Wallet: line"
Write-Host "  Or open dashboard -> wallet hint in header"
