[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$skillRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $skillRoot 'scripts\Invoke-DktCicd.ps1'
$fakeGhPath = Join-Path $PSScriptRoot 'Fake-Gh.ps1'
$revision = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$imageDigest = 'sha256:' + ('1' * 64)
$configDigest = 'sha256:' + ('5' * 64)
$configArtifactDigest = 'sha256:' + ('7' * 64)
$portalDigest = 'sha256:' + ('2' * 64)
$proxyDigest = 'sha256:' + ('3' * 64)
$script:passed = 0
$engineExecutable = if ($PSVersionTable.PSEdition -eq 'Desktop') {
    'powershell.exe'
}
else {
    'pwsh'
}

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
        [switch]$InvalidPortalDigests,
        [switch]$InvalidImageDigests,
        [switch]$MissingConfigDigest,
        [switch]$MissingConfigArtifactDigest,
        [switch]$InvalidConfigArtifactDigests,
        [switch]$PrefixedConfigArtifactDigest,
        [switch]$MalformedConfigArtifactDigest,
        [switch]$ReleaseEventPush,
        [switch]$MismatchedReleaseDigest,
        [int]$DiscoveryDelayQueries = 0,
        [switch]$FinalDiscoveryQuery,
        [string]$ExistingStateDirectory
    )

    $stateDirectory = if ([String]::IsNullOrWhiteSpace($ExistingStateDirectory)) {
        Join-Path $env:TEMP ('dkt-cicd-test-' + [Guid]::NewGuid().ToString('N'))
    }
    else {
        $ExistingStateDirectory
    }
    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $env:DKT_CICD_FAKE_STATE_DIR = $stateDirectory
    $env:DKT_CICD_FAKE_REVISION = $revision
    $env:DKT_CICD_FAKE_MODE = $Mode
    $env:DKT_CICD_TEST_MODE = '1'
    $env:DKT_CICD_FAKE_LOG_FAILURE = if ($LogFailure) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_CONCURRENT = if ($Concurrent) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_INVALID_PORTAL_DIGESTS = if ($InvalidPortalDigests) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_INVALID_IMAGE_DIGESTS = if ($InvalidImageDigests) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_MISSING_CONFIG_DIGEST = if ($MissingConfigDigest) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_MISSING_CONFIG_ARTIFACT_DIGEST = if ($MissingConfigArtifactDigest) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_INVALID_CONFIG_ARTIFACT_DIGESTS = if ($InvalidConfigArtifactDigests) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_PREFIXED_CONFIG_ARTIFACT_DIGEST = if ($PrefixedConfigArtifactDigest) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_MALFORMED_CONFIG_ARTIFACT_DIGEST = if ($MalformedConfigArtifactDigest) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_RELEASE_EVENT_PUSH = if ($ReleaseEventPush) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_MISMATCHED_RELEASE_DIGEST = if ($MismatchedReleaseDigest) { '1' } else { '0' }
    $env:DKT_CICD_FAKE_DISCOVERY_DELAY_QUERIES = [string]$DiscoveryDelayQueries
    $env:DKT_CICD_TEST_DISCOVERY_TIMEOUT_SECONDS = if ($FinalDiscoveryQuery) { '0' } else { $null }
    $env:DKT_CICD_CONFIRMATION_STATE_ROOT = Join-Path $stateDirectory 'confirmations'

    $allArguments = @(
        '-NoLogo', '-NoProfile', '-File', $scriptPath
    ) + $Arguments + @('-GhExecutable', $fakeGhPath, '-OutputJson')
    $output = @(& $engineExecutable @allArguments 2>&1)
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
    Assert-True -Condition (@($statusJson.Digests).Count -eq 0) -Message "status/$mode 的 Digests 必须规范化为空数组"
}

