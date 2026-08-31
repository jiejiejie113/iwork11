param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$stateDirectory = $env:DKT_CICD_FAKE_STATE_DIR
if ([String]::IsNullOrWhiteSpace($stateDirectory)) {
    throw '缺少 DKT_CICD_FAKE_STATE_DIR。'
}
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null

$revision = if ($env:DKT_CICD_FAKE_REVISION) {
    $env:DKT_CICD_FAKE_REVISION
}
else {
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
}
$imageDigest = 'sha256:' + ('1' * 64)
$configDigest = 'sha256:' + ('5' * 64)
$configArtifactDigest = 'sha256:' + ('7' * 64)
$configArtifactId = '301'
$manifestArtifactId = '401'
$manifestArtifactDigest = 'sha256:' + ('8' * 64)
$ciRequestId = '11111111-2222-3333-4444-555555555555'
$releaseRequestId = '66666666-7777-8888-9999-aaaaaaaaaaaa'
$portalDigest = 'sha256:' + ('2' * 64)
$proxyDigest = 'sha256:' + ('3' * 64)
$mode = if ($env:DKT_CICD_FAKE_MODE) { $env:DKT_CICD_FAKE_MODE } else { 'success' }
$logFailure = $env:DKT_CICD_FAKE_LOG_FAILURE -ceq '1'
$concurrentDispatch = $env:DKT_CICD_FAKE_CONCURRENT -ceq '1'
$invalidPortalDigests = $env:DKT_CICD_FAKE_INVALID_PORTAL_DIGESTS -ceq '1'
$invalidImageDigests = $env:DKT_CICD_FAKE_INVALID_IMAGE_DIGESTS -ceq '1'
$missingConfigDigest = $env:DKT_CICD_FAKE_MISSING_CONFIG_DIGEST -ceq '1'
$missingConfigArtifactDigest = $env:DKT_CICD_FAKE_MISSING_CONFIG_ARTIFACT_DIGEST -ceq '1'
$invalidConfigArtifactDigests = $env:DKT_CICD_FAKE_INVALID_CONFIG_ARTIFACT_DIGESTS -ceq '1'
$prefixedConfigArtifactDigest = $env:DKT_CICD_FAKE_PREFIXED_CONFIG_ARTIFACT_DIGEST -ceq '1'
$sourcePlaceholderConfigArtifactDigest = $env:DKT_CICD_FAKE_SOURCE_PLACEHOLDER_CONFIG_ARTIFACT_DIGEST -ceq '1'
$preflightSourcePlaceholderConfigArtifactDigest = $env:DKT_CICD_FAKE_PREFLIGHT_SOURCE_PLACEHOLDER_CONFIG_ARTIFACT_DIGEST -ceq '1'
$malformedConfigArtifactDigest = $env:DKT_CICD_FAKE_MALFORMED_CONFIG_ARTIFACT_DIGEST -ceq '1'
$mismatchedReleaseDigest = $env:DKT_CICD_FAKE_MISMATCHED_RELEASE_DIGEST -ceq '1'
$releaseEventPush = $env:DKT_CICD_FAKE_RELEASE_EVENT_PUSH -ceq '1'
$oldCiEventPush = $env:DKT_CICD_FAKE_OLD_CI_EVENT_PUSH -ceq '1'
$duplicateCiRequest = $env:DKT_CICD_FAKE_DUPLICATE_CI_REQUEST -ceq '1'
$discoveryDelayQueries = if ($env:DKT_CICD_FAKE_DISCOVERY_DELAY_QUERIES -match '^\d+$') {
    [int]$env:DKT_CICD_FAKE_DISCOVERY_DELAY_QUERIES
}
else {
    0
}
$argumentLog = Join-Path $stateDirectory 'arguments.log'
Add-Content -LiteralPath $argumentLog -Value ($RemainingArguments -join [char]31) -Encoding UTF8

function Get-ArgumentValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $index = [Array]::IndexOf($RemainingArguments, $Name)
    if ($index -lt 0 -or $index + 1 -ge $RemainingArguments.Count) {
        return $null
    }
    return $RemainingArguments[$index + 1]
}

function Get-WorkflowInputValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $prefix = "$Name="
    for ($index = 0; $index -lt $RemainingArguments.Count - 1; $index++) {
        if ($RemainingArguments[$index] -ne '-f') {
            continue
        }
        $inputValue = [string]$RemainingArguments[$index + 1]
        if ($inputValue.StartsWith($prefix, [StringComparison]::Ordinal)) {
            return $inputValue.Substring($prefix.Length)
        }
    }
    return $null
}

