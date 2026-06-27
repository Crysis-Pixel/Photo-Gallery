# 1. Switch backend to CPU version (required for building clean distribution build)
Write-Host "1. Switching backend virtual environment to CPU version..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\backend"
if (Test-Path "venv") {
    cmd /c rmdir venv
}
cmd /c mklink /J venv venv_cpu

# 2. Build the backend executable
Write-Host "2. Building backend executable via PyInstaller..." -ForegroundColor Cyan
& .\venv\Scripts\pyinstaller --noconfirm photo-gallery-backend.spec

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed!"
    exit $LASTEXITCODE
}

# 3. Copy backend executable to destinations
Write-Host "3. Copying backend executable to sidecar and release paths..." -ForegroundColor Cyan
$BackendSrc = "$PSScriptRoot\backend\dist\photo-gallery-backend.exe"
$TauriBinDir = "$PSScriptRoot\frontend\src-tauri\binaries"
$TauriReleaseDir = "$PSScriptRoot\frontend\src-tauri\target\release"

# Create directories if they don't exist
New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null
New-Item -ItemType Directory -Force -Path $TauriReleaseDir | Out-Null

Copy-Item -Path $BackendSrc -Destination "$TauriBinDir\photo-gallery-backend-x86_64-pc-windows-msvc.exe" -Force
Copy-Item -Path $BackendSrc -Destination "$TauriBinDir\photo-gallery-backend.exe" -Force
Copy-Item -Path $BackendSrc -Destination "$TauriReleaseDir\photo-gallery-backend.exe" -Force

# 4. Build the Tauri frontend & package the Tauri app shell (app.exe)
Write-Host "4. Building Tauri frontend and compiling release shell..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\frontend"
npm run tauri build

if ($LASTEXITCODE -ne 0) {
    Write-Error "Tauri build failed!"
    exit $LASTEXITCODE
}

# 5. Build the Inno Setup installer
Write-Host "5. Compiling Inno Setup compiler (ISCC)..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot"
$ISCC = "$env:LocalAppData\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $ISCC)) {
    $ISCC = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $ISCC)) {
    $ISCC = "C:\Program Files\Inno Setup 6\ISCC.exe"
}

if (Test-Path $ISCC) {
    & $ISCC installer.iss
} else {
    Write-Error "Could not locate ISCC.exe on this system. Please check your Inno Setup installation."
    exit 1
}

# 6. Switch back to GPU version for local development convenience
Write-Host "6. Switching backend virtual environment back to GPU version..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\backend"
if (Test-Path "venv") {
    cmd /c rmdir venv
}
cmd /c mklink /J venv venv_gpu

Set-Location -Path "$PSScriptRoot"
Write-Host "SUCCESS: Application build & packaging complete!" -ForegroundColor Green
