param(
    [string]$AudioPath = (Join-Path $PSScriptRoot 'test_audio\test_audio_16k_mono.flac')
)

$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) {
    throw 'Missing backend/.venv Python. Install the project dependencies first.'
}
if (-not (Test-Path -LiteralPath $AudioPath -PathType Leaf)) {
    throw 'Test FLAC file was not found.'
}

# Check presence only. Never print credentials, environment dumps or HTTP bodies.
$taskRequired = @('DASHSCOPE_API_KEY', 'ALIYUN_OSS_BUCKET', 'ALIYUN_OSS_ENDPOINT',
                  'ALIYUN_OSS_ACCESS_KEY_ID', 'ALIYUN_OSS_ACCESS_KEY_SECRET')
$taskMissing = @($taskRequired | Where-Object {
    [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, 'Process'))
})
if ($taskMissing.Count -gt 0) {
    throw ('Missing process environment variable names: ' + ($taskMissing -join ', '))
}

$taskOverrides = @{
    ASR_RUN_LIVE_TESTS = '1'
    ASR_LIVE_AUDIO_PATH = (Resolve-Path -LiteralPath $AudioPath).Path
    ASR_LIVE_WORK_DIR = (Join-Path $PSScriptRoot '.local\asr-live-first')
}
$taskPrevious = @{}
foreach ($taskName in $taskOverrides.Keys) {
    $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}

Write-Host 'Real PAID test: private OSS + Beijing Paraformer-v2. Audio limit: 30 seconds.'
Write-Host 'Credentials are inherited from this PowerShell process and are never printed.'
Write-Host 'Keep .local/asr-live-first/asr.sqlite3 across retries to prevent duplicate billing.'
Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    foreach ($taskName in $taskOverrides.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskOverrides[$taskName], 'Process')
    }
    & $taskPython -m pytest tests/test_asr_live.py -q -s --tb=no --disable-warnings -p no:logging
    $taskExitCode = $LASTEXITCODE
}
finally {
    foreach ($taskName in $taskPrevious.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskPrevious[$taskName], 'Process')
    }
    Pop-Location
}
if ($taskExitCode -ne 0) {
    throw 'Real ASR check failed. See .local/asr-live-first/report.json (sanitized). Do not delete the ledger.'
}
Write-Host 'Sanitized report: .local/asr-live-first/report.json'
Write-Host 'Local subtitles: .local/asr-live-first/transcript.json'
