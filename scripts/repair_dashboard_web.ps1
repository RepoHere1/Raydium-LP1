# Overwrite dashboard UI files from origin if your tree has merge markers in web/*.html|js
# or stale embedded copies. Run from repo root.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$branch = "cursor/dashboard-tooltips-filter-order-2e5b"
Write-Host "Fetching origin/$branch ..." -ForegroundColor Cyan
git fetch origin $branch
$paths = @(
  "web/dashboard_shell.html",
  "web/dashboard_client.js",
  "src/raydium_lp1/dashboard_web.py"
)
foreach ($p in $paths) {
  Write-Host "Restoring $p from origin/$branch" -ForegroundColor Yellow
  git checkout "origin/$branch" -- $p
}
Write-Host "Done. Restart the dashboard process, then hard-refresh the browser." -ForegroundColor Green
