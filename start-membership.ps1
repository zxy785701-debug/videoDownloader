param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8010,
    [switch]$Mock
)

$ErrorActionPreference = 'Stop'
$membershipPython = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $membershipPython)) { throw 'Install backend/requirements-billing.txt first.' }
$membershipNames = @('BILLING_ENV', 'BILLING_PROVIDER', 'BILLING_PUBLIC_URL', 'BILLING_DB', 'BILLING_MAIL_DIR')
$membershipSaved = @{}
foreach ($membershipName in $membershipNames) {
    $membershipSaved[$membershipName] = [Environment]::GetEnvironmentVariable($membershipName, 'Process')
}
try {
    if ($Mock) {
        $env:BILLING_ENV = 'development'
        $env:BILLING_PROVIDER = 'mock'
        $env:BILLING_PUBLIC_URL = "http://127.0.0.1:$Port"
        $env:BILLING_DB = Join-Path $PSScriptRoot '.local/mock-membership.sqlite3'
        $env:BILLING_MAIL_DIR = Join-Path $PSScriptRoot '.local/mock-billing-mail'
        Write-Host 'LOCAL SIMULATION ONLY. No real payment or Stripe connection.'
    }
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try {
        & $membershipPython -m uvicorn billing.main:app_factory --factory --host 127.0.0.1 --port $Port --no-access-log
    } finally { Pop-Location }
} finally {
    foreach ($membershipName in $membershipNames) {
        [Environment]::SetEnvironmentVariable($membershipName, $membershipSaved[$membershipName], 'Process')
    }
}
