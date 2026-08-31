"""阶段4 iwork受控生产部署安全契约测试。"""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess

import pytest
import yaml


# ======
# 阶段4文件路径配置
ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "deploy-iwork.yml"
DEPLOY_SCRIPT_PATH = ROOT / "scripts" / "Invoke-IworkProductionDeployment.ps1"
COORDINATION_MODULE_PATH = ROOT / "scripts" / "ProductionCoordination.psm1"
POLICY_INSTALLER_PATH = ROOT / "scripts" / "Install-IworkProductionDeployment.ps1"
RUNNER_INSTALLER_PATH = ROOT / "scripts" / "Install-GitHubProductionRunner.ps1"
START_SCRIPT_PATH = ROOT / "start.sh"
COMPOSE_PATH = ROOT / "docker-compose.yml"
GIT_ATTRIBUTES_PATH = ROOT / ".gitattributes"
CANDIDATE_DIGEST = "sha256:" + "1" * 64
CANDIDATE_REVISION = "2" * 40
PREVIOUS_DIGEST = "sha256:" + "9" * 64
PREVIOUS_REVISION = "8" * 40
DEPLOYMENT_RUN_ID = "123456-1"
REQUEST_ID = "12345678-1234-1234-1234-123456789abc"
PREFLIGHT_RUN_ID = "654321-1"
PREFLIGHT_REQUEST_ID = "abcdefab-cdef-abcd-efab-cdefabcdefab"
CONFIG_ARTIFACT_DIGEST = "sha256:" + "7" * 64
SYSTEM_ROOT = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
WHOAMI_EXE = SYSTEM_ROOT / "System32" / "whoami.exe"
POWERSHELL_EXE = (
    SYSTEM_ROOT / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
)
EXPECTED_COORDINATION_MODULE_SHA256 = (
    "0f2e7346e32bcc3dd59195b607c0ade58d11e3ee264d16292e8e669a7f614bc7"
)


