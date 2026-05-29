param(
    [string]$KeypairPath = "$env:USERPROFILE\.config\solana\id.json"
)

$ErrorActionPreference = "Stop"
$root = "C:\Users\Taylor\Raydium-LP1"

if (!(Test-Path $KeypairPath)) {
    throw "Keypair file not found: $KeypairPath"
}

$env:SOLANA_KEYPAIR_PATH = (Resolve-Path $KeypairPath).Path
Set-Location $root

python .\wallet_signer.py