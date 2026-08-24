[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('iwork', 'portal')]
    [string]$RunnerRole,

    [switch]$RegistrationTokenFromStdin,

    [switch]$ResumeConfiguredRunner,

    [string]$InstallRoot = 'D:\DM\actions-runner',
    [string]$LockRoot = 'D:\DM\cicd-locks',
    [string]$StateRoot = 'D:\DM\cicd-state',
    [string]$PolicyRoot = 'D:\DM\cicd-policy',
    [string]$FallbackProxy = 'http://192.168.1.45:8899'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$RUNNER_VERSION = '2.336.0'
$RUNNER_PACKAGE = 'actions-runner-win-x64-2.336.0.zip'
$RUNNER_PACKAGE_SHA256 = 'd59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162'
$RUNNER_DOWNLOAD_URL = 'https://github.com/actions/runner/releases/download/v2.336.0/actions-runner-win-x64-2.336.0.zip'
$EXPECTED_IDENTITY = 'DONGMING\shuju'
$TASK_PATH = '\DITU\'
$WORK_DIRECTORY = '_work'

$ROLE_CONFIG = @{
    iwork = @{
        RepositoryUrl = 'https://github.com/GuChenkano/iwork'
        Repository = 'GuChenkano/iwork'
        BranchRef = 'refs/heads/Keycloak'
        WorkflowName = 'iwork production runner smoke'
        WorkflowRef = 'GuChenkano/iwork/.github/workflows/runner-smoke.yml@refs/heads/Keycloak'
        RunnerName = 'DTDSERVER-iwork-01'
        Labels = 'dkt-prod,iwork'
        TaskName = 'GitHub-Runner-iwork'
    }
    portal = @{
        RepositoryUrl = 'https://github.com/GuChenkano/DTD_nginx'
        Repository = 'GuChenkano/DTD_nginx'
        BranchRef = 'refs/heads/feature/keycloak-migration'
        WorkflowName = 'Portal production runner smoke'
        WorkflowRef = 'GuChenkano/DTD_nginx/.github/workflows/runner-smoke.yml@refs/heads/feature/keycloak-migration'
        RunnerName = 'DTDSERVER-portal-01'
        Labels = 'dkt-prod,portal'
        TaskName = 'GitHub-Runner-portal'
    }
}

function Assert-Administrator {
    $principal = [Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This installer must run in an elevated DONGMING\shuju session.'
    }
}

function Assert-ExpectedIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -ne $EXPECTED_IDENTITY) {
        throw "Unexpected installer identity: $identity"
    }
}

function Get-RegistrationToken {
    if (-not $RegistrationTokenFromStdin) {
        throw 'The registration token must be provided through redirected stdin.'
    }
    $token = [Console]::In.ReadLine()
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'The redirected registration token is empty.'
    }
    return $token.Trim()
}