def _write_config_bundle(
    bundle_path: Path,
    *,
    compose_content: bytes,
    profile_content: bytes,
    source_commit: str = CANDIDATE_REVISION,
    image_digest: str = CANDIDATE_DIGEST,
) -> str:
    """写入符合固定Schema的隔离生产配置包。

    Args:
        bundle_path (Path): 配置包根目录。
        compose_content (bytes): Compose文件字节。
        profile_content (bytes): 生产环境文件字节。
        source_commit (str): 配置来源Commit。
        image_digest (str): 绑定的应用镜像Digest。

    Returns:
        str: 配置包逻辑Digest。
    """
    bundle_path.joinpath("env").mkdir(parents=True)
    bundle_path.joinpath("docker-compose.yml").write_bytes(compose_content)
    bundle_path.joinpath("env", "production.env").write_bytes(profile_content)
    manifest = {
        "schema": "iwork-production-config/v1",
        "application": "iwork",
        "source_commit": source_commit,
        "image_digest": image_digest,
        "compose_sha256": hashlib.sha256(compose_content).hexdigest(),
        "production_env_sha256": hashlib.sha256(profile_content).hexdigest(),
    }
    canonical = "".join(f"{key}={value}\n" for key, value in manifest.items())
    config_digest = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
    manifest["config_digest"] = config_digest
    bundle_path.joinpath("config-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_digest


def _configure_isolated_acl(
    tmp_path: Path,
    paths: list[Path],
    *,
    directory_paths: set[Path],
) -> str:
    """为测试对象设置关闭继承的当前SID+SYSTEM显式DACL。

    Args:
        tmp_path (Path): 测试临时目录。
        paths (list[Path]): 需要设置ACL的对象路径。
        directory_paths (set[Path]): 其中的目录路径集合。

    Returns:
        str: 测试对象当前Owner的SID。

    Raises:
        RuntimeError: 本机无法应用或读取Windows ACL时，给出明确原因。
    """
    setup_path = tmp_path / "configure-test-acl.ps1"
    setup_path.write_text(
        r"""param(
    [string]$Paths,
    [string]$DirectoryPaths
)
$ErrorActionPreference = 'Stop'
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$pathList = @($Paths -split '\|')
$directorySet = @($DirectoryPaths -split '\|' |
    Where-Object { -not [String]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { [IO.Path]::GetFullPath($_) })
    foreach ($path in $pathList) {
        $fullPath = [IO.Path]::GetFullPath($path)
        $item = Get-Item -LiteralPath $fullPath -Force
        $acl = if ($item.PSIsContainer) {
            [Security.AccessControl.DirectorySecurity]::new()
        }
        else {
            [Security.AccessControl.FileSecurity]::new()
        }
        $null = $acl.SetAccessRuleProtection($true, $false)
        $setOwnerError = $null
        try { $acl.SetOwner($currentSid) }
        catch { $setOwnerError = $_ }
    $readRights = if ($fullPath -in $directorySet) {
        [Security.AccessControl.FileSystemRights]::ListDirectory
    }
    else {
        [Security.AccessControl.FileSystemRights]::ReadAndExecute
    }
    $currentRights = if ($fullPath -in $directorySet) {
        [Security.AccessControl.FileSystemRights]::Modify
    }
    else {
        $readRights
    }
    $none = [Security.AccessControl.InheritanceFlags]::None
    $noPropagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $null = $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid, $currentRights, $none, $noPropagation, $allow
    ))
    $null = $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $systemSid, [Security.AccessControl.FileSystemRights]::FullControl,
        $none, $noPropagation, $allow
    ))
    if ($item.PSIsContainer) {
        [IO.Directory]::SetAccessControl($fullPath, $acl)
    }
    else {
        [IO.File]::SetAccessControl($fullPath, $acl)
    }
    $owner = (Get-Item -LiteralPath $fullPath -Force).
        GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($null -ne $setOwnerError -or $owner -cne $currentSid.Value) {
        try {
            $null = & "$env:SystemRoot\System32\icacls.exe" $fullPath /setowner ("*" + $currentSid.Value) /C 2>&1
        }
        catch {
            $detail = if ($null -ne $setOwnerError) { $setOwnerError.Exception.Message } else { $_.Exception.Message }
            throw "无法调用icacls设置测试对象Owner：$detail"
        }
        if ($LASTEXITCODE -ne 0) {
            $detail = if ($null -ne $setOwnerError) { $setOwnerError.Exception.Message } else { 'Owner回读不匹配' }
            throw "icacls设置测试对象Owner失败：$fullPath；$detail"
        }
        $owner = (Get-Item -LiteralPath $fullPath -Force).
            GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
        if ($owner -cne $currentSid.Value) {
            throw "ACL Owner校验失败，icacls后仍为非当前SID：$owner"
        }
    }
}
$owners = @($pathList | ForEach-Object {
    (Get-Item -LiteralPath ([IO.Path]::GetFullPath($_)) -Force).
        GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
})
if (@($owners | Where-Object { $_ -cne $currentSid.Value }).Count -gt 0) {
    throw "ACL Owner校验失败，仍存在非当前SID Owner：$($owners -join ',')"
}
[Console]::Out.Write($currentSid.Value)
""",
        # Windows PowerShell 5.1 按系统代码页读取无BOM脚本；加入UTF-8 BOM避免中文
        # 文本被误解码后破坏字符串字面量（Hosted Runner 的默认代码页并不固定）。
        encoding="utf-8-sig",
    )
    result = subprocess.run(  # noqa: S603 - 仅执行固定的隔离Windows ACL配置脚本
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(setup_path),
            "-Paths",
            "|".join(str(path) for path in paths),
            "-DirectoryPaths",
            "|".join(str(path) for path in directory_paths),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "无法在隔离测试对象上应用严格Windows ACL；"
            f"exit={result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    return result.stdout.strip()


def test_deploy_workflow_exposes_only_typed_manual_inputs() -> None:
    """部署工作流只能由固定分支手工触发，并使用收窄后的输入。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    lowered = content.lower()

    assert "workflow_dispatch:" in content
    assert "inputs.request_id || github.run_id" not in content
    assert "image_digest:" in content
    assert "config_digest:" in content
    assert "config_artifact_digest:" in content
    assert "release_request_id:" in content
    assert "expected_revision:" in content
    assert "apply:" in content
    assert "run_migrations:" in content
    assert "run_migrations=true is disabled" in content
    assert "migration_policy_id = 'disabled-v1'" in content
    assert "external_probe_uri:" not in content
    assert "external_probe_authorization_env_var:" not in content
    assert "change_description:" in content
    assert "confirmation:" in content
    assert "type: boolean" in content
    assert "default: false" in content
    assert "DEPLOY IWORK WITH MIGRATIONS" in content
    assert "if ($env:GITHUB_ACTOR -cne 'GuChenkano')" in content
    assert "if ($env:GITHUB_REF -cne 'refs/heads/Keycloak')" in content
    assert "Production deploy repository is not approved." in content
    assert "environment: production-iwork" in content
    assert "contents: none" in content
    assert "packages: read" in content
    assert "actions: read" in content
    assert "self-hosted" in content
    assert "dkt-prod" in content
    assert "iwork" in content
    assert "production-deploy-iwork" in content

    for forbidden in (
        "pull_request:",
        "pull_request_target",
        "push:",
        "actions/checkout",
        "packages: write",
        "contents: write",
        "docker build",
        "docker compose build",
        "deploy.ps1",
        "dkt-secrets.env",
        "ssh ",
        "shell_command",
        "command_input",
    ):
        assert forbidden not in lowered


def test_windows_powershell_inline_script_is_ascii_only() -> None:
    """Windows PowerShell 5.1内联脚本必须为ASCII，避免无BOM临时文件解析失败。"""
    workflow = yaml.safe_load(DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8"))
    scripts = [
        step["run"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("shell") == "powershell" and "run" in step
    ]

    assert scripts
    assert all(script.isascii() for script in scripts)


def test_deploy_workflow_uses_pinned_server_script_and_ephemeral_ghcr_auth() -> None:
    """部署工作流必须调用固定服务器脚本，并清理短期GHCR认证。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert r"D:\DM\cicd-tools\iwork" in content
    assert "Invoke-IworkProductionDeployment.ps1" in content
    assert "DEPLOY_SCRIPT_SHA256:" in content
    assert "Get-FileHash" in content
    assert "DOCKER_CONFIG" in content
    assert "RUNNER_TEMP" in content
    assert "docker pull $candidateImage" in content
    assert "org.opencontainers.image.revision" in content
    assert "org.opencontainers.image.source" in content
    assert "Candidate OCI source label mismatch." in content
    assert "$env:EXPECTED_REVISION -cne $env:GITHUB_SHA" in content
    assert "actions/runs/$RunId" in content
    assert "function Assert-SpecifiedWorkflowRun" in content
    assert "-WorkflowFile 'ci.yml'" in content
    assert "-WorkflowFile 'release.yml'" in content
    assert "$run.conclusion -ne 'success'" in content
    assert "Remove-Item -LiteralPath $cleanupPath -Recurse -Force" in content
    assert "-Mode $mode" in content
    assert '$deploymentRunId = "$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"' in content
    assert "-RunId $deploymentRunId" in content
    assert "-Actor $env:GITHUB_ACTOR" in content
    assert "-ChangeDescription $env:CHANGE_DESCRIPTION" in content
    assert "GITHUB_STEP_SUMMARY" in content
    assert "iwork production deployment failed" in content
    assert "RollbackSucceeded" in content
    assert "'${{ inputs.change_description }}'" not in content

    workflow = yaml.safe_load(content)
    deploy_env = workflow["jobs"]["deploy"].get("env", {})
    assert deploy_env["CONFIG_BUNDLE_PATH"] == "${{ github.workspace }}\\iwork-production-config"
    assert "${{ runner.temp }}" not in deploy_env.values()

    script_hash = hashlib.sha256(DEPLOY_SCRIPT_PATH.read_bytes()).hexdigest()
    assert f"DEPLOY_SCRIPT_SHA256: {script_hash}" in content
    module_hash = hashlib.sha256(COORDINATION_MODULE_PATH.read_bytes()).hexdigest()
    assert f"DEPLOY_COORDINATION_MODULE_SHA256: {module_hash}" in content
    assert module_hash == EXPECTED_COORDINATION_MODULE_SHA256
    assert "DEPLOY_COORDINATION_MODULE_PATH:" in content
    assert "DEPLOY_COORDINATION_MODULE_PATH" in content
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" not in content
    assert "HttpClientHandler" in content
    assert "AllowAutoRedirect = $false" in content
    assert "Expand-VerifiedArtifactArchive" in content
    assert "[IO.File]::Move($temporaryPath, $ArchivePath)" in content
    assert "releaseManifestRoot" in content
    assert "CONFIG_DIGEST: ${{ inputs.config_digest }}" in content
    assert "CONFIG_ARTIFACT_DIGEST: ${{ inputs.config_artifact_digest }}" in content
    assert "RELEASE_REQUEST_ID: ${{ inputs.release_request_id }}" in content
    assert "$run.event -ne 'workflow_dispatch'" in content
    assert "$run.head_branch -ne 'Keycloak'" in content
    assert "actions/runs/$env:RELEASE_RUN_ID/artifacts" in content
    assert "actions/artifacts/$ArtifactId/zip" in content
    assert "Assert-ArtifactArchiveDigest" in content
    assert "$Description archive digest mismatch" in content
    assert "IWORK_CONFIG_ARTIFACT_ARCHIVE_VERIFIED=true" in content
    assert "IWORK_RELEASE_MANIFEST_ARCHIVE_VERIFIED=true" in content
    assert "$_.digest -ceq $env:CONFIG_ARTIFACT_DIGEST" in content
    assert "matchingConfigArtifacts.Count -ne 1" in content
    assert "matchingManifestArtifacts.Count -ne 1" in content
    assert "function Get-ExactRequestId" in content
    assert "(Get-ExactRequestId -Title ([string]$releaseRun.display_title)) -cne $env:RELEASE_REQUEST_ID.ToLowerInvariant()" in content
    assert "display_title).Contains($env:RELEASE_REQUEST_ID)" not in content
    assert "[string]$preflightDetails.display_title -notmatch '(?i)\\bpreflight\\b'" in content
    assert "releaseManifest.ci_run_id" in content
    assert "releaseManifest.ci_request_id" in content
    assert "workflow = '.github/workflows/release.yml'" in content
    assert "ref = 'refs/heads/Keycloak'" in content
    assert "mechanism_id = 'iwork-release-mechanism-v1'" in content
    assert "risk_envelope = 'application-only'" in content
    assert "migration_policy_id = 'disabled-v1'" in content
    assert "iwork-production-config/v1" in content
    assert "Production config commit mismatch." in content
    assert "Production config image digest mismatch." in content
    assert "Production config digest mismatch." in content
    assert "Production compose hash mismatch." in content
    assert "Production profile hash mismatch." in content
    assert "-ConfigDigest $env:CONFIG_DIGEST" in content
    assert "-ConfigBundlePath $env:CONFIG_BUNDLE_PATH" in content
    assert "-RequestId $env:REQUEST_ID" in content
    assert '"IWORK_REQUEST_ID=$env:REQUEST_ID"' in content


def test_deployment_contract_requires_external_probe_evidence() -> None:
    """部署契约必须要求宿主机外部探针或显式探针收据。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "ExternalProbeUri" in content
    assert "ExternalProbeReceiptPath" in content
    assert "iwork-external-probe-receipt/v3" in content
    assert "iwork-external-probes-v2" in content
    assert "ExternalProbeProducerSha256" in content
    assert "ExternalProbeSigningSecretSha256" in content
    assert "producer_identity" in content
    assert "switched_at" in content
    assert "nonce" in content
    assert "containers" in content
    for probe_name in (
        "https_nginx",
        "oidc_discovery",
        "sse_first_event",
        "sse_heartbeat",
        "business_read",
        "notification_chain",
    ):
        assert probe_name in content
    assert "外部探针六项收据" in content


def test_deployment_contract_pins_watchdog_sha256_and_mechanism_manifest() -> None:
    """部署前必须校验SYSTEM看门狗脚本哈希与机制清单。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "WatchdogSha256" in content
    assert "WatchdogManifestPath" in content
    assert "WatchdogManifestSha256" in content
    assert "Get-Sha256" in content
    assert "机制清单SHA-256" in content
    assert "机制清单" in content


def test_deploy_workflow_does_not_take_watchdog_integrity_from_dispatch_inputs() -> None:
    """看门狗完整性值必须来自固定Workflow准入，而非手工输入。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "inputs.watchdog_sha256" not in content
    assert "inputs.watchdog_manifest_path" not in content
    assert "WATCHDOG_SHA256: e59f057be2cd427fb7633da22d6220e1167467fa4d3a707a47fd6414edfb0c53" in content
    assert "WATCHDOG_MANIFEST_PATH: D:\\DM\\DTD_nginx\\scripts\\docker-health-watchdog.manifest.json" in content
    assert "WATCHDOG_MANIFEST_SHA256: a031d4a8f600bfeb15f15f05e4c626538a4ba7e218014c0ebef48d5f9c39cea2" in content
    assert "WATCHDOG_TASK_NAME: Docker-Health-Watchdog" in content
    assert "WATCHDOG_TASK_PATH: \\" in content
    assert "EXTERNAL_PROBE_RECEIPT_PATH: D:\\DM\\cicd-state\\iwork\\external-probe-receipt.json" in content


def test_watchdog_integrity_checks_actual_scheduled_task_identity_and_action() -> None:
    """看门狗门禁必须核验真实计划任务身份和固定脚本Action。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "Get-ScheduledTask" in content
    assert "ServiceAccount" in content
    assert "RunLevel" in content
    assert "Highest" in content
    assert "Docker看门狗计划任务Action未固定到受信脚本" in content


def test_deploy_workflow_verifies_signed_release_manifest_before_use() -> None:
    """生产端必须先验证Manifest签名，不能只信日志或可变JSON。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "IWORK_RELEASE_MANIFEST_VERIFY_CERT_B64" in content
    assert "IWORK_RELEASE_MANIFEST_SIGNING_KEY_ID" in content
    assert "release-manifest.sig" in content
    assert "VerifyData" in content
    assert "VerifyData($manifestBytes, 'SHA256', $signatureBytes)" in content
    assert "signature_algorithm" in content
    assert "signature_key_id" in content
    assert "Manifest signature verification failed" in content


def test_deploy_workflow_verifies_artifacts_before_reading_manifest_or_config() -> None:
    """干净Runner必须先下载/验收Artifact，再读取Manifest与配置内容。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    execution = content[content.index("- name: 校验候选镜像并执行预检或部署") :]

    config_download = execution.index("-Description 'Config artifact'")
    manifest_download = execution.index("-Description 'Manifest artifact'")
    manifest_verified = execution.index(
        "$releaseManifest = Get-VerifiedReleaseManifest -ManifestRoot $releaseManifestRoot"
    )
    ci_lookup = execution.index("$ciRun = Assert-SpecifiedWorkflowRun")
    config_read = execution.index(
        "$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json"
    )
    image_pull = execution.index("docker pull $candidateImage")

    assert config_download < manifest_verified
    assert manifest_download < manifest_verified
    assert manifest_verified < ci_lookup < config_read < image_pull


def test_production_coordination_module_is_bom_pinned_and_integrated() -> None:
    """统一协调模块必须字节固定，并由部署脚本接入三段式锁生命周期。"""
    module_bytes = COORDINATION_MODULE_PATH.read_bytes()
    assert module_bytes.startswith(b"\xef\xbb\xbf")
    assert hashlib.sha256(module_bytes).hexdigest() == EXPECTED_COORDINATION_MODULE_SHA256

    module_content = COORDINATION_MODULE_PATH.read_text(encoding="utf-8-sig")
    assert "New-ProductionCoordinationAuditMutex" in module_content
    assert "PRODUCTION_COORDINATION_AUDIT_MUTEX" in module_content
    assert "IdentityNotMappedException" not in module_content
    assert "[Threading.Mutex]::new($false, $PRODUCTION_COORDINATION_AUDIT_MUTEX)" not in module_content

    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")
    assert "Import-Module -Name $COORDINATION_MODULE" in content
    assert "Enter-ProductionCoordinationLock" in content
    assert "Update-ProductionCoordinationLock" in content
    assert "Exit-ProductionCoordinationLock" in content
    assert "-Repository 'GuChenkano/iwork'" in content
    assert "-Service 'iwork'" in content
    assert "iwork = $ImageDigest" in content
    assert "iwork_config = $ConfigDigest" in content
    assert "if (Test-Path -LiteralPath $DEPLOYMENT_LOCK_FILE -PathType Leaf)" not in content


def test_coordination_lock_and_audit_work_without_production_domain_identity(
    tmp_path: Path,
) -> None:
    """托管Runner没有生产域账号时，真实协调锁和审计写入仍应成功。"""
    lock_root = tmp_path / "locks"
    script_path = tmp_path / "run-coordination.ps1"
    script_path.write_text(
        """param([string]$ModulePath, [string]$LockRoot)
$ErrorActionPreference = 'Stop'
Import-Module -Name $ModulePath -Force
$lock = Enter-ProductionCoordinationLock `
    -LockRoot $LockRoot `
    -Repository 'GuChenkano/iwork' `
    -Service 'iwork' `
    -RunId '123456-1' `
    -Actor 'GuChenkano' `
    -ExpectedRevision ('2' * 40) `
    -ArtifactDigests ([ordered]@{ iwork = 'sha256:' + ('1' * 64) }) `
    -RequestId '12345678-1234-1234-1234-123456789abc' `
    -RunStateResolver { [pscustomobject]@{ Status = 'completed'; Conclusion = 'success' } }
Update-ProductionCoordinationLock -Lock $lock -Phase 'validated'
$eventPath = $lock.EventPath
Exit-ProductionCoordinationLock -Lock $lock
$events = @(Get-Content -LiteralPath $eventPath | ForEach-Object { $_ | ConvertFrom-Json })
if ($events.Count -lt 3) { throw '协调审计事件数量不足。' }
if ($events.event -notcontains 'acquire_attempt') { throw '缺少acquire_attempt审计事件。' }
if ($events.event -notcontains 'phase_updated') { throw '缺少phase_updated审计事件。' }
if ($events.event -notcontains 'released') { throw '缺少released审计事件。' }
if (Test-Path -LiteralPath (Join-Path $LockRoot 'production-deploy.lock')) {
    throw '协调锁文件未清理。'
}
[pscustomobject]@{ EventCount = $events.Count; Result = 'ok' } | ConvertTo-Json -Compress
""",
        encoding="utf-8-sig",
    )

    result = subprocess.run(  # noqa: S603 - 仅执行固定的隔离PowerShell测试脚本
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ModulePath",
            str(COORDINATION_MODULE_PATH),
            "-LockRoot",
            str(lock_root),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["Result"] == "ok"
    module_content = COORDINATION_MODULE_PATH.read_text(encoding="utf-8-sig")
    assert r"DONGMING\shuju" not in module_content
    assert "PRODUCTION_COORDINATION_RUNNER_IDENTITY" not in module_content
    assert "IdentityNotMappedException" not in module_content


def test_policy_installer_installs_and_pins_script_and_coordination_module() -> None:
    """安装器必须原子暂存部署脚本和协调模块，并在Hook固定双SHA。"""
    content = POLICY_INSTALLER_PATH.read_text(encoding="utf-8-sig")
    lowered = content.lower()

    assert "SourceCoordinationModule" in content
    assert "TARGET_COORDINATION_MODULE" in content
    assert "MODULE_SHA256" in content
    assert "coordinationModuleTemporaryPath" in content
    assert "COORDINATION_MODULE_PATH" in content
    assert "COORDINATION_MODULE_SHA256" in content
    assert "Get-FileHash -LiteralPath $coordinationModulePath" in content
    assert "Move-Item -LiteralPath $coordinationModuleTemporaryPath" in content
    assert "module" in lowered


def test_deployment_lock_schema_contract_is_explicit() -> None:
    """部署接入必须传递统一锁Schema所需的Run、版本和制品字段。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "production-deploy-lock-v1" in COORDINATION_MODULE_PATH.read_text(
        encoding="utf-8-sig"
    )
    assert "-RunId $RunId" in content
    assert "-Actor $Actor" in content
    assert "-ExpectedRevision $ExpectedRevision" in content
    assert "-RequestId $RequestId" in content
    assert "-Phase 'candidate_validation'" in content
    assert "-Phase 'preflight_complete'" in content
    assert "-Phase 'production_validation'" in content
    assert "-Phase 'automatic_rollback'" in content
    assert "-Phase 'completed'" in content


def test_deploy_workflow_requires_explicit_one_time_rollback_drill() -> None:
    """受控回滚演练必须显式确认、禁止迁移，并传给固定部署脚本。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "rollback_drill:" in content
    assert "ROLLBACK_DRILL: ${{ inputs.rollback_drill }}" in content
    assert "ROLLBACK DRILL IWORK ONCE" in content
    assert "$env:ROLLBACK_DRILL -eq 'true' -and $env:APPLY -ne 'true'" in content
    assert (
        "$env:ROLLBACK_DRILL -eq 'true' -and $env:RUN_MIGRATIONS -eq 'true'"
        in content
    )
    assert "-RollbackDrill $env:ROLLBACK_DRILL" in content


def test_policy_installer_pins_workflow_commit_and_server_script() -> None:
    """生产策略安装器必须固定Workflow提交与服务器部署脚本哈希。"""
    content = POLICY_INSTALLER_PATH.read_text(encoding="utf-8-sig")
    lowered = content.lower()

    assert "ApprovedHeadSha" in content
    assert "GITHUB_SHA" in content
    assert "iwork production runner smoke" in content
    assert "iwork controlled production deployment" in content
    assert "runner-smoke.yml@refs/heads/Keycloak" in content
    assert "deploy-iwork.yml@refs/heads/Keycloak" in content
    assert r"D:\DM\cicd-tools\iwork" in content
    assert "Invoke-IworkProductionDeployment.ps1" in content
    assert "Get-FileHash" in content
    assert "Runner.Worker.exe" in content
    assert "Move-Item" in content
    assert "StateRoot" in content
    assert "LockRoot" in content
    assert "Assert-CrossRepositoryRunReadiness" in content
    assert "GuChenkano/DTD_nginx" in content
    assert '"repos/$CROSS_REPOSITORY/actions/runs?per_page=1"' in content
    assert "$env:GH_TOKEN = $null" in content
    assert "$env:GITHUB_TOKEN = $null" in content
    assert "$previousGhToken = $env:GH_TOKEN" in content
    assert "$previousGitHubToken = $env:GITHUB_TOKEN" in content
    assert "$env:GH_TOKEN = $previousGhToken" in content
    assert "$env:GITHUB_TOKEN = $previousGitHubToken" in content

    for forbidden in (
        "dkt-secrets.env",
        "docker compose",
        "docker build",
        "git clean",
        "git reset",
        "remove-item -literalpath 'd:\\dm\\iwork'",
    ):
        assert forbidden not in lowered


def test_pinned_production_scripts_have_stable_lf_bytes() -> None:
    """固定哈希的生产脚本必须强制LF，避免Windows检出后哈希漂移。"""
    content = GIT_ATTRIBUTES_PATH.read_text(encoding="utf-8")

    assert "scripts/Install-IworkProductionDeployment.ps1 text eol=lf" in content
    assert "scripts/Invoke-IworkProductionDeployment.ps1 text eol=lf" in content


def test_runner_resume_preserves_installed_deployment_policy() -> None:
    """恢复既有Runner任务时，不得覆盖阶段4固定提交准入策略。"""
    content = RUNNER_INSTALLER_PATH.read_text(encoding="utf-8")

    assert "$ResumeConfiguredRunner -and" in content
    assert "Test-Path -LiteralPath $hookPath -PathType Leaf" in content
    assert "保留现有Runner准入钩子" in content


def test_container_startup_can_skip_migrations_explicitly() -> None:
    """受控部署关闭迁移时，Web容器不得隐式执行数据库迁移。"""
    content = START_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "IWORK_RUN_MIGRATIONS" in content
    assert '"${IWORK_RUN_MIGRATIONS:-}" = "true"' in content
    assert '"${IWORK_RUN_MIGRATIONS:-}" = "false"' in content
    assert "IWORK_RUN_MIGRATIONS:-true" not in content
    assert "必须显式设置" in content
    assert "根据部署策略跳过数据库迁移" in content


def test_compose_defaults_migrations_to_explicit_false() -> None:
    """普通Compose启动缺少迁移变量时必须显式落到false，而非隐式迁移。"""
    content = COMPOSE_PATH.read_text(encoding="utf-8")

    assert content.count("IWORK_RUN_MIGRATIONS: ${IWORK_RUN_MIGRATIONS:-false}") == 2


def test_compose_env_file_is_overridable_by_verified_release_profile() -> None:
    """生产脚本必须能让Compose服务直接读取配置包内环境文件。"""
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert compose.count("IWORK_RELEASE_PROFILE_FILE") == 2
    assert "./env/${DKT_ENVIRONMENT:-production}.env" in compose
    assert "$env:IWORK_RELEASE_PROFILE_FILE = $ProfileFile" in script
    assert "Invoke-DockerCommandWithProfile" in script


def test_deployment_requires_explicit_owner_acl_trust_manifest() -> None:
    """生产脚本必须声明并校验显式Owner/ACL信任清单。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "$TrustManifestPath" in content
    assert "$TrustManifestSha256" in content
    assert "iwork-owner-acl/v1" in content


def test_isolated_acl_fixture_reports_owner_setting_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ACL设置或Owner回读失败时，夹具必须显式失败而不是放过测试。"""
    target = tmp_path / "probe.ps1"
    target.write_text("# isolated\n", encoding="utf-8")

    def failed_acl_process(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="icacls owner failure"
        )

    monkeypatch.setattr(subprocess, "run", failed_acl_process)
    with pytest.raises(RuntimeError, match="无法在隔离测试对象上应用严格Windows ACL"):
        _configure_isolated_acl(tmp_path, [target], directory_paths=set())
    setup_script = (tmp_path / "configure-test-acl.ps1").read_text(encoding="utf-8")
    assert "icacls.exe" in setup_script
    assert "/setowner" in setup_script
    assert "ACL Owner校验失败" in setup_script


def _run_deployment_script(
    tmp_path: Path,
    *,
    mode: str,
    rollback_drill: bool = False,
    existing_rollback_drill_marker: bool = False,
    fail_validation: bool = False,
    fail_rollback: bool = False,
    run_migrations: bool = False,
    watchdog_uses_shared_mutex: bool = True,
    emit_compose_progress: bool = False,
    transient_alert_unhealthy_checks: int = 0,
    health_timeout_seconds: int = 2,
    fail_maintenance_cleanup: bool = False,
    existing_maintenance_marker: dict[str, object] | None = None,
    config_source_commit: str = CANDIDATE_REVISION,
    config_image_digest: str = CANDIDATE_DIGEST,
    tamper_config_after_manifest: bool = False,
    add_unknown_config_file: bool = False,
    existing_active_config: bool = False,
    tamper_active_release_field: str | None = None,
    recovery_mutex_name: str | None = None,
    expected_identity: str | None = None,
    preconsumed_request: bool = False,
    external_probe_receipt: bool = True,
    external_probe_mutation: str | None = None,
    external_probe_precreated: bool = False,
    external_probe_producer: bool = True,
    watchdog_sha256_override: str | None = None,
    watchdog_manifest_sha256_override: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    """在隔离目录和伪Docker适配器下运行部署脚本。

    Args:
        tmp_path (Path): pytest隔离临时目录。
        mode (str): 部署脚本模式。
        rollback_drill (bool): 是否执行一次性受控回滚演练。
        existing_rollback_drill_marker (bool): 是否预置既有演练记录。
        fail_validation (bool): 是否让部署后Django检查失败。
        fail_rollback (bool): 是否让回滚Compose切换失败。
        run_migrations (bool): 是否启用迁移前备份与容器迁移。
        watchdog_uses_shared_mutex (bool): 看门狗是否声明共享恢复锁。
        emit_compose_progress (bool): 是否模拟Compose在标准错误输出成功进度。
        transient_alert_unhealthy_checks (int): 告警Worker暂时不健康的检查次数。
        health_timeout_seconds (int): 等待容器恢复健康的超时秒数。
        fail_maintenance_cleanup (bool): 是否模拟维护标记在清理前变为不可删除目录。
        existing_maintenance_marker: 运行前写入的部署维护标记。
        config_source_commit (str): 配置清单绑定的来源Commit。
        config_image_digest (str): 配置清单绑定的镜像Digest。
        tamper_config_after_manifest (bool): 是否在生成清单后篡改配置文件。
        add_unknown_config_file (bool): 是否在配置包中加入未知文件。
        existing_active_config (bool): 是否预置一套与候选不同的活动配置。
        tamper_active_release_field (str | None): 可选的活动指针字段篡改项。
        recovery_mutex_name (str | None): 可选的恢复Mutex名称，用于隔离竞争测试。
        expected_identity (str | None): 可选的生产身份预期值，用于身份门禁回归测试。
        preconsumed_request (bool): 是否预置同一request_id的服务器消费收据。
        external_probe_receipt (bool): 是否提供绑定候选发布的外部探针收据。
        external_probe_mutation (str | None): 可选的外部探针收据破坏场景。
        external_probe_precreated (bool): 是否在候选切换前预生成伪造收据。
        external_probe_producer (bool): 是否提供受信本地主机探针生产者。
        watchdog_sha256_override (str | None): 可选的错误看门狗哈希，用于门禁测试。
        watchdog_manifest_sha256_override (str | None): 可选的错误看门狗清单哈希，用于门禁测试。

    Returns:
        tuple[subprocess.CompletedProcess[str], dict[str, object]]:
            进程结果和隔离路径字典。
    """
    iwork_root = tmp_path / "iwork"
    state_root = tmp_path / "state"
    lock_root = tmp_path / "locks"
    maintenance_file = tmp_path / "maintenance" / "iwork-deployment.json"
    if existing_maintenance_marker is not None:
        maintenance_file.parent.mkdir(parents=True, exist_ok=True)
        maintenance_file.write_text(
            json.dumps(existing_maintenance_marker),
            encoding="utf-8",
        )
    profile = iwork_root / "env" / "production.env"
    secrets = tmp_path / "dkt-secrets.env"
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "fake-docker.ps1"
    fake_docker_wrapper = tmp_path / "fake-docker.cmd"
    watchdog_script = tmp_path / "docker-health-watchdog.ps1"
    watchdog_manifest = tmp_path / "docker-health-watchdog-manifest.json"
    external_probe_receipt_path = (
        tmp_path / "probe-receipts" / "external-probe-receipt.json"
    )
    external_probe_receipt_parent = external_probe_receipt_path.parent
    external_probe_producer_path = tmp_path / "external-probe-producer.ps1"
    external_probe_secret_path = tmp_path / "external-probe-signing.key"
    trust_manifest_path = tmp_path / "owner-acl-trust-manifest.json"
    config_bundle = tmp_path / "config-bundle"

    profile.parent.mkdir(parents=True)
    state_root.mkdir()
    lock_root.mkdir()
    if preconsumed_request:
        consumed_root = state_root / "request-consumption"
        consumed_root.mkdir()
        (consumed_root / f"{REQUEST_ID}.json").write_text(
            json.dumps(
                {
                    "schema": "iwork-request-consumption/v1",
                    "status": "consumed",
                    "request_id": REQUEST_ID,
                }
            ),
            encoding="utf-8",
        )
    if existing_rollback_drill_marker:
        (state_root / "rollback-drill-v1.json").write_text(
            '{"Status":"failed","RunId":"previous-attempt"}\n',
            encoding="utf-8",
        )
    compose_content = b"services: {}\n"
    profile_content = b"DKT_ENVIRONMENT=production\n"
    (iwork_root / "docker-compose.yml").write_bytes(compose_content)
    profile.write_bytes(profile_content)
    config_digest = _write_config_bundle(
        config_bundle,
        compose_content=compose_content,
        profile_content=profile_content,
        source_commit=config_source_commit,
        image_digest=config_image_digest,
    )
    if tamper_config_after_manifest:
        config_bundle.joinpath("env", "production.env").write_text(
            "DKT_ENVIRONMENT=tampered\n",
            encoding="utf-8",
        )
    if add_unknown_config_file:
        config_bundle.joinpath("unexpected.ps1").write_text(
            "throw 'unexpected'\n",
            encoding="utf-8",
        )
    previous_config_digest: str | None = None
    previous_config_path: Path | None = None
    if existing_active_config:
        temporary_previous = tmp_path / "previous-config"
        previous_image_digest = PREVIOUS_DIGEST
        previous_revision = PREVIOUS_REVISION
        previous_config_digest = _write_config_bundle(
            temporary_previous,
            compose_content=b"services:\n  legacy: {}\n",
            profile_content=b"DKT_ENVIRONMENT=production\nFEATURE_LEVEL=legacy\n",
            source_commit=previous_revision,
            image_digest=previous_image_digest,
        )
        previous_config_path = (
            state_root
            / "release-config"
            / previous_config_digest.removeprefix("sha256:")
        )
        previous_config_path.parent.mkdir(parents=True)
        temporary_previous.rename(previous_config_path)
        active_release = {
            "schema": "iwork-active-release/v1",
            "source_commit": previous_revision,
            "image_digest": previous_image_digest,
            "config_digest": previous_config_digest,
            "config_artifact_digest": CONFIG_ARTIFACT_DIGEST,
            "compose_sha256": hashlib.sha256(
                b"services:\n  legacy: {}\n"
            ).hexdigest(),
            "production_env_sha256": hashlib.sha256(
                b"DKT_ENVIRONMENT=production\nFEATURE_LEVEL=legacy\n"
            ).hexdigest(),
            "deployment_run_id": "previous-run",
            "request_id": PREFLIGHT_REQUEST_ID,
            "activated_at": "2026-08-27T00:00:00+00:00",
        }
        if tamper_active_release_field == "request_id":
            active_release["request_id"] = "not-a-guid"
        elif tamper_active_release_field == "compose_sha256":
            active_release["compose_sha256"] = "0" * 64
        state_root.joinpath("active-release.json").write_text(
            json.dumps(active_release),
            encoding="utf-8",
        )
    secrets.write_text("TEST_ONLY=1\n", encoding="utf-8")
    watchdog_script.write_text(
        (
            '$RECOVERY_MUTEX = "Global\\DKT-Docker-Recovery"\n'
            if watchdog_uses_shared_mutex
            else '$RECOVERY_MUTEX = "Global\\Unexpected-Recovery"\n'
        ),
        encoding="utf-8",
    )
    watchdog_sha256 = hashlib.sha256(watchdog_script.read_bytes()).hexdigest()
    watchdog_manifest.write_text(
        json.dumps(
            {
                "schema": "dkt-docker-health-watchdog/v1",
                "application": "DTD_nginx",
                "script": watchdog_script.name,
                "script_sha256": watchdog_sha256,
                "recovery_mutex": "Global\\DKT-Docker-Recovery",
                "execution_identity": "NT AUTHORITY\\SYSTEM",
            }
        ),
        encoding="utf-8",
    )
    watchdog_manifest_sha256 = hashlib.sha256(watchdog_manifest.read_bytes()).hexdigest()
    external_probe_secret_path.write_bytes(b"isolated-test-probe-signing-secret-32")
    probe_template = {
        "schema": "iwork-external-probe-receipt/v3",
        "application": "iwork",
        "status": "succeeded",
        "request_id": REQUEST_ID,
        "deployment_run_id": DEPLOYMENT_RUN_ID,
        "source_commit": CANDIDATE_REVISION,
        "image_digest": CANDIDATE_DIGEST,
        "config_digest": config_digest,
        "config_artifact_digest": CONFIG_ARTIFACT_DIGEST,
        "probe_contract_id": "iwork-external-probes-v2",
        "nonce": "__NONCE__",
        "switched_at": "__SWITCHED_AT__",
        "checked_at": "__CHECKED_AT__",
        "producer_identity": "__IDENTITY__",
        "producer_sha256": "__PRODUCER_SHA256__",
        "containers": "__CONTAINERS__",
        "probes": [
                {
                    "name": "https_nginx",
                    "status": "succeeded",
                    "uri": "https://iwork.example.test/",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 20,
                    "evidence": {"reachable": True, "tls_valid": True},
                },
                {
                    "name": "oidc_discovery",
                    "status": "succeeded",
                    "uri": "https://sso.example.test/realms/ditu/.well-known/openid-configuration",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 25,
                    "evidence": {
                        "issuer": "https://sso.example.test/realms/ditu",
                        "jwks_uri": "https://sso.example.test/realms/ditu/protocol/openid-connect/certs",
                    },
                },
                {
                    "name": "sse_first_event",
                    "status": "succeeded",
                    "uri": "https://iwork.example.test/iwork/events/",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 30,
                    "evidence": {"event_type": "snapshot", "received": True},
                },
                {
                    "name": "sse_heartbeat",
                    "status": "succeeded",
                    "uri": "https://iwork.example.test/iwork/events/",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 1500,
                    "evidence": {"heartbeat_received": True, "interval_ms": 1000},
                },
                {
                    "name": "business_read",
                    "status": "succeeded",
                    "uri": "https://iwork.example.test/iwork/api/history/dates/",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 40,
                    "evidence": {"result_nonempty": True},
                },
                {
                    "name": "notification_chain",
                    "status": "succeeded",
                    "uri": "https://iwork.example.test/iwork/api/account/notifications/",
                    "http_status": 200,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": 50,
                    "evidence": {"correlation_id": REQUEST_ID, "delivered": True},
                },
        ],
    }
    external_probe_producer_path.write_text(
        """param(
    [string]$ChallengePath,
    [string]$ReceiptPath,
    [string]$SignaturePath,
    [string]$SigningSecretFile
)
$ErrorActionPreference = 'Stop'
$Mutation = [string]$env:FAKE_PROBE_MUTATION
$challenge = Get-Content -LiteralPath $ChallengePath -Raw | ConvertFrom-Json
$template = Get-Content -LiteralPath $env:FAKE_PROBE_TEMPLATE -Raw | ConvertFrom-Json
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$template.nonce = $challenge.nonce
$template.switched_at = $challenge.switched_at
$template.checked_at = [DateTimeOffset]::UtcNow.ToString('o')
$template.producer_identity = $identity
$template.producer_sha256 = $challenge.producer_sha256
$template.containers = @($challenge.containers)
foreach ($probe in @($template.probes)) { $probe.checked_at = $template.checked_at }
if ($Mutation -eq 'missing') { $template.probes = @($template.probes)[0..4] }
elseif ($Mutation -eq 'duplicate') { $template.probes = @($template.probes) + @($template.probes)[0] }
elseif ($Mutation -eq 'unknown') { $template.probes[0].name = 'unknown_probe' }
elseif ($Mutation -eq 'failed') { $template.probes[0].evidence.reachable = $false }
elseif ($Mutation -eq 'expired') { $template.checked_at = '2020-01-01T00:00:00+00:00' }
elseif ($Mutation -eq 'pre_switch') { $template.checked_at = ([DateTimeOffset]$challenge.switched_at).AddSeconds(-1).ToString('o') }
elseif ($Mutation -eq 'nonce') { $template.nonce = '00000000000000000000000000000000' }
elseif ($Mutation -eq 'identity') { $template.producer_identity = 'UNTRUSTED\\probe' }
elseif ($Mutation -eq 'container') { $template.containers[0].ContainerId = 'stale-container-id' }
$json = ($template | ConvertTo-Json -Depth 12 -Compress) + "`n"
$bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
[IO.File]::WriteAllBytes($ReceiptPath, $bytes)
$hmac = [Security.Cryptography.HMACSHA256]::new([IO.File]::ReadAllBytes($SigningSecretFile))
try { $signature = $hmac.ComputeHash($bytes) } finally { $hmac.Dispose() }
[IO.File]::WriteAllText($SignaturePath, ([Convert]::ToBase64String($signature) + "`n"), [Text.UTF8Encoding]::new($false))
function Set-TestProbeOutputAcl {
    param([string]$OutputPath)
    $outputAcl = [IO.File]::GetAccessControl($OutputPath)
    $null = $outputAcl.SetAccessRuleProtection($true, $false)
    $setOwnerError = $null
    try { $outputAcl.SetOwner($currentSid) }
    catch { $setOwnerError = $_ }
    foreach ($existingRule in @($outputAcl.Access)) {
        $null = $outputAcl.RemoveAccessRule($existingRule)
    }
    $none = [Security.AccessControl.InheritanceFlags]::None
    $noPropagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $null = $outputAcl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid, [Security.AccessControl.FileSystemRights]::Modify,
        $none, $noPropagation, $allow
    ))
    $null = $outputAcl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
        [Security.AccessControl.FileSystemRights]::FullControl,
        $none, $noPropagation, $allow
    ))
    [IO.File]::SetAccessControl($OutputPath, $outputAcl)
    $owner = (Get-Item -LiteralPath $OutputPath -Force).
        GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($null -ne $setOwnerError -or $owner -cne $currentSid.Value) {
        $null = & "$env:SystemRoot\\System32\\icacls.exe" $OutputPath /setowner `
            ("*" + $currentSid.Value) /C 2>&1
        if ($LASTEXITCODE -ne 0) {
            $detail = if ($null -ne $setOwnerError) {
                $setOwnerError.Exception.Message
            }
            else { 'Owner回读不匹配' }
            throw "icacls设置探针输出Owner失败：$OutputPath；$detail"
        }
        $owner = (Get-Item -LiteralPath $OutputPath -Force).
            GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value
    }
    if ($owner -cne $currentSid.Value) {
        throw "探针输出Owner校验失败：$owner"
    }
}
foreach ($outputPath in @($ReceiptPath, $SignaturePath)) {
    Set-TestProbeOutputAcl -OutputPath $outputPath
}
if ($Mutation -eq 'signature') { [IO.File]::WriteAllText($SignaturePath, ('AAAA' + "`n"), [Text.UTF8Encoding]::new($false)) }
""",
        # 生产者由Windows PowerShell 5.1执行，BOM确保新增中文错误信息不会被系统代码页
        # 误解码并吞掉相邻的引号，避免把真正的Owner失败误报成脚本解析错误。
        encoding="utf-8-sig",
    )
    external_probe_receipt_parent.mkdir(parents=True, exist_ok=True)
    owner_sid = _configure_isolated_acl(
        tmp_path,
        [
            external_probe_producer_path,
            external_probe_secret_path,
            external_probe_receipt_parent,
        ],
        directory_paths={external_probe_receipt_parent},
    )
    identity_sid_result = subprocess.run(  # noqa: S603 - 固定调用Windows系统身份查询
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-Command",
            "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        ],
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    identity_sid = identity_sid_result.stdout.strip()
    trust_objects = [
        {
            "id": "probe-producer",
            "kind": "file",
            "path": str(external_probe_producer_path),
            "content_sha256": hashlib.sha256(
                external_probe_producer_path.read_bytes()
            ).hexdigest(),
            "owner_sids": [owner_sid],
            "allowed_read_sids": [identity_sid, "S-1-5-18"],
            "allowed_write_sids": ["S-1-5-18"],
            "inheritance_protected": True,
            "reparse_allowed": False,
        },
        {
            "id": "probe-signing-secret",
            "kind": "file",
            "path": str(external_probe_secret_path),
            "content_sha256": hashlib.sha256(
                external_probe_secret_path.read_bytes()
            ).hexdigest(),
            "owner_sids": [owner_sid],
            "allowed_read_sids": [identity_sid, "S-1-5-18"],
            "allowed_write_sids": ["S-1-5-18"],
            "inheritance_protected": True,
            "reparse_allowed": False,
        },
        {
            "id": "probe-receipt-directory",
            "kind": "directory",
            "path": str(external_probe_receipt_parent),
            "content_sha256": "",
            "owner_sids": [owner_sid],
            "allowed_read_sids": [identity_sid, "S-1-5-18"],
            "allowed_write_sids": [identity_sid, "S-1-5-18"],
            "inheritance_protected": True,
            "reparse_allowed": False,
        },
        {
            "id": "probe-receipt",
            "kind": "file",
            "path": str(external_probe_receipt_path),
            "content_sha256": "",
            "owner_sids": [owner_sid],
            "allowed_read_sids": [identity_sid, "S-1-5-18"],
            "allowed_write_sids": [identity_sid, "S-1-5-18"],
            "inheritance_protected": True,
            "reparse_allowed": False,
        },
        {
            "id": "probe-signature",
            "kind": "file",
            "path": str(external_probe_receipt_path) + ".sig",
            "content_sha256": "",
            "owner_sids": [owner_sid],
            "allowed_read_sids": [identity_sid, "S-1-5-18"],
            "allowed_write_sids": [identity_sid, "S-1-5-18"],
            "inheritance_protected": True,
            "reparse_allowed": False,
        },
    ]
    trust_manifest = {
        "schema": "iwork-owner-acl/v1",
        "policy_id": "iwork-production-trust-v1",
        "environment": "production",
        "deployment_identity_sid": identity_sid,
        "probe_producer_identity_sid": identity_sid,
        "objects": trust_objects,
        "receipt_schema": "iwork-external-probe-receipt/v3",
        "probe_contract_id": "iwork-external-probes-v2",
    }
    trust_manifest_path.write_text(
        json.dumps(trust_manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    # 清单是在前面的探针对象之后才创建的，必须同样应用隔离的严格Owner/DACL。
    # Hosted Runner 的临时父目录可能把新文件Owner设为Administrators；如果不在这里
    # 显式修正，部署脚本会在第一个Owner/ACL对象校验处提前失败，掩盖真正的测试断言。
    manifest_owner_sid = _configure_isolated_acl(
        tmp_path,
        [trust_manifest_path],
        directory_paths=set(),
    )
    if manifest_owner_sid != identity_sid:
        raise RuntimeError("Owner/ACL测试清单Owner与当前测试SID不一致。")
    trust_manifest_sha256 = hashlib.sha256(
        trust_manifest_path.read_bytes()
    ).hexdigest()
    probe_template_path = tmp_path / "external-probe-template.json"
    probe_template_path.write_text(json.dumps(probe_template), encoding="utf-8")
    producer_sha256 = hashlib.sha256(external_probe_producer_path.read_bytes()).hexdigest()
    secret_sha256 = hashlib.sha256(external_probe_secret_path.read_bytes()).hexdigest()
    if external_probe_precreated:
        probe_receipt = dict(probe_template)
        probe_receipt["nonce"] = "0" * 32
        probe_receipt["switched_at"] = datetime.now(timezone.utc).isoformat()
        probe_receipt["checked_at"] = datetime.now(timezone.utc).isoformat()
        probe_receipt["producer_identity"] = "forged"
        probe_receipt["producer_sha256"] = producer_sha256
        probe_receipt["containers"] = []
        external_probe_receipt_path.write_text(
            json.dumps(probe_receipt),
            encoding="utf-8",
        )
    fake_docker.write_text(
        """param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$line = $CommandArgs -join ' '
Add-Content -LiteralPath $env:FAKE_DOCKER_LOG -Value "release-profile=$env:IWORK_RELEASE_PROFILE_FILE" -Encoding UTF8
Add-Content -LiteralPath $env:FAKE_DOCKER_LOG -Value $line -Encoding UTF8
if ($line -like 'info*') { '29.4.3'; return }
if ($line -like 'image inspect*') {
    $revision = if ($line -like "*$env:FAKE_PREVIOUS_DIGEST*") {
        $env:FAKE_PREVIOUS_REVISION
    }
    else {
        $env:FAKE_REVISION
    }
    '{\"org.opencontainers.image.revision\":\"' + $revision + '\"}'
    return
}
if ($line -like 'inspect DKT_iwork*--format {{.Image}}*') {
    if ($line -like 'inspect DKT_iwork_alert_worker*') { 'sha256:' + ('b' * 64) }
    else { 'sha256:' + ('a' * 64) }
    return
}
if ($line -like 'inspect DKT_iwork*--format {{.Id}}*') {
    if ($line -like 'inspect DKT_iwork_alert_worker*') { 'alert-container-id' }
    else { 'web-container-id' }
    return
}
if ($line -like 'inspect DKT_iwork*--format {{.RestartCount}}*') { '0'; return }
if ($line -like 'inspect DKT_iwork*--format {{.Config.Image}}*') {
    if ($line -like 'inspect DKT_iwork_alert_worker*') {
        Get-Content -LiteralPath $env:FAKE_ALERT_IMAGE_STATE -Raw
    }
    else {
        Get-Content -LiteralPath $env:FAKE_WEB_IMAGE_STATE -Raw
    }
    return
}
if ($line -like 'inspect DKT_iwork*--format {{json .State}}*') {
    if (
        $line -like 'inspect DKT_iwork_alert_worker*' -and
        [int]$env:FAKE_TRANSIENT_ALERT_UNHEALTHY_CHECKS -gt 0
    ) {
        $checkCount = [int](
            Get-Content -LiteralPath $env:FAKE_HEALTH_CHECK_COUNTER -Raw
        )
        if ($checkCount -lt [int]$env:FAKE_TRANSIENT_ALERT_UNHEALTHY_CHECKS) {
            Set-Content `
                -LiteralPath $env:FAKE_HEALTH_CHECK_COUNTER `
                -Value ($checkCount + 1) `
                -NoNewline
            '{\"Running\":true,\"Status\":\"running\",\"Health\":{\"Status\":\"unhealthy\"}}'
            return
        }
    }
    '{\"Running\":true,\"Status\":\"running\",\"Health\":{\"Status\":\"healthy\"}}'
    return
}
if ($line -like 'compose*config --quiet*') { return }
if ($line -like 'tag*') { return }
if ($line -like 'exec DKT_mysql sh -c*mysqldump*') { return }
if ($line -like 'cp DKT_mysql:/tmp/iwork-*') {
    Set-Content -LiteralPath $CommandArgs[-1] -Value 'isolated-test-backup' -Encoding UTF8
    return
}
if ($line -like 'exec DKT_mysql rm -f*') { return }
if ($line -like 'compose*up *--no-build --no-deps iwork alert-worker*') {
    $overrideIndexes = @(0..($CommandArgs.Count - 1) | Where-Object {
        $CommandArgs[$_] -eq '-f'
    })
    $overridePath = $CommandArgs[$overrideIndexes[-1] + 1]
    $images = @(Get-Content -LiteralPath $overridePath | Where-Object {
        $_ -match '^\\s+image:'
    } | ForEach-Object {
        ($_ -split ': ', 2)[1].Trim('"')
    })
    if (
        $env:FAKE_FAIL_ROLLBACK -eq '1' -and
        $images[0] -like "*$env:FAKE_PREVIOUS_DIGEST*"
    ) {
        throw 'Injected rollback compose failure'
    }
    if (
        $env:FAKE_FAIL_MAINTENANCE_CLEANUP -eq '1' -and
        $images[0] -like 'ghcr.io/guchenkano/iwork@*'
    ) {
        Remove-Item -LiteralPath $env:FAKE_MAINTENANCE_FILE -Force
        New-Item -ItemType Directory -Path $env:FAKE_MAINTENANCE_FILE | Out-Null
        Set-Content `
            -LiteralPath (Join-Path $env:FAKE_MAINTENANCE_FILE 'hold.txt') `
            -Value 'injected cleanup failure'
    }
    Set-Content -LiteralPath $env:FAKE_WEB_IMAGE_STATE -Value $images[0] -NoNewline
    Set-Content -LiteralPath $env:FAKE_ALERT_IMAGE_STATE -Value $images[1] -NoNewline
    return
}
if ($line -like 'exec DKT_iwork python manage.py check*') {
    $currentWebImage = Get-Content -LiteralPath $env:FAKE_WEB_IMAGE_STATE -Raw
    if (
        $env:FAKE_FAIL_VALIDATION -eq '1' -and
        $currentWebImage -eq $env:FAKE_CANDIDATE_IMAGE
    ) {
        throw 'Injected Django validation failure'
    }
    'System check identified no issues (0 silenced).'
    return
}
if ($line -like 'exec DKT_iwork python -c*') { return }
if ($line -like 'exec DKT_iwork_alert_worker celery*') { 'pong'; return }
throw "Unexpected fake docker call: $line"
""",
        encoding="utf-8",
    )
    fake_docker_wrapper.write_text(
        """@echo off
if \"%~1\"==\"exec\" if \"%~2\"==\"DKT_iwork\" if \"%~3\"==\"python\" exit /b 0
if \"%~1\"==\"exec\" if \"%~2\"==\"DKT_iwork_alert_worker\" if \"%~3\"==\"celery\" (
  echo pong
  exit /b 0
)
\"%SYSTEMROOT%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" ^
  -NoProfile -ExecutionPolicy Bypass -File \"%FAKE_DOCKER_SCRIPT%\" %*
set \"fakeDockerExitCode=%ERRORLEVEL%\"
if \"%FAKE_COMPOSE_PROGRESS%\"==\"1\" (
  echo %* | findstr /C:\"up --no-build --no-deps iwork alert-worker\" >nul
  if not errorlevel 1 1>&2 echo  Container DKT_iwork Recreate
)
exit /b %fakeDockerExitCode%
""",
        encoding="ascii",
    )

    env = os.environ.copy()
    env["FAKE_DOCKER_LOG"] = str(docker_log)
    env["FAKE_REVISION"] = CANDIDATE_REVISION
    env["FAKE_PREVIOUS_DIGEST"] = PREVIOUS_DIGEST
    env["FAKE_PREVIOUS_REVISION"] = PREVIOUS_REVISION
    env["FAKE_CANDIDATE_IMAGE"] = f"ghcr.io/guchenkano/iwork@{CANDIDATE_DIGEST}"
    env["FAKE_FAIL_VALIDATION"] = "1" if fail_validation else "0"
    env["FAKE_FAIL_ROLLBACK"] = "1" if fail_rollback else "0"
    env["FAKE_COMPOSE_PROGRESS"] = "1" if emit_compose_progress else "0"
    env["FAKE_TRANSIENT_ALERT_UNHEALTHY_CHECKS"] = str(
        transient_alert_unhealthy_checks
    )
    env["FAKE_FAIL_MAINTENANCE_CLEANUP"] = (
        "1" if fail_maintenance_cleanup else "0"
    )
    env["FAKE_MAINTENANCE_FILE"] = str(maintenance_file)
    env["FAKE_PROBE_TEMPLATE"] = str(probe_template_path)
    env["FAKE_PROBE_MUTATION"] = external_probe_mutation or "none"
    env["FAKE_DOCKER_SCRIPT"] = str(fake_docker)
    web_image_state = tmp_path / "web-image-state.txt"
    alert_image_state = tmp_path / "alert-image-state.txt"
    previous_image = f"ghcr.io/guchenkano/iwork@{PREVIOUS_DIGEST}"
    web_image_state.write_text(previous_image, encoding="utf-8")
    alert_image_state.write_text(previous_image, encoding="utf-8")
    env["FAKE_WEB_IMAGE_STATE"] = str(web_image_state)
    env["FAKE_ALERT_IMAGE_STATE"] = str(alert_image_state)
    health_check_counter = tmp_path / "health-check-counter.txt"
    health_check_counter.write_text("0", encoding="ascii")
    env["FAKE_HEALTH_CHECK_COUNTER"] = str(health_check_counter)

    if mode == "Deploy":
        preflight_request_claim_path = (
            state_root
            / "request-consumption"
            / f"{PREFLIGHT_REQUEST_ID}.json"
        )
        preflight_request_claim_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_request_claim_path.write_text(
            json.dumps(
                {
                    "schema": "iwork-request-consumption/v1",
                    "status": "consumed",
                    "request_id": PREFLIGHT_REQUEST_ID,
                    "mode": "Preflight",
                    "run_id": PREFLIGHT_RUN_ID,
                    "expected_revision": CANDIDATE_REVISION,
                    "image_digest": CANDIDATE_DIGEST,
                    "config_digest": config_digest,
                    "config_artifact_digest": CONFIG_ARTIFACT_DIGEST,
                }
            ),
            encoding="utf-8",
        )
        (state_root / f"preflight-{PREFLIGHT_RUN_ID}.json").write_text(
            json.dumps(
                {
                    "schema": "iwork-preflight-receipt/v1",
                    "mode": "Preflight",
                    "run_id": PREFLIGHT_RUN_ID,
                    "request_id": PREFLIGHT_REQUEST_ID,
                    "request_claim_path": str(preflight_request_claim_path),
                    "actor": "GuChenkano",
                    "expected_revision": CANDIDATE_REVISION,
                    "image_digest": CANDIDATE_DIGEST,
                    "config_digest": config_digest,
                    "config_artifact_digest": CONFIG_ARTIFACT_DIGEST,
                    "compose_sha256": hashlib.sha256(compose_content).hexdigest(),
                    "production_env_sha256": hashlib.sha256(profile_content).hexdigest(),
                    "run_migrations": False,
                    "rollback_drill": False,
                    "container_baseline": [
                        {
                            "Name": "DKT_iwork",
                            "ContainerId": "web-container-id",
                            "ConfiguredImage": f"ghcr.io/guchenkano/iwork@{PREVIOUS_DIGEST}",
                            "ImageDigest": PREVIOUS_DIGEST,
                            "Revision": PREVIOUS_REVISION,
                            "ImageId": "sha256:" + "a" * 64,
                            "Status": "running",
                            "Health": "healthy",
                            "RestartCount": 0,
                        },
                        {
                            "Name": "DKT_iwork_alert_worker",
                            "ContainerId": "alert-container-id",
                            "ConfiguredImage": f"ghcr.io/guchenkano/iwork@{PREVIOUS_DIGEST}",
                            "ImageDigest": PREVIOUS_DIGEST,
                            "Revision": PREVIOUS_REVISION,
                            "ImageId": "sha256:" + "b" * 64,
                            "Status": "running",
                            "Health": "healthy",
                            "RestartCount": 0,
                        },
                    ],
                    "result": "validated",
                }
            ),
            encoding="utf-8",
        )
    identity = subprocess.run(  # noqa: S603 - 固定调用Windows系统whoami
        [str(WHOAMI_EXE)],
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    deployment_args = [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DEPLOY_SCRIPT_PATH),
            "-Mode",
            mode,
            "-ImageDigest",
            CANDIDATE_DIGEST,
            "-ExpectedRevision",
            CANDIDATE_REVISION,
            "-RequestId",
            REQUEST_ID,
            "-ConfigDigest",
            config_digest,
            "-ConfigArtifactDigest",
            CONFIG_ARTIFACT_DIGEST,
            "-ConfigBundlePath",
            str(config_bundle),
            "-PreflightRunId",
            PREFLIGHT_RUN_ID if mode == "Deploy" else "none",
            "-PreflightRequestId",
            PREFLIGHT_REQUEST_ID if mode == "Deploy" else "none",
            "-RunMigrations",
            str(run_migrations).lower(),
            "-RollbackDrill",
            str(rollback_drill).lower(),
            "-RunId",
            DEPLOYMENT_RUN_ID,
            "-Actor",
            "GuChenkano",
            "-ChangeDescription",
            "阶段4预检测试",
            "-ExpectedIdentity",
            expected_identity or identity,
            "-IworkRoot",
            str(iwork_root),
            "-StateRoot",
            str(state_root),
            "-LockRoot",
            str(lock_root),
            "-MaintenanceFile",
            str(maintenance_file),
            "-SecretsFile",
            str(secrets),
            "-DockerCommand",
            str(fake_docker_wrapper if emit_compose_progress else fake_docker),
            "-WatchdogScript",
            str(watchdog_script),
            "-WatchdogSha256",
            watchdog_sha256_override or watchdog_sha256,
            "-WatchdogManifestPath",
            str(watchdog_manifest),
            "-WatchdogManifestSha256",
            watchdog_manifest_sha256_override or watchdog_manifest_sha256,
            "-HealthTimeoutSeconds",
            str(health_timeout_seconds),
            "-ProductionMutexName",
            f"Local\\iwork-stage4-production-{tmp_path.name}",
            "-RecoveryMutexName",
            recovery_mutex_name or f"Local\\iwork-stage4-recovery-{tmp_path.name}",
        ]
    if external_probe_receipt:
        deployment_args.extend(
            [
                "-ExternalProbeReceiptPath",
                str(external_probe_receipt_path),
                "-ExternalProbeProducerPath",
                str(external_probe_producer_path if external_probe_producer else tmp_path / "missing-producer.ps1"),
                "-ExternalProbeProducerSha256",
                producer_sha256,
                "-ExternalProbeSigningSecretFile",
                str(external_probe_secret_path),
                "-ExternalProbeSigningSecretSha256",
                secret_sha256,
                "-ExternalProbeProducerExpectedIdentity",
                identity,
                "-TrustManifestPath",
                str(trust_manifest_path),
                "-TrustManifestSha256",
                trust_manifest_sha256,
            ]
        )
    result = subprocess.run(  # noqa: S603 - 仅执行仓库固定脚本与隔离测试参数
        deployment_args,
        capture_output=True,
        encoding="utf-8",
        env=env,
        errors="replace",
    )

    return result, {
        "docker_log": docker_log,
        "state_root": state_root,
        "lock_root": lock_root,
        "maintenance_file": maintenance_file,
        "watchdog_script": watchdog_script,
        "watchdog_manifest": watchdog_manifest,
        "external_probe_receipt": external_probe_receipt_path,
        "external_probe_producer": external_probe_producer_path,
        "trust_manifest": trust_manifest_path,
        "config_bundle": config_bundle,
        "previous_config_path": previous_config_path,
        "previous_config_digest": previous_config_digest,
    }


def test_deploy_fails_closed_without_external_probe_evidence(tmp_path: Path) -> None:
    """正式部署缺少外部探针或收据时不得以容器内检查结果宣告成功。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        external_probe_receipt=False,
    )

    assert result.returncode != 0
    assert "外部探针" in result.stderr


def test_deploy_rejects_external_probe_receipt_created_before_candidate_switch(
    tmp_path: Path,
) -> None:
    """正式部署不得复用候选容器切换前预生成的外部探针收据。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        external_probe_precreated=True,
    )

    assert result.returncode != 0
    assert "切换前" in result.stderr or "已存在" in result.stderr


def test_deploy_fails_closed_without_trusted_external_probe_producer(
    tmp_path: Path,
) -> None:
    """缺少哈希固定的本地主机探针生产者时不得开始候选切换。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        external_probe_producer=False,
    )

    assert result.returncode != 0
    docker_calls = (
        paths["docker_log"].read_text(encoding="utf-8-sig").lower()
        if paths["docker_log"].is_file()
        else ""
    )
    assert "up -d --no-build --no-deps iwork alert-worker" not in docker_calls
    assert "探针生产者" in result.stderr


def test_deploy_requires_exact_six_external_probe_receipt_items(tmp_path: Path) -> None:
    """外部探针收据缺项、重复项和未知项均不得放行部署。"""
    for variant in ("missing", "duplicate", "unknown", "failed"):
        result, paths = _run_deployment_script(
            tmp_path / variant,
            mode="Deploy",
            external_probe_mutation=variant,
        )

        assert result.returncode != 0, variant
        docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
        assert "up -d --no-build --no-deps iwork alert-worker" in docker_calls, variant


def test_deploy_rejects_expired_external_probe_receipt(tmp_path: Path) -> None:
    """外部探针收据超过有效窗口时必须失败并走回滚。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        external_probe_mutation="expired",
    )

    assert result.returncode != 0
    assert "已过期" in result.stderr
    assert (paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json").is_file()


def test_deploy_rejects_signed_probe_receipt_from_before_switch(tmp_path: Path) -> None:
    """即使签名有效，checked_at早于候选切换也必须回滚。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        external_probe_mutation="pre_switch",
    )

    assert result.returncode != 0
    assert "切换前" in result.stderr


def test_deploy_binds_probe_receipt_to_nonce_identity_and_candidate_containers(
    tmp_path: Path,
) -> None:
    """有效签名不能替代nonce、生产者身份和候选双容器的逐项绑定。"""
    expected_errors = {
        "nonce": "nonce",
        "identity": "生产者身份",
        "container": "候选容器绑定",
        "signature": "签名",
    }
    for mutation, expected_error in expected_errors.items():
        result, paths = _run_deployment_script(
            tmp_path / mutation,
            mode="Deploy",
            external_probe_mutation=mutation,
        )

        assert result.returncode != 0, mutation
        assert expected_error in result.stderr, mutation


def test_preflight_fails_closed_on_watchdog_sha256_mismatch(tmp_path: Path) -> None:
    """看门狗脚本哈希不匹配时必须在Docker调用前失败。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        watchdog_sha256_override="0" * 64,
    )

    assert result.returncode != 0
    assert "看门狗SHA-256" in result.stderr
    assert not paths["docker_log"].exists()


def test_preflight_fails_closed_on_watchdog_manifest_sha256_mismatch(
    tmp_path: Path,
) -> None:
    """看门狗机制清单自身哈希不匹配时必须在Docker调用前失败。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        watchdog_manifest_sha256_override="0" * 64,
    )

    assert result.returncode != 0
    assert "机制清单SHA-256" in result.stderr
    assert not paths["docker_log"].exists()


def test_deploy_waits_for_cross_identity_recovery_mutex_to_be_released(
    tmp_path: Path,
) -> None:
    """跨身份恢复锁短暂不可访问时，应等待释放而不是误判为永久失败。"""
    mutex_name = f"Local\\iwork-stage4-restricted-{tmp_path.name}"
    owner_script = tmp_path / "restricted-mutex-owner.ps1"
    ready_file = tmp_path / "restricted-mutex.ready"
    owner_script.write_text(
        """param([string]$Name, [string]$ReadyPath)
$security = New-Object System.Security.AccessControl.MutexSecurity
$rights = [System.Security.AccessControl.MutexRights]::Modify -bor [System.Security.AccessControl.MutexRights]::Synchronize
$sid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$rule = [System.Security.AccessControl.MutexAccessRule]::new($sid, $rights, [System.Security.AccessControl.AccessControlType]::Allow
)
$security.AddAccessRule($rule)
$created = $false
$mutex = [System.Threading.Mutex]::new($false, $Name, [ref]$created, $security)
$mutex.WaitOne(0) | Out-Null
Set-Content -LiteralPath $ReadyPath -Value 'ready' -NoNewline
Start-Sleep -Seconds 2
$mutex.ReleaseMutex()
$mutex.Dispose()
""",
        encoding="utf-8",
    )
    owner = subprocess.Popen(  # noqa: S603 - 仅执行固定的隔离PowerShell测试脚本
        [
            str(POWERSHELL_EXE),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(owner_script),
            "-Name",
            mutex_name,
            "-ReadyPath",
            str(ready_file),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        for _ in range(40):
            if ready_file.is_file():
                break
            if owner.poll() is not None:
                break
            time.sleep(0.1)
        assert ready_file.is_file(), owner.stderr.read() if owner.stderr else ""
        result, paths = _run_deployment_script(
            tmp_path / "deployment",
            mode="Deploy",
            recovery_mutex_name=mutex_name,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["Result"] == "deployed"
        assert not (paths["lock_root"] / "production-deploy.lock").exists()
    finally:
        if owner.poll() is None:
            owner.terminate()
        owner.wait(timeout=10)


def test_production_entry_rejects_wrong_expected_identity_fail_closed(
    tmp_path: Path,
) -> None:
    """生产入口收到错误ExpectedIdentity时，必须失败且不得创建部署状态。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        expected_identity="DONGMING\\identity-that-does-not-exist",
    )

    assert result.returncode != 0
    assert "部署身份不正确" in result.stderr
    assert list(paths["state_root"].iterdir()) == []
    assert list(paths["lock_root"].iterdir()) == []


def test_preflight_validates_candidate_without_mutating_containers(tmp_path: Path) -> None:
    """预检应验证镜像、Compose和容器状态，但不得执行容器切换。"""
    result, paths = _run_deployment_script(tmp_path, mode="Preflight")

    assert result.returncode == 0, result.stderr
    assert '"Mode":"Preflight"' in result.stdout
    preflight = json.loads(result.stdout)
    assert preflight["PreviousWebImageId"].startswith("sha256:")
    assert preflight["PreviousAlertWorkerImageId"].startswith("sha256:")
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert "info" in docker_calls
    assert "image inspect" in docker_calls
    assert "compose" in docker_calls and "config --quiet" in docker_calls
    assert "inspect dkt_iwork" in docker_calls
    assert "inspect dkt_iwork_alert_worker" in docker_calls
    for forbidden in (" up ", " down ", " run ", " stop ", " rm "):
        assert forbidden not in f" {docker_calls} "
    receipt_path = paths["state_root"] / f"preflight-{DEPLOYMENT_RUN_ID}.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "iwork-preflight-receipt/v1"
    assert receipt["request_id"] == REQUEST_ID
    assert receipt["config_artifact_digest"] == CONFIG_ARTIFACT_DIGEST
    assert list(paths["lock_root"].iterdir()) == []
    assert not paths["maintenance_file"].exists()


def test_preflight_rejects_tampered_or_mismatched_config_before_docker(
    tmp_path: Path,
) -> None:
    """配置包被篡改或身份错配时，必须在任何Docker调用前失败关闭。"""
    cases = {
        "tampered": {"tamper_config_after_manifest": True},
        "unknown-file": {"add_unknown_config_file": True},
        "wrong-commit": {"config_source_commit": "3" * 40},
        "wrong-image": {
            "config_image_digest": "sha256:" + "4" * 64,
        },
    }

    for case_name, kwargs in cases.items():
        result, paths = _run_deployment_script(
            tmp_path / case_name,
            mode="Preflight",
            **kwargs,
        )
        assert result.returncode != 0, case_name
        assert not paths["docker_log"].exists(), case_name
        assert not paths["maintenance_file"].exists(), case_name


def test_deploy_archives_expired_owned_maintenance_marker(tmp_path: Path) -> None:
    """取得双Mutex和新协调锁后，应归档可信且已过期的旧维护标记。"""
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        existing_maintenance_marker={
            "application": "iwork",
            "operation": "production_deployment",
            "workflow_run_id": "654321-1",
            "actor": "GuChenkano",
            "started_at": (expired_at - timedelta(minutes=19)).isoformat(),
            "expires_at": expired_at.isoformat(),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not paths["maintenance_file"].exists()
    archives = list(
        paths["maintenance_file"].parent.glob(
            "iwork-deployment.json.stale.*.json"
        )
    )
    assert len(archives) == 1


def test_deploy_preserves_untrusted_expired_maintenance_markers(
    tmp_path: Path,
) -> None:
    """不完整或不可信的iwork维护标记必须保留并使部署失败关闭。"""
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    valid_marker: dict[str, object] = {
        "application": "iwork",
        "operation": "production_deployment",
        "workflow_run_id": "654321-1",
        "actor": "GuChenkano",
        "started_at": (expired_at - timedelta(minutes=19)).isoformat(),
        "expires_at": expired_at.isoformat(),
    }
    invalid_markers = {
        "missing-started-at": {
            key: value
            for key, value in valid_marker.items()
            if key != "started_at"
        },
        "reversed-window": {
            **valid_marker,
            "started_at": (expired_at + timedelta(minutes=1)).isoformat(),
        },
        "overlong-window": {
            **valid_marker,
            "started_at": (expired_at - timedelta(minutes=21)).isoformat(),
        },
        "invalid-run-id": {
            **valid_marker,
            "workflow_run_id": "invalid run id",
        },
        "invalid-status": {**valid_marker, "status": "failed"},
        "invalid-actor": {**valid_marker, "actor": 123},
        "future-window": {
            **valid_marker,
            "started_at": (expired_at + timedelta(days=1)).isoformat(),
            "expires_at": (
                expired_at + timedelta(days=1, minutes=19)
            ).isoformat(),
        },
    }

    for case_name, marker in invalid_markers.items():
        result, paths = _run_deployment_script(
            tmp_path / case_name,
            mode="Deploy",
            existing_maintenance_marker=marker,
        )
        assert result.returncode != 0, case_name
        assert paths["maintenance_file"].is_file(), case_name
        assert not list(
            paths["maintenance_file"].parent.glob(
                "iwork-deployment.json.stale.*.json"
            )
        ), case_name


def test_preflight_does_not_archive_expired_maintenance_without_lock(
    tmp_path: Path,
) -> None:
    """只读预检未取得协调锁时，不得处理其他运行遗留的维护标记。"""
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        existing_maintenance_marker={
            "application": "iwork",
            "operation": "production_deployment",
            "workflow_run_id": "654322-1",
            "actor": "GuChenkano",
            "started_at": (expired_at - timedelta(minutes=19)).isoformat(),
            "expires_at": expired_at.isoformat(),
        },
    )

    assert result.returncode != 0
    assert paths["maintenance_file"].is_file()
    assert not list(
        paths["maintenance_file"].parent.glob(
            "iwork-deployment.json.stale.*.json"
        )
    )


def test_deploy_does_not_archive_active_maintenance_marker(tmp_path: Path) -> None:
    """即使取得新锁，未过期维护标记仍必须失败关闭并保留原文件。"""
    started_at = datetime.now(timezone.utc)
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        existing_maintenance_marker={
            "application": "iwork",
            "operation": "production_deployment",
            "workflow_run_id": "654323-1",
            "actor": "GuChenkano",
            "started_at": started_at.isoformat(),
            "expires_at": (started_at + timedelta(minutes=20)).isoformat(),
        },
    )

    assert result.returncode != 0
    assert paths["maintenance_file"].is_file()
    assert not (paths["lock_root"] / "production-deploy.lock").exists()


def test_preflight_waits_for_transient_alert_worker_health_recovery(
    tmp_path: Path,
) -> None:
    """镜像拉取造成短时探针超时时，预检应在严格时限内等待恢复。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        transient_alert_unhealthy_checks=1,
        health_timeout_seconds=5,
    )

    assert result.returncode == 0, result.stderr
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert docker_calls.count(
        "inspect dkt_iwork_alert_worker --format {{json .state}}"
    ) >= 2


def test_deploy_switches_both_services_and_records_rollback_state(
    tmp_path: Path,
) -> None:
    """部署应同时切换Web与告警Worker，并保存可追溯回滚状态。"""
    result, paths = _run_deployment_script(tmp_path, mode="Deploy")

    assert result.returncode == 0, result.stderr
    assert '"Mode":"Deploy"' in result.stdout
    assert '"Result":"deployed"' in result.stdout
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert f"ghcr.io/guchenkano/iwork@{CANDIDATE_DIGEST}" in docker_calls
    assert "compose" in docker_calls
    assert "up -d --no-build --no-deps iwork alert-worker" in docker_calls
    assert "exec dkt_iwork python manage.py check --deploy" in docker_calls
    assert "exec dkt_iwork_alert_worker celery" in docker_calls
    assert " down " not in f" {docker_calls} "

    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "deployed"
    assert state["PreviousWebImageId"].startswith("sha256:")
    assert state["PreviousAlertWorkerImageId"].startswith("sha256:")
    assert state["PreviousImageDigest"] == PREVIOUS_DIGEST
    assert state["PreviousRevision"] == PREVIOUS_REVISION
    assert state["PreviousContainers"][0]["ContainerId"] == "web-container-id"
    assert state["PreviousContainers"][0]["RestartCount"] == 0
    assert state["PreviousContainers"][0]["Health"] == "healthy"
    assert state["CandidateConfigDigest"].startswith("sha256:")
    assert state["RequestId"] == REQUEST_ID
    assert state["CandidateComposeSha256"] == hashlib.sha256(
        b"services: {}\n"
    ).hexdigest()
    assert state["CandidateProductionEnvSha256"] == hashlib.sha256(
        b"DKT_ENVIRONMENT=production\n"
    ).hexdigest()
    assert state["ExternalProbe"]["Mode"] == "receipt"
    assert state["ExternalProbe"]["StatusCode"] == 200
    archived_receipt = Path(state["ExternalProbe"]["ReceiptPath"])
    assert archived_receipt.is_file()
    assert Path(state["ExternalProbe"]["SignaturePath"]).is_file()
    assert not paths["external_probe_receipt"].exists()
    assert state["PreviousConfigDigest"] == state["CandidateConfigDigest"]
    assert state["PreviousConfigBootstrap"] is True
    active_release = json.loads(
        paths["state_root"].joinpath("active-release.json").read_text(
            encoding="utf-8"
        )
    )
    assert active_release["schema"] == "iwork-active-release/v1"
    assert active_release["config_digest"] == state["CandidateConfigDigest"]
    assert active_release["image_digest"] == CANDIDATE_DIGEST
    assert active_release["request_id"] == REQUEST_ID
    assert not (paths["lock_root"] / "production-deploy.lock").exists()
    assert not paths["maintenance_file"].exists()


def test_deploy_accepts_successful_compose_progress_on_stderr(tmp_path: Path) -> None:
    """Compose退出码为0时，标准错误中的正常进度不得触发错误回滚。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        emit_compose_progress=True,
    )

    assert result.returncode == 0, result.stderr
    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "deployed"
    assert state["RollbackSucceeded"] is False


def test_controlled_rollback_drill_restores_both_previous_images(
    tmp_path: Path,
) -> None:
    """受控演练应复用真实回滚路径，并把成功证据写入状态文件。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        rollback_drill=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["Result"] == "rolled_back"
    assert summary["RollbackDrill"] is True

    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert docker_calls.count("up -d --no-build --no-deps iwork alert-worker") == 2
    persisted_config_path = str(paths["state_root"] / "release-config").lower()
    assert docker_calls.count(persisted_config_path) >= 2
    assert f"ghcr.io/guchenkano/iwork@{PREVIOUS_DIGEST}" in docker_calls
    assert docker_calls.count("inspect dkt_iwork --format {{.image}}") >= 2
    assert docker_calls.count("inspect dkt_iwork_alert_worker --format {{.image}}") >= 2

    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "rolled_back"
    assert state["RollbackSucceeded"] is True
    assert state["RollbackDrill"] is True
    assert state["DeploymentError"] == "受控回滚演练触发"

    drill_file = paths["state_root"] / "rollback-drill-v1.json"
    drill = json.loads(drill_file.read_text(encoding="utf-8"))
    assert drill["Status"] == "succeeded"
    assert drill["RunId"] == DEPLOYMENT_RUN_ID
    assert drill["PreviousWebImageId"].startswith("sha256:")
    assert drill["PreviousAlertWorkerImageId"].startswith("sha256:")
    assert drill["PreviousImageDigest"] == PREVIOUS_DIGEST
    assert drill["PreviousRevision"] == PREVIOUS_REVISION
    assert not (paths["lock_root"] / "production-deploy.lock").exists()
    assert not paths["maintenance_file"].exists()


def test_controlled_rollback_drill_rejects_every_repeated_attempt(
    tmp_path: Path,
) -> None:
    """一次性演练记录存在时，必须在切换容器前拒绝再次执行。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        rollback_drill=True,
        existing_rollback_drill_marker=True,
    )

    assert result.returncode != 0
    assert "拒绝重复执行" in result.stderr
    assert not paths["docker_log"].exists()
    drill_file = paths["state_root"] / "rollback-drill-v1.json"
    drill = json.loads(drill_file.read_text(encoding="utf-8"))
    assert drill == {"Status": "failed", "RunId": "previous-attempt"}


def test_controlled_rollback_drill_stops_after_unexpected_failure(
    tmp_path: Path,
) -> None:
    """演练中出现非受控异常时应回滚但返回失败，并永久保留失败记录。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        rollback_drill=True,
        fail_validation=True,
    )

    assert result.returncode != 0
    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "rolled_back"
    assert state["RollbackSucceeded"] is True

    drill_file = paths["state_root"] / "rollback-drill-v1.json"
    drill = json.loads(drill_file.read_text(encoding="utf-8"))
    assert drill["Status"] == "failed"
    assert "Injected Django validation failure" in drill["Error"]


def test_controlled_rollback_drill_rejects_database_migrations(
    tmp_path: Path,
) -> None:
    """受控回滚演练不得执行不可自动回滚的数据库迁移。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        rollback_drill=True,
        run_migrations=True,
    )

    assert result.returncode != 0
    assert "run_migrations=true已禁用" in result.stderr
    assert not paths["docker_log"].exists()
    assert not (paths["state_root"] / "rollback-drill-v1.json").exists()