function Write-RunJson {
    param(
        [long]$Id,
        [string]$WorkflowName,
        [string]$Status,
        [AllowEmptyString()][string]$Conclusion,
        [string]$DisplayTitle = '',
        [string]$RunName = '',
        [string]$Event = 'workflow_dispatch'
    )

    $now = [DateTimeOffset]::UtcNow
    [ordered]@{
        databaseId = $Id
        attempt = 1
        workflowName = $WorkflowName
        displayTitle = if ([String]::IsNullOrWhiteSpace($RunName)) { $DisplayTitle } else { $RunName }
        runName = $RunName
        status = $Status
        conclusion = $Conclusion
        headSha = $revision
        url = "https://github.com/example/actions/runs/$Id"
        createdAt = $now.ToString('o')
        startedAt = $now.ToString('o')
        updatedAt = $now.AddSeconds(10).ToString('o')
        event = $Event
    }
}

if ($RemainingArguments.Count -ge 2 -and $RemainingArguments[0] -eq 'auth') {
    exit 0
}

if ($RemainingArguments.Count -ge 1 -and $RemainingArguments[0] -eq 'api') {
    $revision
    exit 0
}

if ($RemainingArguments.Count -ge 3 -and
    $RemainingArguments[0] -eq 'workflow' -and
    $RemainingArguments[1] -eq 'run') {
    $workflow = $RemainingArguments[2]
    $requestId = Get-WorkflowInputValue -Name 'request_id'
    if (-not [String]::IsNullOrWhiteSpace($requestId)) {
        $requestId | Set-Content -LiteralPath (Join-Path $stateDirectory "$workflow.request-id") -Encoding UTF8
    }
    New-Item -ItemType File -Path (Join-Path $stateDirectory "$workflow.dispatched") -Force | Out-Null
    exit 0
}

