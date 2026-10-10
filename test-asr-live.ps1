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

# Python checks process/.env settings without returning secret values to PowerShell.

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
Write-Host 'Server credentials come from process environment or project-root .env and are never printed.'
Write-Host 'Keep .local/asr-live-first/asr.sqlite3 across retries to prevent duplicate billing.'
Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    & $taskPython -m app.asr.settings
    if ($LASTEXITCODE -ne 0) { throw 'ASR configuration is incomplete; only missing variable names were printed.' }
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
