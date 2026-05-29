<#
.SYNOPSIS
  Proof-of-wiring LIVE CLMM open: ~25¢ (0.002 SOL) into SOL/DEGEN pool.

.EXAMPLE
  .\scripts\export_keypair.ps1
  .\scripts\open_proof_25c.ps1
#>
param(
    [string]$PoolId = "BSPFA8d9qeZdsTubmS6FvriYadx2mzoi6jesauD6hi4e",
    [double]$SolAmount = 0.005
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "open_live_lp.ps1") -PoolId $PoolId -SolAmount $SolAmount
