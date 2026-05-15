param(
    [string]$Target = "config\settings.json",
    [switch]$ApplyMomentumTemplate,
    [switch]$MergeMissingKeysOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$template = if ($ApplyMomentumTemplate) {
    "config\settings.momentum.example.json"
} else {
    "config\settings.example.json"
}

if (-not (Test-Path $template)) {
    Write-Error "Template not found: $template"
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path $Path)) { return @{} }
    return (Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

$src = Read-JsonFile $template
$dst = Read-JsonFile $Target

if ($dst.Count -eq 0 -and -not (Test-Path $Target)) {
    Write-Host "Creating $Target from $template" -ForegroundColor Green
    Copy-Item $template $Target
    exit 0
}

$merged = @{}
foreach ($prop in $dst.PSObject.Properties) {
    if ($prop.Name -notlike "_*") {
        $merged[$prop.Name] = $prop.Value
    }
}
$added = @()
foreach ($prop in $src.PSObject.Properties) {
    if ($prop.Name -like "_*") { continue }
    if (-not $merged.Contains($prop.Name)) {
        $merged[$prop.Name] = $prop.Value
        $added += $prop.Name
    } elseif (-not $MergeMissingKeysOnly -and $ApplyMomentumTemplate) {
        $merged[$prop.Name] = $prop.Value
    }
}

$configDir = Split-Path -Parent $Target
if ($configDir -and -not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir | Out-Null
}

$merged | ConvertTo-Json -Depth 8 | Set-Content -Path $Target -Encoding UTF8

Write-Host "Updated $Target" -ForegroundColor Green
if ($added.Count -gt 0) {
    Write-Host "Added missing keys: $($added -join ', ')" -ForegroundColor Cyan
}
if ($ApplyMomentumTemplate) {
    Write-Host "Applied momentum template values from $template" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "Git has settings.example.json + settings.momentum.example.json only."
Write-Host "Your scanner reads: $Target (local, not committed)."
