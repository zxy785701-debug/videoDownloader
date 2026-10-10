param(
    [Parameter(Mandatory = $true)]
    [string]$VideoUrl,
    [ValidateSet('Both', 'Native', 'Anonymous')]
    [string]$Mode = 'Both'
)

$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'
$taskLedger = Join-Path $PSScriptRoot '.local\asr-live-first\asr.sqlite3'
if (-not (Test-Path -LiteralPath $taskLedger -PathType Leaf)) {
    throw 'Existing first-live ASR ledger is required. Do not create a fresh ledger or reset the original.'
}

$taskOutput = Join-Path $PSScriptRoot ('.local\asr-live-first\bilibili-e2e\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskPreviousOptIn = [Environment]::GetEnvironmentVariable('ASR_RUN_BILIBILI_E2E', 'Process')
$taskPreviousModules = [Environment]::GetEnvironmentVariable('NODE_PATH', 'Process')
$taskRuntimeModules = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
if (-not $taskPreviousModules -and (Test-Path -LiteralPath (Join-Path $taskRuntimeModules 'playwright\package.json'))) {
    $env:NODE_PATH = $taskRuntimeModules
}
Write-Host 'Real Bilibili acceptance: process environment or project-root .env; no secret values are printed.'
Write-Host 'Native and anonymous modes use separate learning databases and the SAME existing ASR ledger.'
Write-Host 'The test uses local port 8000 only while running. If occupied, it stops without restarting the existing service.'
Write-Host 'Make sure Firefox is logged into Bilibili. Close Firefox normally if its cookie database is locked.'
Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    & $taskPython -m app.asr.settings
    if ($LASTEXITCODE -ne 0) { throw 'ASR configuration is incomplete; only missing variable names were printed.' }
    $env:ASR_RUN_BILIBILI_E2E = '1'
    $taskModes = if ($Mode -eq 'Both') { @('native', 'anonymous') } else { @($Mode.ToLowerInvariant()) }
    foreach ($taskCase in $taskModes) {
        $taskCaseOutput = Join-Path $taskOutput $taskCase
        & $taskPython -m tests.run_bilibili_e2e --mode $taskCase --url $VideoUrl --output $taskCaseOutput
        if ($LASTEXITCODE -ne 0) {
            throw ('Acceptance stopped in ' + $taskCase + '. Inspect its sanitized report. No automatic rerun was made.')
        }
    }
} finally {
    [Environment]::SetEnvironmentVariable('ASR_RUN_BILIBILI_E2E', $taskPreviousOptIn, 'Process')
    [Environment]::SetEnvironmentVariable('NODE_PATH', $taskPreviousModules, 'Process')
    Pop-Location
    Write-Host ('Acceptance output: ' + $taskOutput)
}