def test_rollback_failure_is_visible_in_job_error_and_state(tmp_path: Path) -> None:
    """自动回滚失败时，任务错误和状态文件都必须明确暴露严重故障。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        fail_validation=True,
        fail_rollback=True,
    )

    assert result.returncode != 0
    assert "自动回滚失败" in result.stderr
    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "rollback_failed"
    assert state["RollbackSucceeded"] is False
    assert "Injected rollback compose failure" in state["RollbackError"]


def test_deploy_failure_automatically_restores_both_previous_images(
    tmp_path: Path,
) -> None:
    """部署后验收失败时，应自动恢复两个服务并释放维护状态。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        fail_validation=True,
    )

    assert result.returncode != 0
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert docker_calls.count("up -d --no-build --no-deps iwork alert-worker") == 2
    assert f"ghcr.io/guchenkano/iwork@{PREVIOUS_DIGEST}" in docker_calls
    assert docker_calls.count("exec dkt_iwork python manage.py check --deploy") == 2
    assert docker_calls.count("exec dkt_iwork_alert_worker celery") == 1

    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "rolled_back"
    assert state["RollbackSucceeded"] is True
    assert "Injected Django validation failure" in state["DeploymentError"]
    assert not (paths["lock_root"] / "production-deploy.lock").exists()
    assert not paths["maintenance_file"].exists()


