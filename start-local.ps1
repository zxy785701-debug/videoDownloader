param(
    [ValidateSet('edge', 'chrome', 'firefox')]
    [string]$Browser = 'firefox',
    [string]$Profile = '',
    [string]$Proxy = '',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$AskDeepSeekKey,
    [switch]$UseFirefoxSubtitleSession,
    [string]$SubtitleFirefoxProfile = ''
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
$settingNames = @('YTDLP_COOKIES_FROM_BROWSER', 'YTDLP_PROXY', 'YTDLP_POT_BASE_URL', 'DEEPSEEK_API_KEY', 'VIDEO_LEARNING_FIREFOX_SESSION', 'VIDEO_LEARNING_FIREFOX_PROFILE')
$savedSettings = @{}
foreach ($settingName in $settingNames) {
    $savedSettings[$settingName] = [Environment]::GetEnvironmentVariable($settingName, 'Process')
}
try {
    if ($UseFirefoxSubtitleSession) {
        $env:VIDEO_LEARNING_FIREFOX_SESSION = '1'
        if ($SubtitleFirefoxProfile) { $env:VIDEO_LEARNING_FIREFOX_PROFILE = $SubtitleFirefoxProfile }
    }
    if ($AskDeepSeekKey) {
        $deepSeekSecureKey = Read-Host 'DeepSeek API key (hidden; optional, press Enter to skip)' -AsSecureString
        $deepSeekKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($deepSeekSecureKey)
        try {
            $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($deepSeekKeyPointer)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($deepSeekKeyPointer)
            $deepSeekSecureKey.Dispose()
        }
    }
    $cookieBrowser = $Browser
    if ($Profile) { $cookieBrowser = '{0}:{1}' -f $Browser, $Profile }
    $env:YTDLP_COOKIES_FROM_BROWSER = $cookieBrowser
    if ($Proxy) { $env:YTDLP_PROXY = $Proxy }
    # The earlier anonymous test provider is optional and may be stopped.
    [Environment]::SetEnvironmentVariable('YTDLP_POT_BASE_URL', $null, 'Process')
    Write-Host "Personal mode: $Browser cookies; API bound to 127.0.0.1:$Port."
    Write-Host "Open http://127.0.0.1:$Port to use the website. No separate frontend process is required."
    Write-Host 'Close the selected browser if its cookie database is locked. Ctrl+C stops the API.'
    if ($env:DEEPSEEK_API_KEY) { Write-Host 'DeepSeek is configured for this process. Open AI Learning to summarize available captions.' }
    else { Write-Host 'No DeepSeek summary key set in the process. Backend also checks DEEPSEEK_API_KEY in project-root .env; this message does not refer to the Bailian ASR key.' }
    if ($env:ASR_ENABLED -in @('0', 'false')) {
        Write-Host 'Cloud ASR fallback is disabled by ASR_ENABLED.'
    } elseif ($env:DASHSCOPE_API_KEY) {
        Write-Host 'Bailian/DashScope ASR key is present in the process environment (not cloud-validated). Private OSS bucket and credentials are also required; see docs/ASR_FALLBACK.md.'
    } else {
        Write-Host 'Cloud ASR fallback needs DASHSCOPE_API_KEY in the process environment and private OSS configuration. ASR does not read project-root .env; see docs/ASR_FALLBACK.md.'
    }
    if ($env:VIDEO_LEARNING_FIREFOX_SESSION -in @('1', 'true')) { Write-Host 'Firefox session is explicitly enabled for Bilibili/Douyin captions only.' }
    & $pythonPath -m uvicorn app.main:app --app-dir (Join-Path $PSScriptRoot 'backend') --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) { throw "API exited with code $LASTEXITCODE" }
} finally {
    foreach ($settingName in $settingNames) {
        [Environment]::SetEnvironmentVariable($settingName, $savedSettings[$settingName], 'Process')
    }
}
