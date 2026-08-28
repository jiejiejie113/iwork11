"""阶段4 iwork受控生产部署安全契约测试。"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess

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
    "beb88d9bf07143102c0398edf75f6665dcd1ee48fc1604b22ecae3bafc1cf882"
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
    assert "change_description:" in content
    assert "confirmation:" in content
    assert "type: boolean" in content
    assert "default: false" in content
    assert "DEPLOY IWORK WITH MIGRATIONS" in content
    assert "github.actor == 'GuChenkano'" in content
    assert "github.ref == 'refs/heads/Keycloak'" in content
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
    assert "$env:EXPECTED_REVISION -cne $env:GITHUB_SHA" in content
    assert "actions/workflows/$WorkflowFile/runs" in content
    assert "-WorkflowFile 'ci.yml'" in content
    assert "-WorkflowFile 'release.yml'" in content
    assert "$_.conclusion -eq 'success'" in content
    assert "Remove-Item -LiteralPath $env:DOCKER_CONFIG -Recurse -Force" in content
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
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in content
    assert "iwork-production-config-${{ inputs.expected_revision }}" in content
    assert "run-id: ${{ steps.release.outputs.run_id }}" in content
    assert "CONFIG_DIGEST: ${{ inputs.config_digest }}" in content
    assert "CONFIG_ARTIFACT_DIGEST: ${{ inputs.config_artifact_digest }}" in content
    assert "RELEASE_REQUEST_ID: ${{ inputs.release_request_id }}" in content
    assert "$_.event -eq 'workflow_dispatch'" in content
    assert "$_.head_branch -eq 'Keycloak'" in content
    assert "actions/runs/$($candidate.id)/artifacts" in content
    assert "$_.digest -ceq $env:CONFIG_ARTIFACT_DIGEST" in content
    assert "matchingReleaseRuns.Count -ne 1" in content
    assert "([string]$_.display_title).Contains($env:RELEASE_REQUEST_ID)" in content
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


def test_production_coordination_module_is_bom_pinned_and_integrated() -> None:
    """统一协调模块必须字节固定，并由部署脚本接入三段式锁生命周期。"""
    module_bytes = COORDINATION_MODULE_PATH.read_bytes()
    assert module_bytes.startswith(b"\xef\xbb\xbf")
    assert hashlib.sha256(module_bytes).hexdigest() == EXPECTED_COORDINATION_MODULE_SHA256

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
    assert '"${IWORK_RUN_MIGRATIONS:-true}" = "true"' in content
    assert "根据部署策略跳过数据库迁移" in content


def test_compose_env_file_is_overridable_by_verified_release_profile() -> None:
    """生产脚本必须能让Compose服务直接读取配置包内环境文件。"""
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8-sig")

    assert compose.count("IWORK_RELEASE_PROFILE_FILE") == 2
    assert "./env/${DKT_ENVIRONMENT:-production}.env" in compose
    assert "$env:IWORK_RELEASE_PROFILE_FILE = $ProfileFile" in script
    assert "Invoke-DockerCommandWithProfile" in script


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
    config_bundle = tmp_path / "config-bundle"

    profile.parent.mkdir(parents=True)
    state_root.mkdir()
    lock_root.mkdir()
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
        (state_root / f"preflight-{PREFLIGHT_RUN_ID}.json").write_text(
            json.dumps(
                {
                    "schema": "iwork-preflight-receipt/v1",
                    "mode": "Preflight",
                    "run_id": PREFLIGHT_RUN_ID,
                    "request_id": PREFLIGHT_REQUEST_ID,
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
    result = subprocess.run(  # noqa: S603 - 仅执行仓库固定脚本与隔离测试参数
        [
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
            identity,
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
            "-HealthTimeoutSeconds",
            str(health_timeout_seconds),
            "-ProductionMutexName",
            f"Local\\iwork-stage4-production-{tmp_path.name}",
            "-RecoveryMutexName",
            f"Local\\iwork-stage4-recovery-{tmp_path.name}",
        ],
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
        "config_bundle": config_bundle,
        "previous_config_path": previous_config_path,
        "previous_config_digest": previous_config_digest,
    }


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
    assert "禁止执行数据库迁移" in result.stderr
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


def test_migration_deployment_creates_database_backup_and_checksum(
    tmp_path: Path,
) -> None:
    """启用迁移时，切换容器前必须生成数据库备份及SHA-256。"""
    result, paths = _run_deployment_script(
        tmp_path,
        mode="Deploy",
        run_migrations=True,
    )

    assert result.returncode == 0, result.stderr
    docker_calls = paths["docker_log"].read_text(encoding="utf-8-sig").lower()
    assert "exec dkt_mysql sh -c" in docker_calls
    assert "mysqldump" in docker_calls
    assert f"cp dkt_mysql:/tmp/iwork-{DEPLOYMENT_RUN_ID}.sql" in docker_calls

    state_file = paths["state_root"] / f"{DEPLOYMENT_RUN_ID}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    backup_path = Path(state["DatabaseBackupPath"])
    assert backup_path.is_file()
    assert backup_path.stat().st_size > 0
    assert len(state["DatabaseBackupSha256"]) == 64


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