$statusRouting = Invoke-SkillProcess -Arguments @(
    '-Action', 'status', '-Service', 'portal', '-WorkflowKind', 'release', '-Limit', '1'
) -Mode success -PreserveState
$statusRoutingLog = Get-Content -LiteralPath (Join-Path $statusRouting.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($statusRoutingLog.Contains('release.yml')) -Message '状态查询应按 WorkflowKind 路由'
$statusRoutingJson = $statusRouting.Output | ConvertFrom-Json
Assert-True -Condition (
    $statusRoutingJson.Digests -contains $portalDigest -and
    $statusRoutingJson.Digests -contains $proxyDigest
) -Message 'Release 状态查询必须返回已发布的完整 Digest'
Assert-True -Condition ($null -eq $statusRoutingJson.ConfigArtifactDigest) -Message 'Portal Release 不应产生 iwork ConfigArtifactDigest'
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
) -Mode success -PreserveState
Assert-True -Condition ($releaseResult.ExitCode -eq 0) -Message '发布触发与等待应成功'
$releaseJson = $releaseResult.Output | ConvertFrom-Json
Assert-True -Condition ($releaseJson.Conclusion -eq 'success') -Message '发布成功结论应准确'
Assert-True -Condition ($releaseJson.Digests -contains $imageDigest) -Message '发布结果应提取 Digest'
Assert-True -Condition ($releaseJson.ImageDigest -eq $imageDigest) -Message '发布结果应单独返回 ImageDigest'
Assert-True -Condition ($releaseJson.ConfigDigest -eq $configDigest) -Message '发布结果应返回唯一 ConfigDigest'
Assert-True -Condition ($releaseJson.ConfigArtifactDigest -eq $configArtifactDigest) -Message '发布结果应返回唯一 ConfigArtifactDigest'
$releaseLog = Get-Content -LiteralPath (Join-Path $releaseResult.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($releaseLog -match 'request_id=[0-9a-f-]{36}') -Message 'Release 触发必须传入 GUID request_id'
Assert-True -Condition ($releaseLog -match 'ci_request_id=11111111-2222-3333-4444-555555555555') -Message 'Release 必须精确绑定成功 CI 的 request_id'
Remove-TestStateDirectory -Path $releaseResult.StateDirectory

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

$invalidImageDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -InvalidImageDigests
Assert-True -Condition (
    $invalidImageDigestRead.ExitCode -eq 1 -and
    $invalidImageDigestRead.Output.Contains('唯一完整 Digest')
) -Message '成功 iwork Release 必须严格校验唯一 ImageDigest'

$missingConfigDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -MissingConfigDigest
Assert-True -Condition (
    $missingConfigDigestRead.ExitCode -eq 1 -and
    $missingConfigDigestRead.Output.Contains('ConfigDigest') -and
    $missingConfigDigestRead.Output.Contains('实际：0')
) -Message '成功 iwork Release 缺少 ConfigDigest 时必须失败关闭'

$missingConfigArtifactDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -MissingConfigArtifactDigest
Assert-True -Condition (
    $missingConfigArtifactDigestRead.ExitCode -eq 1 -and
    $missingConfigArtifactDigestRead.Output.Contains('ConfigArtifactDigest') -and
    $missingConfigArtifactDigestRead.Output.Contains('实际：0')
) -Message '成功 iwork Release 缺少 ConfigArtifactDigest 时必须失败关闭'

$invalidConfigArtifactDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -InvalidConfigArtifactDigests
Assert-True -Condition (
    $invalidConfigArtifactDigestRead.ExitCode -eq 1 -and
    $invalidConfigArtifactDigestRead.Output.Contains('ConfigArtifactDigest') -and
    $invalidConfigArtifactDigestRead.Output.Contains('唯一且完整')
) -Message '成功 iwork Release 出现多个 ConfigArtifactDigest 时必须失败关闭'

$prefixedConfigArtifactDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -PrefixedConfigArtifactDigest
Assert-True -Condition (
    $prefixedConfigArtifactDigestRead.ExitCode -eq 0 -and
    ($prefixedConfigArtifactDigestRead.Output | ConvertFrom-Json).ConfigArtifactDigest -eq $configArtifactDigest
) -Message '带 Job/Step 前缀的 Release 日志仍应稳定解析 ConfigArtifactDigest'

$malformedConfigArtifactDigestRead = Invoke-SkillProcess -Arguments @(
    '-Action', 'release', '-Service', 'iwork', '-Revision', $revision, '-Wait'
) -Mode success -MalformedConfigArtifactDigest
Assert-True -Condition (
    $malformedConfigArtifactDigestRead.ExitCode -eq 1 -and
    $malformedConfigArtifactDigestRead.Output.Contains('ConfigArtifactDigest') -and
    $malformedConfigArtifactDigestRead.Output.Contains('唯一且完整')
) -Message '成功 iwork Release 的 ConfigArtifactDigest 不完整时必须失败关闭'

$failedProductionStatus = Invoke-SkillProcess -Arguments @(
    '-Action', 'production-status', '-Service', 'iwork', '-Limit', '1'
) -Mode failure -LogFailure
Assert-True -Condition ($failedProductionStatus.ExitCode -eq 0) -Message 'completed failure 的生产证据不得因缺少 Digest 全局失败'
$failedProductionJson = $failedProductionStatus.Output | ConvertFrom-Json
Assert-True -Condition ($failedProductionJson.Runs[0].Digests.Count -eq 0) -Message '失败生产 Run 的 Digests 必须为空'
Assert-True -Condition ($null -eq $failedProductionJson.Runs[0].ImageDigest) -Message '失败生产 Run 的 ImageDigest 必须为空'
Assert-True -Condition ($null -eq $failedProductionJson.Runs[0].ConfigDigest) -Message '失败生产 Run 的 ConfigDigest 必须为空'
Assert-True -Condition ($null -eq $failedProductionJson.Runs[0].ConfigArtifactDigest) -Message '失败生产 Run 的 ConfigArtifactDigest 必须为空'

$successfulProductionStatus = Invoke-SkillProcess -Arguments @(
    '-Action', 'production-status', '-Service', 'iwork', '-Limit', '1'
) -Mode success
Assert-True -Condition ($successfulProductionStatus.ExitCode -eq 0) -Message '成功iwork生产证据查询应可解析'
$successfulProductionJson = $successfulProductionStatus.Output | ConvertFrom-Json
Assert-True -Condition (
    $successfulProductionJson.Runs[0].RequestId -eq '11111111-2222-3333-4444-555555555555'
) -Message 'production-status必须从run-name恢复iwork request_id'

$ambiguousDispatch = Invoke-SkillProcess -Arguments @(
    '-Action', 'ci', '-Service', 'iwork', '-Revision', $revision
) -Mode queued -Concurrent
Assert-True -Condition (
    $ambiguousDispatch.ExitCode -eq 1 -and
    $ambiguousDispatch.Output.Contains('并发') -and
    $ambiguousDispatch.Output.Contains('禁止重复触发')
) -Message '并发候选 Run 歧义必须停止关联并禁止重试'

$finalDiscovery = Invoke-SkillProcess -Arguments @(
    '-Action', 'ci', '-Service', 'iwork', '-Revision', $revision
) -Mode queued -DiscoveryDelayQueries 1 -FinalDiscoveryQuery -PreserveState
Assert-True -Condition ($finalDiscovery.ExitCode -eq 0) -Message '发现窗口截止时必须执行最终查询并关联刚创建的 Run'
$finalDiscoveryJson = $finalDiscovery.Output | ConvertFrom-Json
Assert-True -Condition (
    $finalDiscoveryJson.RequestId -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
) -Message '触发结果必须返回关联用 request_id'
$finalDiscoveryLog = Get-Content -LiteralPath (Join-Path $finalDiscovery.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($finalDiscoveryLog -match 'request_id=[0-9a-f-]{36}') -Message 'CI 触发必须传入 GUID request_id'
Remove-TestStateDirectory -Path $finalDiscovery.StateDirectory

$mismatchedDigest = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', 'Digest 绑定验收'
) -Mode success -MismatchedReleaseDigest
Assert-True -Condition (
    $mismatchedDigest.ExitCode -eq 1 -and
    $mismatchedDigest.Output.Contains('发布产物')
) -Message '预检 Digest 必须与同 Commit 的 Release 产物完全一致'

$untrackedRelease = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', 'Release事件门禁验收'
) -Mode success -ReleaseEventPush
Assert-True -Condition (
    $untrackedRelease.ExitCode -eq 1 -and
    $untrackedRelease.Output.Contains('workflow_dispatch')
) -Message 'iwork生产预检只能复用带request_id的workflow_dispatch Release'

