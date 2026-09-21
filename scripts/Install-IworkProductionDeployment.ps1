[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ApprovedHeadSha,

    [string]$SourceDeployScript = (
        Join-Path $PSScriptRoot 'Invoke-IworkProductionDeployment.ps1'
    ),
    [string]$SourceCoordinationModule = (
        Join-Path $PSScriptRoot 'ProductionCoordination.psm1'
    ),
    [string]$ToolRoot = 'D:\DM\cicd-tools\iwork',
    [string]$PolicyRoot = 'D:\DM\cicd-policy',
    [string]$StateRoot = 'D:\DM\cicd-state\iwork',
    [string]$LockRoot = 'D:\DM\cicd-locks',
    [string]$RunnerRoot = 'D:\DM\actions-runner\iwork',
    [string]$ExpectedIdentity = 'DONGMING\shuju'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

# ======
# 固定策略配置
$TARGET_DEPLOY_SCRIPT = Join-Path $ToolRoot 'Invoke-IworkProductionDeployment.ps1'
$TARGET_COORDINATION_MODULE = Join-Path $ToolRoot 'ProductionCoordination.psm1'
$TARGET_HOOK = Join-Path $PolicyRoot 'iwork-job-started.ps1'
$EXPECTED_REPOSITORY = 'jiejiejie113/iwork11'
$EXPECTED_REF = 'refs/heads/Keycloak'
$EXPECTED_ACTOR = 'jiejiejie113'
$CROSS_REPOSITORY = 'jiejiejie113/DTD_nginx'

function Assert-Administrator {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '必须在提升权限的DONGMING\shuju会话中安装生产部署策略。'
    }
}

function Assert-ExpectedIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -ine $ExpectedIdentity) {
        throw "部署策略安装身份不正确：$identity"
    }
}

function Get-Sha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-CrossRepositoryRunReadiness {
    <#
    .SYNOPSIS
        确认Runner账号可只读查询另一仓库的Actions Run。
    #>
    $gh = Get-Command 'gh.exe' -ErrorAction SilentlyContinue
    if (-not $gh) { $gh = Get-Command 'gh' -ErrorAction SilentlyContinue }
    if (-not $gh) { throw '未安装GitHub CLI，无法核验跨仓库Run。' }

    $previousTimeout = $env:GH_HTTP_TIMEOUT
    $previousGhToken = $env:GH_TOKEN
    $previousGitHubToken = $env:GITHUB_TOKEN
    try {
        $env:GH_TOKEN = $null
        $env:GITHUB_TOKEN = $null
        $env:GH_HTTP_TIMEOUT = '30'
        & $gh.Source auth status --hostname github.com 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI未登录。' }
        & $gh.Source api `
            "repos/$CROSS_REPOSITORY/actions/runs?per_page=1" `
            --silent 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "当前Runner账号无法只读访问跨仓库：$CROSS_REPOSITORY"
        }
    }
    finally {
        $env:GH_HTTP_TIMEOUT = $previousTimeout
        $env:GH_TOKEN = $previousGhToken
        $env:GITHUB_TOKEN = $previousGitHubToken
    }
}

Assert-Administrator
Assert-ExpectedIdentity
Assert-CrossRepositoryRunReadiness

if (-not (Test-Path -LiteralPath $SourceDeployScript -PathType Leaf)) {
    throw "源部署脚本不存在：$SourceDeployScript"
}
if (-not (Test-Path -LiteralPath $SourceCoordinationModule -PathType Leaf)) {
    throw "源协调模块不存在：$SourceCoordinationModule"
}

$activeWorker = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'Runner.Worker.exe' -and
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($RunnerRoot, [StringComparison]::OrdinalIgnoreCase)
}
if ($activeWorker) {
    throw 'iwork Runner正在执行Job，拒绝更新生产准入策略。'
}

