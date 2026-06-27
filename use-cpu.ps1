Set-Location -Path "$PSScriptRoot\backend"
if (Test-Path "venv") {
    # Safely remove the junction link without prompting or deleting target files
    cmd /c rmdir venv
}
cmd /c mklink /J venv venv_cpu
Write-Host "Switched backend virtual environment to CPU version (ready for building installer)." -ForegroundColor Green
Set-Location -Path "$PSScriptRoot"