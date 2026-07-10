$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        throw "Python 3.12 이상이 필요합니다."
    }
    & $systemPython.Source -m venv venv
}

& $python -m pip install -r requirements.txt

function Install-StockfishArchive($url, $zipPath, $extractPath) {
    New-Item -ItemType Directory -Force (Split-Path $zipPath) | Out-Null
    Invoke-WebRequest `
        -Uri $url `
        -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Remove-Item -LiteralPath $zipPath
}

$stockfishAvx2 = Join-Path $projectRoot "tools\stockfish\stockfish\stockfish-windows-x86-64-avx2.exe"
if (-not (Test-Path $stockfishAvx2)) {
    Install-StockfishArchive `
        "https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-avx2.zip" `
        (Join-Path $projectRoot "tools\stockfish.zip") `
        (Join-Path $projectRoot "tools\stockfish")
}

$stockfishAvxVnni = Join-Path $projectRoot "tools\stockfish-avxvnni\stockfish\stockfish-windows-x86-64-avxvnni.exe"
if (-not (Test-Path $stockfishAvxVnni)) {
    Install-StockfishArchive `
        "https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-avxvnni.zip" `
        (Join-Path $projectRoot "tools\stockfish-avxvnni.zip") `
        (Join-Path $projectRoot "tools\stockfish-avxvnni")
}

$env:STOCKFISH_PATH = $stockfishAvxVnni
$env:PYTHONPATH = Join-Path $projectRoot "src"

Write-Host ""
Write-Host "checkss server is starting..." -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "Stop: Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

& (Join-Path $projectRoot "venv\Scripts\waitress-serve.exe") `
    --host=127.0.0.1 `
    --port=5000 `
    --threads=8 `
    server:app