function Get-VerifiedRunnerPackage {
    param([string]$PackagePath)

    if (Test-Path -LiteralPath $PackagePath -PathType Leaf) {
        $cachedHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($cachedHash -eq $RUNNER_PACKAGE_SHA256) {
            return
        }
        Remove-Item -LiteralPath $PackagePath -Force
    }

    try {
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $RUNNER_DOWNLOAD_URL `
            -OutFile $PackagePath `
            -TimeoutSec 600
    }
    catch {
        if ([string]::IsNullOrWhiteSpace($FallbackProxy)) {
            throw
        }
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $RUNNER_DOWNLOAD_URL `
            -OutFile $PackagePath `
            -Proxy $FallbackProxy `
            -TimeoutSec 600
    }

    $actualHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $RUNNER_PACKAGE_SHA256) {
        Remove-Item -LiteralPath $PackagePath -Force -ErrorAction SilentlyContinue
        throw "Runner package SHA-256 mismatch: $actualHash"
    }
}

function Ensure-ScheduledTaskFolder {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $comTaskPath = $TASK_PATH.TrimEnd('\')
    try {
        $null = $service.GetFolder($comTaskPath)
    }
    catch {
        $rootFolder = $service.GetFolder('\')
        $null = $rootFolder.CreateFolder($TASK_PATH.Trim('\'))
    }
}

function Write-AdmissionHook {
    param(
        [hashtable]$Config,
        [string]$HookPath
    )

    $hook = @'
$ErrorActionPreference = 'Stop'
$expectedEvent = 'workflow_dispatch'
$expectedActor = 'GuChenkano'
$expectedRepository = '__REPOSITORY__'
$expectedRef = '__BRANCH_REF__'
$expectedWorkflow = '__WORKFLOW_NAME__'
$expectedWorkflowRef = '__WORKFLOW_REF__'

if ($env:GITHUB_EVENT_NAME -ne $expectedEvent) {
    throw "Rejected event: $env:GITHUB_EVENT_NAME"
}
if ($env:GITHUB_ACTOR -ne $expectedActor) {
    throw "Rejected actor: $env:GITHUB_ACTOR"
}
if ($env:GITHUB_REPOSITORY -ne $expectedRepository) {
    throw "Rejected repository: $env:GITHUB_REPOSITORY"
}
if ($env:GITHUB_REF -ne $expectedRef) {
    throw "Rejected ref: $env:GITHUB_REF"
}
if ($env:GITHUB_WORKFLOW -ne $expectedWorkflow) {
    throw "Rejected workflow: $env:GITHUB_WORKFLOW"
}
if ($env:GITHUB_WORKFLOW_REF -ne $expectedWorkflowRef) {
    throw "Rejected workflow ref: $env:GITHUB_WORKFLOW_REF"
}
"Runner admission accepted: $env:GITHUB_WORKFLOW_REF; actor=$env:GITHUB_ACTOR"
'@
    $hook = $hook.Replace('__REPOSITORY__', $Config.Repository)
    $hook = $hook.Replace('__BRANCH_REF__', $Config.BranchRef)
    $hook = $hook.Replace('__WORKFLOW_NAME__', $Config.WorkflowName)
    $hook = $hook.Replace('__WORKFLOW_REF__', $Config.WorkflowRef)
    Set-Content -LiteralPath $HookPath -Value $hook -Encoding ASCII
}

function Write-RunnerWrapper {
    param(
        [string]$WrapperPath,
        [string]$RunnerDirectory,
        [string]$StatePath
    )

    $wrapper = @'
$ErrorActionPreference = 'Stop'
$runnerDirectory = '__RUNNER_DIRECTORY__'
$statePath = '__STATE_PATH__'
$deadline = [DateTimeOffset]::Now.AddMinutes(30)

Set-Location -LiteralPath $runnerDirectory
while ([DateTimeOffset]::Now -lt $deadline) {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        break
    }
    Start-Sleep -Seconds 10
}
if ([DateTimeOffset]::Now -ge $deadline) {
    "$(Get-Date -Format o) Docker API timeout" | Out-File -LiteralPath $statePath -Append -Encoding utf8
    exit 70
}

"$(Get-Date -Format o) Runner starting" | Out-File -LiteralPath $statePath -Append -Encoding utf8
& (Join-Path $runnerDirectory 'run.cmd')
$runnerExitCode = $LASTEXITCODE
"$(Get-Date -Format o) Runner exited: $runnerExitCode" | Out-File -LiteralPath $statePath -Append -Encoding utf8
exit $runnerExitCode
'@
    $wrapper = $wrapper.Replace('__RUNNER_DIRECTORY__', $RunnerDirectory)
    $wrapper = $wrapper.Replace('__STATE_PATH__', $StatePath)
    Set-Content -LiteralPath $WrapperPath -Value $wrapper -Encoding ASCII
}

Assert-Administrator
Assert-ExpectedIdentity
$config = $ROLE_CONFIG[$RunnerRole]

$installDirectory = Join-Path $InstallRoot $RunnerRole
$packageDirectory = Join-Path $StateRoot 'packages'
$packagePath = Join-Path $packageDirectory $RUNNER_PACKAGE
$hookPath = Join-Path $PolicyRoot "$RunnerRole-job-started.ps1"
$wrapperPath = Join-Path $installDirectory 'Start-Runner.ps1'
$statePath = Join-Path $StateRoot "$RunnerRole-runner.log"

foreach ($directory in @($InstallRoot, $LockRoot, $StateRoot, $PolicyRoot, $packageDirectory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$runnerConfigPath = Join-Path $installDirectory '.runner'
if ($ResumeConfiguredRunner) {
    if (-not (Test-Path -LiteralPath $runnerConfigPath -PathType Leaf)) {
        throw "Configured runner cannot be resumed because .runner is missing: $installDirectory"
    }
}
else {
    if (Test-Path -LiteralPath $installDirectory) {
        throw "Runner installation directory already exists: $installDirectory"
    }
    $registrationToken = Get-RegistrationToken
    Get-VerifiedRunnerPackage -PackagePath $packagePath
    try {
        New-Item -ItemType Directory -Path $installDirectory | Out-Null
        Expand-Archive -LiteralPath $packagePath -DestinationPath $installDirectory

        Push-Location $installDirectory
        try {
            & .\config.cmd `
                --unattended `
                --url $config.RepositoryUrl `
                --token $registrationToken `
                --name $config.RunnerName `
                --labels $config.Labels `
                --work $WORK_DIRECTORY `
                --replace
            if ($LASTEXITCODE -ne 0) {
                throw "Runner registration failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            $registrationToken = $null
            Pop-Location
        }
        if (-not (Test-Path -LiteralPath $runnerConfigPath -PathType Leaf)) {
            throw 'Runner registration did not create the .runner configuration file.'
        }
    }
    catch {
        $registrationToken = $null
        if (
            (Test-Path -LiteralPath $installDirectory -PathType Container) -and
            -not (Test-Path -LiteralPath $runnerConfigPath -PathType Leaf)
        ) {
            Remove-Item -LiteralPath $installDirectory -Recurse -Force
        }
        throw
    }
}

Write-AdmissionHook -Config $config -HookPath $hookPath
Set-Content `
    -LiteralPath (Join-Path $installDirectory '.env') `
    -Value "ACTIONS_RUNNER_HOOK_JOB_STARTED=$hookPath" `
    -Encoding ASCII
Write-RunnerWrapper `
    -WrapperPath $wrapperPath `
    -RunnerDirectory $installDirectory `
    -StatePath $statePath

Ensure-ScheduledTaskFolder
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperPath`""
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $EXPECTED_IDENTITY
$principal = New-ScheduledTaskPrincipal `
    -UserId $EXPECTED_IDENTITY `
    -LogonType S4U `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskPath $TASK_PATH `
    -TaskName $config.TaskName `
    -Action $action `
    -Trigger @($startupTrigger, $logonTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "GitHub Actions production runner for $RunnerRole; workflow_dispatch smoke validation only" `
    -Force | Out-Null
Start-ScheduledTask -TaskPath $TASK_PATH -TaskName $config.TaskName

[pscustomobject]@{
    RunnerRole = $RunnerRole
    RunnerVersion = $RUNNER_VERSION
    RunnerName = $config.RunnerName
    InstallDirectory = $installDirectory
    Task = "$TASK_PATH$($config.TaskName)"
    AdmissionHook = $hookPath
} | Format-List
