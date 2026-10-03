param(
    [ValidateSet('edge', 'chrome', 'firefox')]
    [string]$Browser = 'firefox',
    [string]$Profile = '',
    [string]$Proxy = '',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

# Opt-in personal mode. Environment changes apply only to this invocation.
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the backend virtual environment first; see README.md.'
}
$frontendPath = Join-Path $PSScriptRoot 'frontend'
Push-Location $frontendPath
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}
$settingNames = @('YTDLP_COOKIES_FROM_BROWSER', 'YTDLP_PROXY', 'YTDLP_POT_BASE_URL')
$savedSettings = @{}
foreach ($settingName in $settingNames) {
    $savedSettings[$settingName] = [Environment]::GetEnvironmentVariable($settingName, 'Process')
}
try {
    $cookieBrowser = $Browser
    if ($Profile) { $cookieBrowser = '{0}:{1}' -f $Browser, $Profile }
    $env:YTDLP_COOKIES_FROM_BROWSER = $cookieBrowser
    if ($Proxy) { $env:YTDLP_PROXY = $Proxy }
    # The earlier anonymous test provider is optional and may be stopped.
    [Environment]::SetEnvironmentVariable('YTDLP_POT_BASE_URL', $null, 'Process')
    Write-Host "Personal mode: $Browser cookies; API bound to 127.0.0.1:$Port."
    Write-Host "Open http://127.0.0.1:$Port to use the website. No separate frontend process is required."
    Write-Host 'Close the selected browser if its cookie database is locked. Ctrl+C stops the API.'
    & $pythonPath -m uvicorn app.main:app --app-dir (Join-Path $PSScriptRoot 'backend') --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "API exited with code $LASTEXITCODE" }
} finally {
    foreach ($settingName in $settingNames) {
        [Environment]::SetEnvironmentVariable($settingName, $savedSettings[$settingName], 'Process')
    }
}
