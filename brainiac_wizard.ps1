# Brainiac wizard — PowerShell must use .\ prefix (see about_Command_Precedence)
Set-Location $PSScriptRoot
& "$PSScriptRoot\scripts\brainiac_open_wizard.ps1" @args
exit $LASTEXITCODE
