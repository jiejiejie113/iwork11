$ErrorActionPreference = 'Stop'

& docker restart DKT_iwork
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restart DKT_iwork with exit code $LASTEXITCODE."
}

Write-Host 'DKT_iwork restarted.' -ForegroundColor Green
