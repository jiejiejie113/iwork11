"""生产Self-hosted Runner阶段3安全契约测试。"""

from pathlib import Path


# ======
# 阶段3文件路径配置
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "runner-smoke.yml"
INSTALLER_PATH = ROOT / "scripts" / "Install-GitHubProductionRunner.ps1"


def _read(path: Path) -> str:
    """读取阶段3文本文件。

    Args:
        path (Path): 待读取文件路径。

    Returns:
        str: UTF-8文本内容。
    """
    return path.read_text(encoding="utf-8")


def test_iwork_runner_smoke_workflow_is_manual_and_read_only() -> None:
    """iwork生产Runner只允许所有者手工执行固定的只读验收。"""
    content = _read(WORKFLOW_PATH)
    lowered = content.lower()

    assert "workflow_dispatch:" in content
    assert "github.actor == 'GuChenkano'" in content
    assert "github.ref == 'refs/heads/Keycloak'" in content
    assert "self-hosted" in content
    assert "dkt-prod" in content
    assert "iwork" in content
    assert "environment: production-runner-validation" in content
    assert "contents: none" in content
    assert "packages: read" in content
    assert "timeout-minutes: 12" in content
    assert r"DONGMING\shuju" in content
    assert "DOCKER_CONFIG" in content
    assert "RUNNER_TEMP" in content
    assert "--password-stdin" in content
    assert "org.opencontainers.image.revision" in content
    assert (
        "ghcr.io/guchenkano/iwork@sha256:"
        "2d636c8e09f11667039e3322c6422bea870ebd577dfa1e6686c36b157009390c"
        in lowered
    )
    assert "51c1911e867c7183eef45b66b7fa6bc35ee8d676" in lowered

    for forbidden in (
        "pull_request:",
        "pull_request_target",
        "push:",
        "actions/checkout",
        "contents: write",
        "packages: write",
        "dkt-secrets.env",
        "docker compose",
        "docker run",
        "deploy.ps1",
        "ssh ",
    ):
        assert forbidden not in lowered


def test_runner_installer_uses_pinned_package_and_s4u_policy_hook() -> None:
    """Runner安装器必须固定官方包并使用S4U和本机准入钩子。"""
    content = _read(INSTALLER_PATH)

    assert "actions-runner-win-x64-2.336.0.zip" in content
    assert "d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162" in content
    assert "RegistrationTokenFromStdin" in content
    assert "[Console]::In.ReadLine()" in content
    assert "ResumeConfiguredRunner" in content
    assert "Configured runner cannot be resumed because .runner is missing" in content
    assert "Resume refused: stop the task and listeners only after an external" in content
    assert "--unattended" in content
    assert "--replace" in content
    assert r"D:\DM\actions-runner" in content
    assert r"D:\DM\cicd-locks" in content
    assert r"D:\DM\cicd-state" in content
    assert "ACTIONS_RUNNER_HOOK_JOB_STARTED" in content
    assert "GITHUB_EVENT_NAME" in content
    assert "GITHUB_ACTOR" in content
    assert "GITHUB_WORKFLOW_REF" in content
    assert "New-ScheduledTaskPrincipal" in content
    assert "$comTaskPath = $TASK_PATH.TrimEnd('\\')" in content
    assert "$service.GetFolder($comTaskPath)" in content
    assert "-LogonType S4U" in content
    assert "-RunLevel Highest" in content
    assert "New-ScheduledTaskTrigger -AtStartup" in content
    assert "New-ScheduledTaskTrigger -AtLogOn" in content
    assert "-RepetitionInterval (New-TimeSpan -Minutes 1)" in content
    assert "-RepetitionDuration (New-TimeSpan -Days 9999)" in content
    assert "@($startupTrigger, $logonTrigger, $recoveryTrigger)" in content
    assert "docker info" in content
    assert "run.cmd" in content
    assert "Runner.Listener.exe" in content
    assert "$unexpectedCleanExitCode = 71" in content
    assert "if ($runnerExitCode -eq 0)" in content
    assert "Runner registration did not create the .runner configuration file." in content
    assert "Remove-Item -LiteralPath $installDirectory -Recurse -Force" in content

    for forbidden in (
        "dkt-secrets.env",
        "docker compose up",
        "docker compose down",
        "docker run",
        "git clean",
        "git reset",
        r"D:\DM\iwork",
        r"D:\DM\DTD_nginx",
    ):
        assert forbidden not in content
