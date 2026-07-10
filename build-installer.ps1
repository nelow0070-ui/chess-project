$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$appVersion = "1.2.0"

$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "먼저 .\run.ps1을 실행해 Python 가상환경을 준비해주세요."
}

$stockfishAvx2 = Join-Path $projectRoot "tools\stockfish\stockfish\stockfish-windows-x86-64-avx2.exe"
$stockfishAvxVnni = Join-Path $projectRoot "tools\stockfish-avxvnni\stockfish\stockfish-windows-x86-64-avxvnni.exe"
if (-not (Test-Path $stockfishAvx2) -or -not (Test-Path $stockfishAvxVnni)) {
    throw "Stockfish가 없습니다. 먼저 .\run.ps1을 실행해주세요."
}

& $python -m pip install -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    throw "Python 빌드 패키지 설치에 실패했습니다."
}
& $python -m PyInstaller --noconfirm --clean checkss.spec
if ($LASTEXITCODE -ne 0) {
    throw "checkss 실행 파일 빌드에 실패했습니다."
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Host ""
    Write-Host "실행 파일 빌드 완료: dist\checkss\checkss.exe" -ForegroundColor Green
    Write-Host "설치 파일을 만들려면 Inno Setup 6을 설치한 뒤 이 스크립트를 다시 실행하세요." -ForegroundColor Yellow
    exit 0
}

& $iscc (Join-Path $projectRoot "installer\checkss.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Windows 설치 파일 빌드에 실패했습니다."
}
Write-Host ""
Write-Host "설치 파일 빌드 완료: release\checkss-Setup-$appVersion.exe" -ForegroundColor Green
