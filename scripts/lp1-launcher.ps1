$ErrorActionPreference = 'Stop'

$root = 'C:\Users\Taylor\Raydium-LP1'
Set-Location $root

$configDir = Join-Path $root 'config'
$active = Join-Path $configDir 'settings.json'
$safe = Join-Path $configDir 'settings.safe.json'
$degen = Join-Path $configDir 'settings.degen.json'

function Use-Profile([string]$name) {
  $src = if ($name -eq 'safe') { $safe } else { $degen }
  if (-not (Test-Path -LiteralPath $src)) {
    throw "Missing profile: $src"
  }
  Copy-Item -Force -LiteralPath $src -Destination $active
  Write-Host "Active profile: $name"
}

while ($true) {
  Write-Host ""
  Write-Host "Raydium-LP1 Launcher"
  Write-Host "1) Safe profile"
  Write-Host "2) Degen profile"
  Write-Host "3) Launch scanner with current settings"
  Write-Host "4) Exit"
  $choice = Read-Host "Choose"

  switch ($choice) {
    '1' { Use-Profile 'safe' }
    '2' { Use-Profile 'degen' }
    '3' {
      $env:PYTHONPATH = (Join-Path $root 'src')
      & python -m raydium_lp1.scanner --dashboard --loop --interval 30 --write-reports --reload-config-each-scan
    }
    '4' { break }
    default { Write-Host "Invalid choice" }
  }
}