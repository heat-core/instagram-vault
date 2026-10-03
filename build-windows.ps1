$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path 'C:\Program Files\nodejs') { $env:PATH = 'C:\Program Files\nodejs;' + $env:PATH }

if (-not ((Test-Path '.build-deps\gallery_dl') -and (Test-Path '.build-deps\yt_dlp'))) {
  python -m pip install --disable-pip-version-check --no-deps --upgrade --target .build-deps gallery-dl==1.32.14 yt-dlp==2026.08.19
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Public downloader dependencies are unavailable; only session downloads will be packaged.' }
}
$env:PYTHONPATH = (Join-Path $PSScriptRoot '.build-deps') + ';' + $env:PYTHONPATH
$downloaderOptions = @()
if ((Test-Path '.build-deps\gallery_dl') -and (Test-Path '.build-deps\yt_dlp')) {
  $downloaderOptions = @('--hidden-import', 'gallery_dl', '--hidden-import', 'gallery_dl.job', '--hidden-import', 'gallery_dl.config',
    '--hidden-import', 'gallery_dl.extractor.instagram', '--hidden-import', 'yt_dlp', '--hidden-import', 'yt_dlp.extractor.instagram')
}

python -m PyInstaller --onedir --noconfirm --clean --name archive-api `
  --distpath desktop\backend-build --workpath desktop\build --specpath desktop\build `
  --paths .build-deps `
  --collect-submodules keyring.backends `
  @downloaderOptions `
  --exclude-module torch --exclude-module torchvision --exclude-module pandas `
  --exclude-module scipy --exclude-module sklearn --exclude-module matplotlib `
  --exclude-module orjson backend_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed' }

Push-Location -LiteralPath (Join-Path $PSScriptRoot 'desktop')
try {
  & .\node_modules\.bin\tsc.cmd -p tsconfig.app.json --noEmit --incremental false
  if ($LASTEXITCODE -ne 0) { throw 'TypeScript check failed' }
  & .\node_modules\.bin\vite.cmd build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
  & .\node_modules\.bin\electron-builder.cmd --dir --win
  if ($LASTEXITCODE -ne 0) { throw 'Electron build failed' }
} finally {
  Pop-Location
}

if (Test-Path 'desktop\release-next\win-unpacked') {
  Copy-Item -Path 'desktop\release\win-unpacked\*' -Destination 'desktop\release-next\win-unpacked' -Recurse -Force
}

Write-Host 'Ready: desktop\release\win-unpacked\Saved Archive.exe'
