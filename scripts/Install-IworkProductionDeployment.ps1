[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ApprovedHeadSha,

    [string]$SourceDeployScript = (
        Join-Path $PSScriptRoot 'Invoke-IworkProductionDeployment.ps1'
    ),
    [string]$ToolRoot = 'D:\DM\cicd-tools',
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
$TARGET_HOOK = Join-Path $PolicyRoot 'iwork-job-started.ps1'
$EXPECTED_REPOSITORY = 'GuChenkano/iwork'
$EXPECTED_REF = 'refs/heads/Keycloak'
$EXPECTED_ACTOR = 'GuChenkano'

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

Assert-Administrator
Assert-ExpectedIdentity

if (-not (Test-Path -LiteralPath $SourceDeployScript -PathType Leaf)) {
    throw "源部署脚本不存在：$SourceDeployScript"
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
$scriptTemporaryPath = "$TARGET_DEPLOY_SCRIPT.$([Guid]::NewGuid().ToString('N')).tmp"
$hookTemporaryPath = "$TARGET_HOOK.$([Guid]::NewGuid().ToString('N')).tmp"

try {
    Copy-Item -LiteralPath $SourceDeployScript -Destination $scriptTemporaryPath -Force
    $copiedHash = Get-Sha256 -Path $scriptTemporaryPath
    if ($copiedHash -cne $sourceHash) {
        throw "复制后的部署脚本SHA-256不一致：$copiedHash"
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
$allowedWorkflowRefs = @{
    'iwork production runner smoke' = 'GuChenkano/iwork/.github/workflows/runner-smoke.yml@refs/heads/Keycloak'
    'iwork controlled production deployment' = 'GuChenkano/iwork/.github/workflows/deploy-iwork.yml@refs/heads/Keycloak'
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
"Runner准入通过：$env:GITHUB_WORKFLOW_REF；sha=$env:GITHUB_SHA；actor=$env:GITHUB_ACTOR"
'@
    $hook = $hook.Replace('__EXPECTED_ACTOR__', $EXPECTED_ACTOR)
    $hook = $hook.Replace('__EXPECTED_REPOSITORY__', $EXPECTED_REPOSITORY)
    $hook = $hook.Replace('__EXPECTED_REF__', $EXPECTED_REF)
    $hook = $hook.Replace('__APPROVED_HEAD_SHA__', $ApprovedHeadSha)
    $hook = $hook.Replace('__DEPLOY_SCRIPT_PATH__', $TARGET_DEPLOY_SCRIPT)
    $hook = $hook.Replace('__DEPLOY_SCRIPT_SHA256__', $sourceHash)
    [IO.File]::WriteAllText(
        $hookTemporaryPath,
        $hook,
        [Text.UTF8Encoding]::new($true)
    )

    Move-Item -LiteralPath $scriptTemporaryPath -Destination $TARGET_DEPLOY_SCRIPT -Force
    Move-Item -LiteralPath $hookTemporaryPath -Destination $TARGET_HOOK -Force
}
finally {
    Remove-Item -LiteralPath $scriptTemporaryPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $hookTemporaryPath -Force -ErrorAction SilentlyContinue
}

[pscustomobject]@{
    ApprovedHeadSha = $ApprovedHeadSha
    DeployScript = $TARGET_DEPLOY_SCRIPT
    DeployScriptSha256 = $sourceHash
    AdmissionHook = $TARGET_HOOK
} | Format-List