foreach ($directory in @($ToolRoot, $PolicyRoot, $StateRoot, $LockRoot)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$sourceHash = Get-Sha256 -Path $SourceDeployScript
$coordinationModuleHash = Get-Sha256 -Path $SourceCoordinationModule
$scriptTemporaryPath = "$TARGET_DEPLOY_SCRIPT.$([Guid]::NewGuid().ToString('N')).tmp"
$coordinationModuleTemporaryPath = "$TARGET_COORDINATION_MODULE.$([Guid]::NewGuid().ToString('N')).tmp"
$hookTemporaryPath = "$TARGET_HOOK.$([Guid]::NewGuid().ToString('N')).tmp"

try {
    Copy-Item -LiteralPath $SourceDeployScript -Destination $scriptTemporaryPath -Force
    $copiedHash = Get-Sha256 -Path $scriptTemporaryPath
    if ($copiedHash -cne $sourceHash) {
        throw "复制后的部署脚本SHA-256不一致：$copiedHash"
    }

    Copy-Item -LiteralPath $SourceCoordinationModule -Destination $coordinationModuleTemporaryPath -Force
    $copiedModuleHash = Get-Sha256 -Path $coordinationModuleTemporaryPath
    if ($copiedModuleHash -cne $coordinationModuleHash) {
        throw "复制后的协调模块SHA-256不一致：$copiedModuleHash"
    }

    $hook = @'
$ErrorActionPreference = 'Stop'
$expectedEvent = 'workflow_dispatch'
$expectedActor = '__EXPECTED_ACTOR__'
$expectedRepository = '__EXPECTED_REPOSITORY__'
$expectedRef = '__EXPECTED_REF__'
$approvedHeadSha = '__APPROVED_HEAD_SHA__'
$deployScriptPath = '__DEPLOY_SCRIPT_PATH__'
$deployScriptSha256 = '__DEPLOY_SCRIPT_SHA256__'
$coordinationModulePath = '__COORDINATION_MODULE_PATH__'
$coordinationModuleSha256 = '__COORDINATION_MODULE_SHA256__'
$allowedWorkflowRefs = @{
    'iwork production runner smoke' = 'jiejiejie113/iwork11/.github/workflows/runner-smoke.yml@refs/heads/Keycloak'
    'iwork controlled production deployment' = 'jiejiejie113/iwork11/.github/workflows/deploy-iwork.yml@refs/heads/Keycloak'
}

if ($env:GITHUB_EVENT_NAME -ne $expectedEvent) {
    throw "拒绝事件：$env:GITHUB_EVENT_NAME"
}
if ($env:GITHUB_ACTOR -ne $expectedActor) {
    throw "拒绝触发账号：$env:GITHUB_ACTOR"
}
if ($env:GITHUB_REPOSITORY -ne $expectedRepository) {
    throw "拒绝仓库：$env:GITHUB_REPOSITORY"
}
if ($env:GITHUB_REF -ne $expectedRef) {
    throw "拒绝分支引用：$env:GITHUB_REF"
}
if ($env:GITHUB_SHA -ne $approvedHeadSha) {
    throw "拒绝提交SHA：$env:GITHUB_SHA"
}
if (-not $allowedWorkflowRefs.ContainsKey($env:GITHUB_WORKFLOW)) {
    throw "拒绝Workflow：$env:GITHUB_WORKFLOW"
}
$expectedWorkflowRef = $allowedWorkflowRefs[$env:GITHUB_WORKFLOW]
if ($env:GITHUB_WORKFLOW_REF -ne $expectedWorkflowRef) {
    throw "拒绝Workflow引用：$env:GITHUB_WORKFLOW_REF"
}
if (-not (Test-Path -LiteralPath $deployScriptPath -PathType Leaf)) {
    throw "固定部署脚本不存在：$deployScriptPath"
}
$actualScriptHash = (
    Get-FileHash -LiteralPath $deployScriptPath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($actualScriptHash -ne $deployScriptSha256) {
    throw "固定部署脚本哈希不匹配：$actualScriptHash"
}
if (-not (Test-Path -LiteralPath $coordinationModulePath -PathType Leaf)) {
    throw "固定协调模块不存在：$coordinationModulePath"
}
$actualModuleHash = (
    Get-FileHash -LiteralPath $coordinationModulePath -Algorithm SHA256
).Hash.ToLowerInvariant()
if ($actualModuleHash -ne $coordinationModuleSha256) {
    throw "固定协调模块哈希不匹配：$actualModuleHash"
}
"Runner准入通过：$env:GITHUB_WORKFLOW_REF；sha=$env:GITHUB_SHA；actor=$env:GITHUB_ACTOR"
'@
    $hook = $hook.Replace('__EXPECTED_ACTOR__', $EXPECTED_ACTOR)
    $hook = $hook.Replace('__EXPECTED_REPOSITORY__', $EXPECTED_REPOSITORY)
    $hook = $hook.Replace('__EXPECTED_REF__', $EXPECTED_REF)
    $hook = $hook.Replace('__APPROVED_HEAD_SHA__', $ApprovedHeadSha)
    $hook = $hook.Replace('__DEPLOY_SCRIPT_PATH__', $TARGET_DEPLOY_SCRIPT)
    $hook = $hook.Replace('__DEPLOY_SCRIPT_SHA256__', $sourceHash)
    $hook = $hook.Replace('__COORDINATION_MODULE_PATH__', $TARGET_COORDINATION_MODULE)
    $hook = $hook.Replace('__COORDINATION_MODULE_SHA256__', $coordinationModuleHash)
    [IO.File]::WriteAllText(
        $hookTemporaryPath,
        $hook,
        [Text.UTF8Encoding]::new($true)
    )

    Move-Item -LiteralPath $scriptTemporaryPath -Destination $TARGET_DEPLOY_SCRIPT -Force
    Move-Item -LiteralPath $coordinationModuleTemporaryPath -Destination $TARGET_COORDINATION_MODULE -Force
    Move-Item -LiteralPath $hookTemporaryPath -Destination $TARGET_HOOK -Force
}
finally {
    Remove-Item -LiteralPath $scriptTemporaryPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $coordinationModuleTemporaryPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $hookTemporaryPath -Force -ErrorAction SilentlyContinue
}

[pscustomobject]@{
    ApprovedHeadSha = $ApprovedHeadSha
    DeployScript = $TARGET_DEPLOY_SCRIPT
    DeployScriptSha256 = $sourceHash
    CoordinationModule = $TARGET_COORDINATION_MODULE
    CoordinationModuleSha256 = $coordinationModuleHash
    AdmissionHook = $TARGET_HOOK
} | Format-List