$mismatchedConfigDigest = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', ('sha256:' + ('6' * 64)),
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', '配置 Digest 绑定验收'
) -Mode success
Assert-True -Condition (
    $mismatchedConfigDigest.ExitCode -eq 1 -and
    $mismatchedConfigDigest.Output.Contains('ConfigDigest') -and
    $mismatchedConfigDigest.Output.Contains('配置发布产物')
) -Message '预检 ConfigDigest 必须与同 Commit 的 Release 配置产物完全一致'

$mismatchedConfigArtifactDigest = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', ('sha256:' + ('6' * 64)),
    '-ChangeDescription', '配置 Artifact Digest 绑定验收'
) -Mode success
Assert-True -Condition (
    $mismatchedConfigArtifactDigest.ExitCode -eq 1 -and
    $mismatchedConfigArtifactDigest.Output.Contains('ConfigArtifactDigest') -and
    $mismatchedConfigArtifactDigest.Output.Contains('配置发布产物')
) -Message '预检 ConfigArtifactDigest 必须与同一 Commit 的 Release 配置 Artifact 产物完全一致'

$mismatchedPortalDigests = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'portal', '-Revision', $revision,
    '-PortalDigest', $portalDigest, '-ProxyDigest', $proxyDigest,
    '-ChangeDescription', 'Portal Digest 绑定验收'
) -Mode success -MismatchedReleaseDigest
Assert-True -Condition (
    $mismatchedPortalDigests.ExitCode -eq 1 -and
    $mismatchedPortalDigests.Output.Contains('发布产物')
) -Message 'Portal 两个 Digest 都必须与同 Commit 的 Release 产物完全一致'

