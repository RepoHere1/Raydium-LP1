# Wait for dashboard /health then open Dashboard + Positions in default browser.
param(
    [int]$Port = 8844,
    [string]$ListenHost = "127.0.0.1",
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = "SilentlyContinue"
$base = "http://${ListenHost}:$Port"
$health = "$base/health"
$deadline = (Get-Date).AddSeconds($TimeoutSec)

while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 4
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
            Start-Process "$base/"
            Start-Sleep -Milliseconds 500
            Start-Process "$base/positions.html"
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 2
}
exit 1