def test_deploy_failure_restores_previous_image_and_previous_config(
    tmp_path: Path,
) -> None:
    """存在活动发布指针时，候选失败必须成对恢复旧镜像和旧配置。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        fail_validation=True,
        existing_active_config=True,
    )

    assert result.returncode != 0
    state = json.loads(
        (paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["Status"] == "rolled_back"
    assert state["RollbackSucceeded"] is True
    assert state["PreviousConfigBootstrap"] is False
    assert state["PreviousConfigDigest"] == paths["previous_config_digest"]
    assert state["PreviousConfigDigest"] != state["CandidateConfigDigest"]
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert str(paths["previous_config_path"]).lower() in docker_calls
    assert (
        f"release-profile={paths['previous_config_path']}\\env\\production.env".lower()
        in docker_calls
    )
    active_release = json.loads(
        (paths["state_root"] / "active-release.json").read_text(encoding="utf-8")
    )
    assert active_release["config_digest"] == paths["previous_config_digest"]


def test_active_release_pointer_must_bind_audit_identity_and_config_hashes(
    tmp_path: Path,
) -> None:
    """活动发布指针的request_id和配置文件哈希被篡改时必须在切换前失败。"""
    for field in ("request_id", "compose_sha256"):
        result, paths = _run_deployment_script(
            tmp_path / field,
            mode="Deploy",
            existing_active_config=True,
            tamper_active_release_field=field,
        )

        assert result.returncode != 0, field
        docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
        assert "up -d --no-build --no-deps iwork alert-worker" not in docker_calls
        assert "活动发布指针" in result.stderr


def test_migration_deployment_is_disabled_without_compatibility_evidence(
    tmp_path: Path,
) -> None:
    """没有机器可验证兼容性证据时，迁移开关必须在Docker调用前失败关闭。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        run_migrations=True,
    )

    assert result.returncode != 0
    assert "run_migrations=true已禁用" in result.stderr
    assert not paths["docker_log"].exists()
    assert not (paths["state_root"] / "backups").exists()


