# 1. Build the backend executable
Write-Host "1. Building backend executable via PyInstaller..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\backend"
& .\venv\Scripts\pyinstaller --noconfirm photo-gallery-backend.spec

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed!"
    exit $LASTEXITCODE
}

# 2. Copy backend executable to destinations
Write-Host "2. Copying backend executable to sidecar and release paths..." -ForegroundColor Cyan
$BackendSrc = "$PSScriptRoot\backend\dist\photo-gallery-backend.exe"
$TauriBinDir = "$PSScriptRoot\frontend\src-tauri\binaries"
$TauriReleaseDir = "$PSScriptRoot\frontend\src-tauri\target\release"

# Create directories if they don't exist
New-Item -ItemType Directory -Force -Path $TauriBinDir | Out-Null
New-Item -ItemType Directory -Force -Path $TauriReleaseDir | Out-Null

Copy-Item -Path $BackendSrc -Destination "$TauriBinDir\photo-gallery-backend-x86_64-pc-windows-msvc.exe" -Force
Copy-Item -Path $BackendSrc -Destination "$TauriBinDir\photo-gallery-backend.exe" -Force
Copy-Item -Path $BackendSrc -Destination "$TauriReleaseDir\photo-gallery-backend.exe" -Force

# 3. Build the Tauri frontend & package the Tauri app shell (app.exe)
Write-Host "3. Building Tauri frontend and compiling release shell..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\frontend"
npm run tauri build

if ($LASTEXITCODE -ne 0) {
    Write-Error "Tauri build failed!"
    exit $LASTEXITCODE
}

# 4. Build the Inno Setup installer
Write-Host "4. Compiling Inno Setup compiler (ISCC)..." -ForegroundColor Cyan
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

Set-Location -Path "$PSScriptRoot"
Write-Host "SUCCESS: Application CI build & packaging complete!" -ForegroundColor Green
