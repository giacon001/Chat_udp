param(
    [string]$PythonExe = ".venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python nao encontrado em '$PythonExe'. Ajuste -PythonExe."
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r requirements-build.txt

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }

& $PythonExe -m PyInstaller --noconfirm chat_p2p.spec

Write-Host "Build concluido. Executavel: dist/chat_p2p.exe"