def test_database_backup_is_restricted_to_runner_system_and_administrators() -> None:
    """数据库备份必须移除继承权限，仅保留执行账号、SYSTEM和管理员。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "SetAccessRuleProtection($true, $false)" in content
    assert "S-1-5-18" in content
    assert "S-1-5-32-544" in content
    assert "[Security.Principal.WindowsIdentity]::GetCurrent().User" in content
    assert "[IO.FileInfo]::new($Path).SetAccessControl($acl)" in content


def test_preflight_rejects_watchdog_without_shared_recovery_mutex(
    tmp_path: Path,
) -> None:
    """看门狗未使用同一恢复锁时，预检必须失败并禁止部署。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        watchdog_uses_shared_mutex=False,
    )

    assert result.returncode != 0
    assert "Global\\DKT-Docker-Recovery" in result.stderr
    assert list(paths["state_root"].iterdir()) == []
    assert list(paths["lock_root"].iterdir()) == []


def test_shared_mutex_acl_contract_covers_system_runner_and_diagnostics() -> None:
    """跨身份共享Mutex必须显式授予权限并诊断访问拒绝。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "MutexSecurity" in content
    assert "MutexAccessRule" in content
    assert "MutexRights" in content
    assert "S-1-5-18" in content
    assert "S-1-5-32-544" in content
    assert "UnauthorizedAccessException" in content
    assert "Security.SecurityException" in content
    assert "WindowsIdentity]::GetCurrent().Name" in content
    assert "无法取得共享部署互斥锁" in content


def test_deployment_only_removes_locks_and_markers_it_created() -> None:
    """部署进程未取得所有权时，不得删除其他运维进程的锁或维护标记。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert "$coordinationLock = $null" in content
    assert "if ($null -ne $coordinationLock)" in content
    assert "Exit-ProductionCoordinationLock -Lock $coordinationLock" in content
    assert "$ownsMaintenanceFile = $false" in content
    assert "$ownsMaintenanceFile = $true" in content
    assert "if ($ownsMaintenanceFile)" in content