$directDeploy = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', '离线验收',
    '-ApprovalText', "DEPLOY IWORK $revision"
) -Mode queued -PreserveState
Assert-True -Condition (
    $directDeploy.ExitCode -eq 1 -and
    $directDeploy.Output.Contains('预检Run')
) -Message '未绑定成功预检Run时，即使确认词正确也不得触发部署'
Assert-True -Condition (
    -not (Test-Path -LiteralPath (Join-Path $directDeploy.StateDirectory 'deploy-iwork.yml.dispatched'))
) -Message '直接提供确认词不得触发部署 Workflow'
Remove-TestStateDirectory -Path $directDeploy.StateDirectory

$preflightResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', '部署前预检绑定', '-Wait'
) -Mode success
$preflightJson = $preflightResult.Output | ConvertFrom-Json
$preflightRunId = [string]$preflightJson.Run.RunIdentifier
Assert-True -Condition ($preflightRunId -eq '203-1') -Message '预检成功结果必须返回稳定Run标识'
Assert-True -Condition (
    ($preflightJson.Run.RunName -match '(?i)\bpreflight\b') -and
    ($preflightJson.Run.Workflow -eq 'iwork controlled production deployment')
) -Message '预检绑定结果必须确认部署Workflow身份和apply=false标题'

$changedPreview = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-PreflightRunId', $preflightRunId,
    '-ChangeDescription', '原始预览'
) -Mode success -PreserveState
$changedConfirmation = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-PreflightRunId', $preflightRunId,
    '-ChangeDescription', '已被修改',
    '-ApprovalText', "DEPLOY IWORK $revision"
) -Mode queued -PreserveState -ExistingStateDirectory $changedPreview.StateDirectory
Assert-True -Condition (
    $changedConfirmation.ExitCode -eq 1 -and
    $changedConfirmation.Output.Contains('参数') -and
    $changedConfirmation.Output.Contains('预览')
) -Message '确认前修改任一预览参数必须失败关闭'
Assert-True -Condition (
    -not (Test-Path -LiteralPath (Join-Path $changedPreview.StateDirectory 'deploy-iwork.yml.dispatched'))
) -Message '参数变化不得触发部署 Workflow'
Remove-TestStateDirectory -Path $changedPreview.StateDirectory

$previewResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-PreflightRunId', $preflightRunId,
    '-ChangeDescription', '离线验收'
) -Mode success -PreserveState
Assert-True -Condition ($previewResult.ExitCode -eq 4) -Message '缺少生产确认必须返回专用退出码'
$previewJson = $previewResult.Output | ConvertFrom-Json
Assert-True -Condition ($previewJson.Status -eq 'confirmation_required') -Message '必须返回确认预览'
Assert-True -Condition ($previewJson.Preview.ConfigDigest -eq $configDigest) -Message '确认预览必须展示 ConfigDigest'
Assert-True -Condition ($previewJson.Preview.ConfigArtifactDigest -eq $configArtifactDigest) -Message '确认预览必须展示 ConfigArtifactDigest'
Assert-True -Condition ($previewJson.RequiredApprovalText -eq "DEPLOY IWORK $revision") -Message 'iwork 确认词应绑定 Commit'
Assert-True -Condition (-not (Test-Path -LiteralPath (Join-Path $previewResult.StateDirectory 'deploy-iwork.yml.dispatched'))) -Message '未确认不得触发部署'