if ($RemainingArguments.Count -ge 2 -and
    $RemainingArguments[0] -eq 'run' -and
    $RemainingArguments[1] -eq 'list') {
    $workflow = Get-ArgumentValue -Name '--workflow'
    if ([String]::IsNullOrWhiteSpace($workflow)) {
        $conclusion = if ($mode -in @('queued', 'in_progress')) { '' } else { $mode }
        @(
            Write-RunJson -Id 900 -WorkflowName 'fake workflow' -Status $(
                if ($mode -in @('queued', 'in_progress')) { $mode } else { 'completed' }
            ) -Conclusion $conclusion
        ) | ConvertTo-Json -Depth 6
        exit 0
    }

    $items = @()
    if ($workflow -eq 'ci.yml') {
        $items += Write-RunJson `
            -Id 101 `
            -WorkflowName 'CI' `
            -Status 'completed' `
            -Conclusion 'success' `
            -RunName "iwork ci $revision $ciRequestId" `
            -Event $(if ($oldCiEventPush) { 'push' } else { 'workflow_dispatch' })
        if ($duplicateCiRequest) {
            $items += Write-RunJson `
                -Id 105 `
                -WorkflowName 'CI' `
                -Status 'completed' `
                -Conclusion 'success' `
                -RunName "iwork ci duplicate $revision $ciRequestId"
        }
    }
    elseif ($workflow -eq 'release.yml') {
        $releaseEvent = if ($releaseEventPush) { 'push' } else { 'workflow_dispatch' }
        $items += Write-RunJson `
            -Id 102 `
            -WorkflowName 'Release' `
            -Status 'completed' `
            -Conclusion 'success' `
            -RunName "iwork release $revision $releaseRequestId" `
            -Event $releaseEvent
    }
    elseif ($workflow -eq 'runner-smoke.yml') {
        $title = "Portal runner smoke $revision $portalDigest $proxyDigest"
        $items += Write-RunJson -Id 103 -WorkflowName 'Portal production runner smoke' -Status 'completed' -Conclusion 'success' -DisplayTitle $title
    }
    else {
        $items += Write-RunJson `
            -Id 104 `
            -WorkflowName 'iwork controlled production deployment' `
            -Status 'completed' `
            -Conclusion 'success' `
            -RunName 'iwork preflight aaaaaaaa 11111111-2222-3333-4444-555555555555'
    }

    if (Test-Path -LiteralPath (Join-Path $stateDirectory "$workflow.dispatched")) {
        $requestIdPath = Join-Path $stateDirectory "$workflow.request-id"
        $requestId = if (Test-Path -LiteralPath $requestIdPath) {
            (Get-Content -LiteralPath $requestIdPath -Raw -Encoding UTF8).Trim()
        }
        else {
            $null
        }
        $discoveryCounterPath = Join-Path $stateDirectory "$workflow.discovery-count"
        $discoveryCount = if (Test-Path -LiteralPath $discoveryCounterPath) {
            [int](Get-Content -LiteralPath $discoveryCounterPath -Raw -Encoding UTF8)
        }
        else {
            0
        }
        $discoveryCount++
        $discoveryCount | Set-Content -LiteralPath $discoveryCounterPath -Encoding UTF8
        if ($discoveryCount -le $discoveryDelayQueries) {
            $items | ConvertTo-Json -Depth 6
            exit 0
        }
        $newId = switch ($workflow) {
            'ci.yml' { 201 }
            'release.yml' { 202 }
            'deploy-iwork.yml' { 203 }
            'deploy-portal.yml' { 204 }
            default { 299 }
        }
        $status = if ($mode -in @('queued', 'in_progress')) { $mode } else { 'completed' }
        $conclusion = if ($status -eq 'completed') { $mode } else { '' }
        $items = @(
            Write-RunJson -Id $newId -WorkflowName $workflow -Status $status -Conclusion $conclusion -RunName $requestId
        ) + $items
        if ($concurrentDispatch) {
            $items = @(
                Write-RunJson -Id ($newId + 1000) -WorkflowName $workflow -Status $status -Conclusion $conclusion -RunName $requestId
            ) + $items
        }
    }
    $items | ConvertTo-Json -Depth 6
    exit 0
}

if ($RemainingArguments.Count -ge 3 -and
    $RemainingArguments[0] -eq 'run' -and
    $RemainingArguments[1] -eq 'watch') {
    if ($mode -eq 'failure') { exit 1 }
    exit 0
}

if ($RemainingArguments.Count -ge 3 -and
    $RemainingArguments[0] -eq 'run' -and
    $RemainingArguments[1] -eq 'view') {
    if ($RemainingArguments -contains '--log-failed') {
        if ($logFailure) {
            Write-Error '模拟失败日志读取失败'
            exit 2
        }
        Write-Output ('token=' + ('gh' + 'p_FAKE_TOKEN_VALUE'))
        Write-Output ('token=' + ('github' + '_pat_FAKE_NEW_TOKEN'))
        Write-Output 'password=FAKE_PASSWORD_VALUE'
        Write-Output ('https://fake-user:' + 'fake-uri-password@example.invalid/path')
        Write-Output '真实失败原因：候选镜像健康检查失败'
        exit 0
    }
    if ($RemainingArguments -contains '--log') {
        if ($logFailure) {
            Write-Error '模拟完整日志读取失败'
            exit 2
        }
        $runId = [long]$RemainingArguments[2]
        $effectiveImageDigest = if ($mismatchedReleaseDigest -and $runId -eq 102) {
            'sha256:' + ('9' * 64)
        }
        else {
            $imageDigest
        }
        $effectivePortalDigest = if ($mismatchedReleaseDigest -and $runId -eq 102) {
            'sha256:' + ('8' * 64)
        }
        else {
            $portalDigest
        }
        $effectiveProxyDigest = if ($mismatchedReleaseDigest -and $runId -eq 102) {
            'sha256:' + ('7' * 64)
        }
        else {
            $proxyDigest
        }
        Write-Output "ghcr.io/guchenkano/iwork@$effectiveImageDigest"
        Write-Output "IWORK_IMAGE_DIGEST=$effectiveImageDigest"
        if (-not $missingConfigDigest) {
            Write-Output "IWORK_CONFIG_DIGEST=$configDigest"
        }
        if (-not $missingConfigArtifactDigest -and $runId -in @(102, 202, 203)) {
            if ($malformedConfigArtifactDigest) {
                Write-Output 'IWORK_CONFIG_ARTIFACT_DIGEST=not-a-sha256-digest'
            }
            elseif ($sourcePlaceholderConfigArtifactDigest) {
                Write-Output 'IWORK_CONFIG_ARTIFACT_DIGEST=$artifactDigest'
                Write-Output 'IWORK_CONFIG_ARTIFACT_DIGEST=$artifactDigest"^[[0m'
                Write-Output "IWORK_CONFIG_ARTIFACT_DIGEST=$configArtifactDigest"
            }
            elseif ($preflightSourcePlaceholderConfigArtifactDigest) {
                Write-Output 'IWORK_CONFIG_ARTIFACT_DIGEST=$env:CONFIG_ARTIFACT_DIGEST"^[[0m'
                Write-Output "IWORK_CONFIG_ARTIFACT_DIGEST=$configArtifactDigest"
            }
            elseif ($prefixedConfigArtifactDigest) {
                Write-Output "publish`t记录发布身份`tIWORK_CONFIG_ARTIFACT_DIGEST=$configArtifactDigest"
            }
            else {
                Write-Output "IWORK_CONFIG_ARTIFACT_DIGEST=$configArtifactDigest"
            }
            if ($runId -in @(102, 202)) {
                Write-Output "IWORK_CONFIG_ARTIFACT_ID=$configArtifactId"
                Write-Output "IWORK_CONFIG_ARTIFACT_NAME=iwork-production-config-$revision"
                Write-Output "IWORK_RELEASE_MANIFEST_ARTIFACT_ID=$manifestArtifactId"
                Write-Output "IWORK_RELEASE_MANIFEST_ARTIFACT_NAME=iwork-release-manifest-$revision"
                Write-Output "IWORK_RELEASE_MANIFEST_ARTIFACT_DIGEST=$manifestArtifactDigest"
            }
            if ($invalidConfigArtifactDigests) {
                Write-Output "IWORK_CONFIG_ARTIFACT_DIGEST=sha256:$('8' * 64)"
            }
        }
        if ($invalidImageDigests) {
            Write-Output "ghcr.io/guchenkano/iwork@sha256:$('4' * 64)"
        }
        if ($invalidPortalDigests) {
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$effectivePortalDigest"
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$effectiveProxyDigest"
        }
        else {
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$effectivePortalDigest"
            Write-Output "ghcr.io/guchenkano/dtd-oauth2-proxy@$effectiveProxyDigest"
        }
        exit 0
    }

    $id = [long]$RemainingArguments[2]
    # Run 203 是部署测试预先绑定的成功 apply=false 预检证据；后续部署可用
    # queued/in_progress 模式模拟新部署 Run，但不能改变这份历史预检证据。
    $status = if ($id -eq 203) {
        'completed'
    }
    elseif ($mode -in @('queued', 'in_progress')) {
        $mode
    }
    else {
        'completed'
    }
    $conclusion = if ($status -eq 'completed') {
        if ($id -eq 203) { 'success' } else { $mode }
    }
    else {
        ''
    }
    $requestIdFileName = switch ($id) {
        201 { 'ci.yml.request-id' }
        202 { 'release.yml.request-id' }
        203 { 'deploy-iwork.yml.request-id' }
        204 { 'deploy-portal.yml.request-id' }
        default { $null }
    }
    $requestIdPath = if ($null -ne $requestIdFileName) {
        Join-Path $stateDirectory $requestIdFileName
    }
    else {
        $null
    }
    $requestId = if ($null -ne $requestIdPath) {
        if (Test-Path -LiteralPath $requestIdPath -PathType Leaf) {
            (Get-Content -LiteralPath $requestIdPath -Raw -Encoding UTF8).Trim()
        }
        else {
            switch ($id) {
                203 { '11111111-2222-3333-4444-555555555555' }
                default { $null }
            }
        }
    }
    else {
        switch ($id) {
            104 { '11111111-2222-3333-4444-555555555555' }
            203 { '11111111-2222-3333-4444-555555555555' }
            default { $null }
        }
    }
    $workflowName = switch ($id) {
        201 { 'ci.yml' }
        202 { 'release.yml' }
        203 { 'iwork controlled production deployment' }
        204 { 'deploy-portal.yml' }
        default { 'fake workflow' }
    }
    $displayTitle = if ($id -eq 203) {
        "iwork preflight $requestId"
    }
    else {
        $requestId
    }
    $steps = @(
        [ordered]@{
            name = '执行'
            conclusion = if ($id -eq 203 -or $mode -ne 'failure') { 'success' } else { 'failure' }
        }
    )
    [ordered]@{
        databaseId = $id
        attempt = 1
        workflowName = $workflowName
        displayTitle = $displayTitle
        runName = $displayTitle
        status = $status
        conclusion = $conclusion
        headSha = $revision
        url = "https://github.com/example/actions/runs/$id"
        createdAt = '2026-08-26T00:00:00Z'
        startedAt = '2026-08-26T00:00:01Z'
        updatedAt = '2026-08-26T00:00:11Z'
        event = 'workflow_dispatch'
        jobs = @(
            [ordered]@{
                name = 'fake job'
                conclusion = $conclusion
                steps = $steps
            }
        )
    } | ConvertTo-Json -Depth 8
    exit 0
}

Write-Error "Fake gh 不支持参数：$($RemainingArguments -join ' ')"
exit 2
