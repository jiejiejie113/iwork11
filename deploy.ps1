param(
    [ValidateSet('local', 'production')]
    [string]$Environment = 'local',
    [string]$SecretsFile,
    [switch]$Status,
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$WorkspaceRoot = Split-Path $RepoRoot -Parent
$Profile = Join-Path $RepoRoot "env\$Environment.env"

if (-not $SecretsFile) {
    if ($Environment -eq 'production') {
        $SecretsFile = 'D:\DM\dkt-secrets.env'
    } else {
        $SecretsFile = Join-Path $WorkspaceRoot 'dkt-secrets.env'
    }
}
$SecretsFile = [System.IO.Path]::GetFullPath($SecretsFile)

if ($Status) {
    & docker ps --filter 'name=DKT_iwork' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    & docker logs DKT_iwork --tail 30
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $Profile)) {
    throw "Environment profile does not exist: $Profile"
}
if (-not (Test-Path -LiteralPath $SecretsFile)) {
    throw "Central secrets file does not exist: $SecretsFile"
}

$composeArguments = @(
    'compose',
    '--env-file', $Profile,
    '--env-file', $SecretsFile,
    'up', '-d'
)
if (-not $NoBuild) {
    $composeArguments += '--build'
}
$composeArguments += 'iwork'

Push-Location $RepoRoot
try {
    & docker @composeArguments
    if ($LASTEXITCODE -ne 0) {
        throw "iwork deployment failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

if (& docker ps --filter 'name=DKT_kc_nginx' --format '{{.Names}}') {
    & docker exec DKT_kc_nginx nginx -t
    if ($LASTEXITCODE -ne 0) { throw 'Nginx configuration test failed.' }
    & docker exec DKT_kc_nginx nginx -s reload
    if ($LASTEXITCODE -ne 0) { throw 'Nginx reload failed.' }
}

$deadline = [DateTime]::UtcNow.AddSeconds(60)
do {
    & docker exec DKT_iwork python -c "import urllib.request; request = urllib.request.Request('http://127.0.0.1:8000/', headers={'Host': 'iwork'}); response = urllib.request.urlopen(request); assert response.status == 200" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "iwork deployment completed: $Environment (HTTP 200)" -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 3
} while ([DateTime]::UtcNow -lt $deadline)

throw 'iwork internal connectivity check failed.'