def test_maintenance_cleanup_failure_still_releases_lock_and_records_failure(
    tmp_path: Path,
) -> None:
    """维护标记清理失败时，协调锁仍应释放且部署状态必须暴露失败。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        fail_maintenance_cleanup=True,
    )

    assert result.returncode != 0
    assert "部署清理失败" in result.stderr
    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["Status"] == "cleanup_failed"
    assert state["CleanupSucceeded"] is False
    assert any("维护标记清理失败" in error for error in state["CleanupErrors"])
    assert not (paths["lock_root"] / "production-deploy.lock").exists()
    assert paths["maintenance_file"].is_dir()


def test_stage6_cleanup_failures_are_isolated_visible_and_fatal() -> None:
    """阶段六清理失败必须隔离后续释放、可记录并使部署结果失败。"""
    content = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")
    cleanup = content[content.rfind("    finally {"):]

    assert re.search(
        r"try\s*\{.*?\$ownsMaintenanceFile.*?Remove-Item.*?-ErrorAction Stop.*?\}\s*catch",
        cleanup,
        re.DOTALL,
    )
    assert re.search(
        r"try\s*\{.*?\$coordinationLock.*?Exit-ProductionCoordinationLock.*?\}\s*catch",
        cleanup,
        re.DOTALL,
    )
    assert re.search(
        r"try\s*\{.*?Exit-DeploymentMutex -Mutex \$recoveryMutex.*?\}\s*catch",
        cleanup,
        re.DOTALL,
    )
    assert re.search(
        r"try\s*\{.*?Exit-DeploymentMutex -Mutex \$productionMutex.*?\}\s*catch",
        cleanup,
        re.DOTALL,
    )
    assert "-ErrorAction SilentlyContinue" not in cleanup
    assert "$cleanupErrors" in cleanup
    assert "CleanupErrors" in cleanup
    assert "cleanup_failed" in cleanup
    assert "部署清理失败" in cleanup


def test_apply_rerun_is_rejected_before_server_consumes_confirmation() -> None:
    """apply=true 的 Workflow re-run 必须因 run_attempt 非首次而失败关闭。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert (
        "if ($env:APPLY -eq 'true' -and $env:GITHUB_RUN_ATTEMPT -ne '1')"
        in content
    )
    assert "re-run" in content.lower() or "rerun" in content.lower()
    assert "$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT" in content


def test_temporary_setup_is_scoped_and_cleanup_preserves_original_error() -> None:
    """临时目录初始化失败或清理失败时，必须可审计且不覆盖原始部署异常。"""
    content = DEPLOY_WORKFLOW_PATH.read_text(encoding="utf-8")
    init_index = content.index("$env:DOCKER_CONFIG = Join-Path")
    setup_scope = content[init_index - 120 : init_index + 220]

    assert "try {" in setup_scope
    assert "$deploymentError = $null" in content
    assert "if ($null -ne $deploymentError)" in content
    assert "cleanup_failed" in content


def test_server_consumes_request_id_once_and_rejects_replay(tmp_path: Path) -> None:
    """固定服务器脚本必须拒绝已消费request_id，不能靠本机Skill防重放。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Preflight",
        preconsumed_request=True,
    )

    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "request_id已经被服务器消费" in combined
    claim = paths["state_root"] / "request-consumption" / f"{REQUEST_ID}.json"
    assert claim.is_file()
