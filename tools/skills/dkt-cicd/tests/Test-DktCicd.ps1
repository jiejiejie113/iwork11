[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$skillRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $skillRoot 'scripts\Invoke-DktCicd.ps1'
$fakeGhPath = Join-Path $PSScriptRoot 'Fake-Gh.ps1'
$revision = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$imageDigest = 'sha256:' + ('1' * 64)
$portalDigest = 'sha256:' + ('2' * 64)
$proxyDigest = 'sha256:' + ('3' * 64)
$script:passed = 0

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if (-not $Condition) {
        throw "断言失败：$Message"
    }
    $script:passed++
}

function Remove-TestStateDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    $expectedRoot = [IO.Path]::GetFullPath((Join-Path $env:TEMP 'dkt-cicd-test-'))
    if (-not $resolvedPath.StartsWith($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝删除非测试目录：$resolvedPath"
    }
    if (Test-Path -LiteralPath $resolvedPath) {
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
}

function Invoke-SkillProcess {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [ValidateSet('queued', 'in_progress', 'success', 'failure')]
        [string]$Mode = 'success',
        [switch]$PreserveState,
        [switch]$LogFailure,
        [switch]$Concurrent,
        [switch]$InvalidPortalDigests
    )

    $stateDirectory = Join-Path $env:TEMP ('dkt-cicd-test-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $env:DKT_CICD_FAKE_STATE_DIR = $stateDirectory
    $env:DKT_CICD_FAKE_REVISION = $revision
    $env:DKT_CICD_FAKE_MODE = $Mode
    $env:DKT_CICD_TEST_MODE = '1'
    $env:DKT_CICD_FAKE_LOG_FAILURE = if ($LogFailure) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_CONCURRENT = if ($Concurrent) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_INVALID_PORTAL_DIGESTS = if ($InvalidPortalDigests) { '1' } else { '0' }

    $allArguments = @(
        '-NoLogo', '-NoProfile', '-File', $scriptPath
    ) + $Arguments + @('-GhExecutable', $fakeGhPath, '-OutputJson')
    $output = @(& pwsh @allArguments 2>&1)
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { [string]$_ }) -join "`n"
    $result = [pscustomobject]@{
        ExitCode = $exitCode
        Output = $text
        StateDirectory = $stateDirectory
    }
    if (-not $PreserveState) {
        Remove-TestStateDirectory -Path $stateDirectory
    }
    return $result
}

foreach ($mode in @('queued', 'in_progress', 'success', 'failure')) {
    $statusResult = Invoke-SkillProcess -Arguments @(
        '-Action', 'status', '-Service', 'iwork', '-WorkflowKind', 'ci', '-Limit', '1'
    ) -Mode $mode
    Assert-True -Condition ($statusResult.ExitCode -eq 0) -Message "status/$mode 应成功"
    $statusJson = $statusResult.Output | ConvertFrom-Json
    $expectedStatus = if ($mode -in @('queued', 'in_progress')) { $mode } else { 'completed' }
    Assert-True -Condition ($statusJson.Status -eq $expectedStatus) -Message "status/$mode 状态应准确"
    if ($mode -eq 'failure') {
        Assert-True -Condition ($statusJson.FailedSteps.Count -eq 1) -Message '失败步骤应被提取'
    }
}

$statusRouting = Invoke-SkillProcess -Arguments @(
    '-Action', 'status', '-Service', 'portal', '-WorkflowKind', 'release', '-Limit', '1'
) -Mode success -PreserveState
$statusRoutingLog = Get-Content -LiteralPath (Join-Path $statusRouting.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($statusRoutingLog.Contains('release.yml')) -Message '状态查询应按 WorkflowKind 路由'
Remove-TestStateDirectory -Path $statusRouting.StateDirectory

$logResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'failed-log', '-Service', 'iwork', '-RunId', '900'
) -Mode failure
Assert-True -Condition ($logResult.ExitCode -eq 0) -Message 'failed-log 应成功'
Assert-True -Condition (-not $logResult.Output.Contains('FAKE_TOKEN_VALUE')) -Message 'GitHub Token 必须脱敏'
Assert-True -Condition (-not $logResult.Output.Contains('FAKE_NEW_TOKEN')) -Message '新版 GitHub Token 必须脱敏'
Assert-True -Condition (-not $logResult.Output.Contains('FAKE_PASSWORD_VALUE')) -Message '密码必须脱敏'
Assert-True -Condition (-not $logResult.Output.Contains('fake-uri-password')) -Message 'URI userinfo 密码必须脱敏'
Assert-True -Condition ($logResult.Output.Contains('[REDACTED')) -Message '脱敏标记必须可见'

$failedLogRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'failed-log', '-Service', 'iwork', '-RunId', '900'
) -Mode failure -LogFailure
Assert-True -Condition (
    $failedLogRead.ExitCode -eq 1 -and
    $failedLogRead.Output.Contains('模拟失败日志读取失败')
) -Message '失败日志读取失败必须失败关闭'

$ciResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'ci', '-Service', 'iwork', '-Revision', $revision
) -Mode queued -PreserveState
Assert-True -Condition ($ciResult.ExitCode -eq 0) -Message 'CI 触发应成功'
$ciJson = $ciResult.Output | ConvertFrom-Json
Assert-True -Condition ($ciJson.Status -eq 'queued') -Message '新 CI queued 不得误报成功'
$ciLog = Get-Content -LiteralPath (Join-Path $ciResult.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($ciLog.Contains('workflow') -and $ciLog.Contains('ci.yml')) -Message 'CI 应路由到 ci.yml'
Assert-True -Condition ($ciLog.Contains('GuChenkano/iwork') -and $ciLog.Contains('Keycloak')) -Message 'CI 应固定仓库和分支'
Remove-TestStateDirectory -Path $ciResult.StateDirectory

$releaseResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success
Assert-True -Condition ($releaseResult.ExitCode -eq 0) -Message '发布触发与等待应成功'
$releaseJson = $releaseResult.Output | ConvertFrom-Json
Assert-True -Condition ($releaseJson.Conclusion -eq 'success') -Message '发布成功结论应准确'
Assert-True -Condition ($releaseJson.Digests -contains $imageDigest) -Message '发布结果应提取 Digest'

$failedWait = Invoke-SkillProcess -Arguments @(
    '-Action', 'ci', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode failure
Assert-True -Condition ($failedWait.ExitCode -eq 2) -Message '等待到失败结论必须返回非零退出码'

$failedDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -LogFailure
Assert-True -Condition (
    $failedDigestRead.ExitCode -eq 1 -and
    $failedDigestRead.Output.Contains('模拟完整日志读取失败')
) -Message '成功发布但无法读取 Digest 时必须失败关闭'

$invalidPortalDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'portal', '-Revision', $revision, '-Wait'
) -Mode success -InvalidPortalDigests
Assert-True -Condition (
    $invalidPortalDigestRead.ExitCode -eq 1 -and
    $invalidPortalDigestRead.Output.Contains('dtd-nginx') -and
    $invalidPortalDigestRead.Output.Contains('唯一完整 Digest')
) -Message 'Portal 必须分别校验两个固定镜像各自唯一的 Digest'

$ambiguousDispatch = Invoke-SkillProcess -Arguments @(
    '-Action', 'ci', '-Service', 'iwork', '-Revision', $revision
) -Mode queued -Concurrent
Assert-True -Condition (
    $ambiguousDispatch.ExitCode -eq 1 -and
    $ambiguousDispatch.Output.Contains('并发') -and
    $ambiguousDispatch.Output.Contains('禁止重复触发')
) -Message '并发候选 Run 歧义必须停止关联并禁止重试'

$previewResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ChangeDescription', '离线验收'
) -Mode success -PreserveState
Assert-True -Condition ($previewResult.ExitCode -eq 4) -Message '缺少生产确认必须返回专用退出码'
$previewJson = $previewResult.Output | ConvertFrom-Json
Assert-True -Condition ($previewJson.Status -eq 'confirmation_required') -Message '必须返回确认预览'
Assert-True -Condition ($previewJson.RequiredApprovalText -eq "DEPLOY IWORK $revision") -Message 'iwork 确认词应绑定 Commit'
Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $previewResult.StateDirectory 'deploy-iwork.yml.dispatched'))) -Message '未确认不得触发部署'
Remove-TestStateDirectory -Path $previewResult.StateDirectory

$deployResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ChangeDescription', '离线验收',
    '-ApprovalText', "DEPLOY IWORK $revision"
) -Mode queued -PreserveState
Assert-True -Condition ($deployResult.ExitCode -eq 0) -Message '精确确认后应允许触发假部署'
Assert-True -Condition (Test-Path -LiteralPath (Join-Path $deployResult.StateDirectory 'deploy-iwork.yml.dispatched')) -Message '假部署应被记录为已触发'
$deployLog = Get-Content -LiteralPath (Join-Path $deployResult.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($deployLog.Contains('apply=true')) -Message '部署必须传 apply=true'
Assert-True -Condition ($deployLog.Contains('confirmation=DEPLOY IWORK')) -Message '应传 Workflow 原生确认词'
Remove-TestStateDirectory -Path $deployResult.StateDirectory

$portalPreview = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'portal', '-Revision', $revision,
    '-PortalDigest', $portalDigest, '-ProxyDigest', $proxyDigest,
    '-ChangeDescription', 'Portal 离线验收'
) -Mode success
Assert-True -Condition ($portalPreview.ExitCode -eq 4) -Message 'Portal 缺少确认必须阻止'
$portalJson = $portalPreview.Output | ConvertFrom-Json
Assert-True -Condition ($portalJson.RequiredApprovalText -eq "DEPLOY PORTAL AND AUTHENTICATION $revision") -Message 'Portal 应使用更强确认词'

$invalidPreflight = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ChangeDescription', '禁止迁移的预检',
    '-RunMigrations'
) -Mode success
Assert-True -Condition (
    $invalidPreflight.ExitCode -eq 1 -and
    $invalidPreflight.Output.Contains('不接受数据库迁移开关')
) -Message '预检不得接受迁移开关'

$rollbackResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'rollback', '-Service', 'iwork'
)
Assert-True -Condition ($rollbackResult.ExitCode -eq 3) -Message '手工回滚缺少 Workflow 时必须失败关闭'
$rollbackJson = $rollbackResult.Output | ConvertFrom-Json
Assert-True -Condition ($rollbackJson.Code -eq 'manual_rollback_workflow_missing') -Message '回滚阻断原因应明确'

$productionStatus = Invoke-SkillProcess -Arguments @(
    '-Action', 'production-status', '-Service', 'portal', '-Limit', '1'
)
Assert-True -Condition ($productionStatus.ExitCode -eq 0) -Message '生产交付证据查询应成功'
$productionJson = $productionStatus.Output | ConvertFrom-Json
Assert-True -Condition ($productionJson.EvidenceScope.Contains('not live Docker health')) -Message '不得把 Actions 证据冒充实时容器健康'

[Environment]::SetEnvironmentVariable('DKT_CICD_TEST_MODE', $null, 'Process')
$overrideOutput = @(& pwsh -NoLogo -NoProfile -File $scriptPath `
    -Action status -Service iwork -GhExecutable $fakeGhPath -OutputJson 2>&1)
$overrideExitCode = $LASTEXITCODE
Assert-True -Condition (
    $overrideExitCode -ne 0 -and
    (($overrideOutput | ForEach-Object { [string]$_ }) -join "`n").Contains('仅允许离线测试使用')
) -Message '真实模式不得替换 gh 可执行文件'

$filesToScan = Get-ChildItem -LiteralPath $skillRoot -Recurse -File | Where-Object {
    $_.FullName -notlike '*\tests\Fake-Gh.ps1'
}
$forbiddenPatterns = @(
    'gh[pousr]_[A-Za-z0-9_]{12,}',
    'github_pat_[A-Za-z0-9_]{12,}',
    'dkt-secrets\.env\s*=',
    'BEGIN (?:RSA |OPENSSH )?PRIVATE KEY'
)
foreach ($file in $filesToScan) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($pattern in $forbiddenPatterns) {
        Assert-True -Condition (-not [regex]::IsMatch($content, $pattern, 'IgnoreCase')) -Message "文件不得包含敏感内容：$($file.Name)"
    }
}

Write-Output "dkt-cicd 离线验收通过，共完成 $script:passed 个断言。"
$global:LASTEXITCODE = 0