$deployResult = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-PreflightRunId', $preflightRunId,
    '-ChangeDescription', '离线验收',
    '-ApprovalText', "DEPLOY IWORK $revision"
) -Mode queued -PreserveState -ExistingStateDirectory $previewResult.StateDirectory
Assert-True -Condition ($deployResult.ExitCode -eq 0) -Message '精确确认后应允许触发假部署'
Assert-True -Condition (Test-Path -LiteralPath (Join-Path $deployResult.StateDirectory 'deploy-iwork.yml.dispatched')) -Message '假部署应被记录为已触发'
$deployLog = Get-Content -LiteralPath (Join-Path $deployResult.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($deployLog.Contains('apply=true')) -Message '部署必须传 apply=true'
Assert-True -Condition ($deployLog.Contains("config_digest=$configDigest")) -Message '部署必须传入发布验证过的 ConfigDigest'
Assert-True -Condition ($deployLog.Contains("config_artifact_digest=$configArtifactDigest")) -Message '部署必须传入发布验证过的 ConfigArtifactDigest'
Assert-True -Condition ($deployLog.Contains('release_request_id=66666666-7777-8888-9999-aaaaaaaaaaaa')) -Message 'Deploy 必须精确绑定成功 Release 的 request_id'
Assert-True -Condition ($deployLog.Contains('confirmation=DEPLOY IWORK')) -Message '应传 Workflow 原生确认词'
Assert-True -Condition ($deployLog -match 'request_id=[0-9a-f-]{36}') -Message 'Deploy 触发必须传入 GUID request_id'
Assert-True -Condition (
    -not (Get-ChildItem -LiteralPath (Join-Path $deployResult.StateDirectory 'confirmations') -Filter '*.json' -ErrorAction SilentlyContinue)
) -Message '确认预览必须在使用后单次消费，禁止重复触发'
Remove-TestStateDirectory -Path $deployResult.StateDirectory

$portalPreview = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'portal', '-Revision', $revision,
    '-PortalDigest', $portalDigest, '-ProxyDigest', $proxyDigest,
    '-ChangeDescription', 'Portal 离线验收'
) -Mode success -PreserveState
Assert-True -Condition ($portalPreview.ExitCode -eq 4) -Message 'Portal 缺少确认必须阻止'
$portalJson = $portalPreview.Output | ConvertFrom-Json
Assert-True -Condition ($portalJson.RequiredApprovalText -eq "DEPLOY PORTAL AND AUTHENTICATION $revision") -Message 'Portal 应使用更强确认词'
$portalDeploy = Invoke-SkillProcess -Arguments @(
    '-Action', 'deploy', '-Service', 'portal', '-Revision', $revision,
    '-PortalDigest', $portalDigest, '-ProxyDigest', $proxyDigest,
    '-ChangeDescription', 'Portal 离线验收',
    '-ApprovalText', "DEPLOY PORTAL AND AUTHENTICATION $revision"
) -Mode success -PreserveState -ExistingStateDirectory $portalPreview.StateDirectory
Assert-True -Condition ($portalDeploy.ExitCode -eq 0) -Message 'Portal 精确确认后应允许触发假部署'
$portalLog = Get-Content -LiteralPath (Join-Path $portalDeploy.StateDirectory 'arguments.log') -Raw
Assert-True -Condition ($portalLog.Contains('capability_drill=false')) -Message 'Portal 普通部署必须关闭 capability_drill'
Assert-True -Condition (
    -not $portalLog.Contains('rollback_drill=') -and
    -not $portalLog.Contains('rollback_drill_retry=') -and
    -not $portalLog.Contains('rollback_drill_recovery=')
) -Message 'Portal 不得传递已移除的旧回滚演练输入'
Remove-TestStateDirectory -Path $portalDeploy.StateDirectory

$invalidPreflight = Invoke-SkillProcess -Arguments @(
    '-Action', 'preflight', '-Service', 'iwork', '-Revision', $revision,
    '-ImageDigest', $imageDigest, '-ConfigDigest', $configDigest,
    '-ConfigArtifactDigest', $configArtifactDigest,
    '-ChangeDescription', '禁止迁移的预检',
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
$previousErrorActionPreference = $ErrorActionPreference
try {
    # Windows PowerShell 5.1会把预期的子进程stderr包装成NativeCommandError；
    # 此处只收集失败输出并在后续显式断言退出码。
    $ErrorActionPreference = 'Continue'
    $overrideOutput = @(& $engineExecutable -NoLogo -NoProfile -File $scriptPath `
        -Action status -Service iwork -GhExecutable $fakeGhPath -OutputJson 2>&1)
    $overrideExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
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
