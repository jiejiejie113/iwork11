$ErrorActionPreference = 'Stop'

& docker stop DKT_iwork
if ($LASTEXITCODE -ne 0) {
    throw "Failed to stop DKT_iwork with exit code $LASTEXITCODE."
}

Write-Host 'DKT_iwork stopped. Shared MySQL and Redis were left running.' -ForegroundColor Green
