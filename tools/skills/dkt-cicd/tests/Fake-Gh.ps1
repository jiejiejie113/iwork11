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
$portalDigest = 'sha256:' + ('2' * 64)
$proxyDigest = 'sha256:' + ('3' * 64)
$mode = if ($env:DKT_CICD_FAKE_MODE) { $env:DKT_CICD_FAKE_MODE } else { 'success' }
$logFailure = $env:DKT_CICD_FAKE_LOG_FAILURE -ceq '1'
$concurrentDispatch = $env:DKT_CICD_FAKE_CONCURRENT -ceq '1'
$invalidPortalDigests = $env:DKT_CICD_FAKE_INVALID_PORTAL_DIGESTS -ceq '1'
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

function Write-RunJson {
    param(
        [long]$Id,
        [string]$WorkflowName,
        [string]$Status,
        [AllowEmptyString()][string]$Conclusion,
        [string]$DisplayTitle = ''
    )

    $now = [DateTimeOffset]::UtcNow
    [ordered]@{
        databaseId = $Id
        workflowName = $WorkflowName
        displayTitle = $DisplayTitle
        status = $Status
        conclusion = $Conclusion
        headSha = $revision
        url = "https://github.com/example/actions/runs/$Id"
        createdAt = $now.ToString('o')
        startedAt = $now.ToString('o')
        updatedAt = $now.AddSeconds(10).ToString('o')
        event = 'workflow_dispatch'
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
        $items += Write-RunJson -Id 101 -WorkflowName 'CI' -Status 'completed' -Conclusion 'success'
    }
    elseif ($workflow -eq 'release.yml') {
        $items += Write-RunJson -Id 102 -WorkflowName 'Release' -Status 'completed' -Conclusion 'success'
    }
    elseif ($workflow -eq 'runner-smoke.yml') {
        $title = "Portal runner smoke $revision $portalDigest $proxyDigest"
        $items += Write-RunJson -Id 103 -WorkflowName 'Portal production runner smoke' -Status 'completed' -Conclusion 'success' -DisplayTitle $title
    }
    else {
        $items += Write-RunJson -Id 104 -WorkflowName 'Deploy' -Status 'completed' -Conclusion 'success'
    }

    if (Test-Path -LiteralPath (Join-Path $stateDirectory "$workflow.dispatched")) {
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
            Write-RunJson -Id $newId -WorkflowName $workflow -Status $status -Conclusion $conclusion
        ) + $items
        if ($concurrentDispatch) {
            $items = @(
                Write-RunJson -Id ($newId + 1000) -WorkflowName $workflow -Status $status -Conclusion $conclusion
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
        Write-Output "ghcr.io/guchenkano/iwork@$imageDigest"
        if ($invalidPortalDigests) {
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$portalDigest"
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$proxyDigest"
        }
        else {
            Write-Output "ghcr.io/guchenkano/dtd-nginx@$portalDigest"
            Write-Output "ghcr.io/guchenkano/dtd-oauth2-proxy@$proxyDigest"
        }
        exit 0
    }

    $id = [long]$RemainingArguments[2]
    $status = if ($mode -in @('queued', 'in_progress')) { $mode } else { 'completed' }
    $conclusion = if ($status -eq 'completed') { $mode } else { '' }
    $steps = @(
        [ordered]@{
            name = '执行'
            conclusion = if ($mode -eq 'failure') { 'failure' } else { 'success' }
        }
    )
    [ordered]@{
        databaseId = $id
        workflowName = 'fake workflow'
        status = $status
        conclusion = $conclusion
        headSha = $revision
        url = "https://github.com/example/actions/runs/$id"
        createdAt = '2026-08-26T00:00:00Z'
        startedAt = '2026-08-26T00:00:01Z'
        updatedAt = '2026-08-26T00:00:11Z'
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
