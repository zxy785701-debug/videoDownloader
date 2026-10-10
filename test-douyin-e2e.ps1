param(
    [Parameter(Mandatory = $true)]
    [string]$VideoUrl
)

$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'
$taskLedger = Join-Path $PSScriptRoot '.local\asr-live-first\asr.sqlite3'
if (-not (Test-Path -LiteralPath $taskLedger -PathType Leaf)) {
    throw 'Existing first-live ASR ledger is required. Do not reset or replace it.'
}
# OSS auth is resolved by the existing role/STS/environment credential chain.
# Secret values are never read back, echoed or written to files by this wrapper.
$taskOutput = Join-Path $PSScriptRoot ('.local\asr-live-first\douyin-e2e\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskPreviousOptIn = [Environment]::GetEnvironmentVariable('ASR_RUN_DOUYIN_E2E', 'Process')
$taskPreviousModules = [Environment]::GetEnvironmentVariable('NODE_PATH', 'Process')
$taskRuntimeModules = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
if (-not $taskPreviousModules -and (Test-Path -LiteralPath (Join-Path $taskRuntimeModules 'playwright\package.json'))) {
    $env:NODE_PATH = $taskRuntimeModules
}
Write-Host 'Real PAID Douyin acceptance: native first, at most one new ASR submission, then one summary operation.'
Write-Host 'Server credentials come from process environment or project-root .env; secret values are never printed.'
Write-Host 'Uses the SAME existing ASR ledger; cached or unknown paid tasks are never blindly resubmitted.'
Write-Host 'No new paid chat request. Read-only browser checks summary, mindmap, exports and empty chat.'
Write-Host 'Uses local port 8000 only during the test; if occupied, stops without restarting the existing service.'
Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    & $taskPython -m app.asr.settings
    if ($LASTEXITCODE -ne 0) { throw 'ASR configuration is incomplete; only missing variable names were printed.' }
    $env:ASR_RUN_DOUYIN_E2E = '1'
    & $taskPython -m tests.run_douyin_e2e --url $VideoUrl --output $taskOutput
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance stopped. Inspect the sanitized report; no automatic rerun was made.' }
} finally {
    [Environment]::SetEnvironmentVariable('ASR_RUN_DOUYIN_E2E', $taskPreviousOptIn, 'Process')
    [Environment]::SetEnvironmentVariable('NODE_PATH', $taskPreviousModules, 'Process')
    Pop-Location
    Write-Host ('Acceptance output: ' + $taskOutput)
}
