# Builds dist\FileSh.exe: one file, no console window, runs in the tray.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# Temporary build files go to build\ (git-ignored); the .exe goes to dist\.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$build = Join-Path $root "build"
$icon = Join-Path $build "filesh.ico"
$static = Join-Path $root "app\static"

Push-Location $root
try {
    New-Item -ItemType Directory -Force $build | Out-Null

    # The .exe icon, drawn the same way as the tray icon.
    & $python -c "import sys; from app.tray import make_icon_image; make_icon_image(256).save(sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])" $icon
    if ($LASTEXITCODE -ne 0) { throw "Could not create the icon" }

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name FileSh `
        --icon $icon `
        --add-data "$static;app\static" `
        --collect-submodules uvicorn `
        --collect-submodules websockets `
        --hidden-import app.tray `
        --hidden-import pystray._win32 `
        --specpath $build `
        --workpath $build `
        --distpath (Join-Path $root "dist") `
        FileSh.pyw
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    Write-Host "`nBuilt dist\FileSh.exe"
}
finally {
    Pop-Location
}
