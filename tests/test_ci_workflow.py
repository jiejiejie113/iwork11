"""GitHub Actions纯CI工作流安全契约测试。"""

import re
from pathlib import Path

import yaml


# ======
# CI文件路径配置
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"


def _read_workflow() -> str:
    """读取CI工作流文本。

    Returns:
        str: CI工作流完整文本。
    """
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _read_release_workflow() -> str:
    """读取GHCR发布工作流文本。

    Returns:
        str: GHCR发布工作流完整文本。
    """
    return RELEASE_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_ci_workflow_is_hosted_and_cannot_touch_production() -> None:
    """CI只能使用GitHub托管Runner，且不得包含任何生产部署入口。"""
    content = _read_workflow()
    lowered = content.lower()

    assert "runs-on: ubuntu-latest" in content
    for forbidden in (
        "self-hosted",
        "pull_request_target",
        "dkt-secrets.env",
        "production.env",
        "docker compose up",
        "docker login",
        "docker push",
        "deploy.ps1",
        "ghcr.io",
        "packages: write",
        "secrets.",
        "ssh ",
        "192.168.0.97",
    ):
        assert forbidden not in lowered


def test_ci_workflow_uses_pinned_actions_and_expected_checks() -> None:
    """CI必须固定Action提交，并执行隔离测试、生产包Ruff和无密钥镜像构建。"""
    content = _read_workflow()
    action_uses = re.findall(r"uses:\s+[^\s]+@([^\s]+)", content)

    assert action_uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in action_uses)
    assert "Keycloak" in content
    assert "contents: read" in content
    assert "python -m pytest tests/ -q" in content
    assert "python -m ruff check --no-cache" in content
    assert "--ignore E402,W292 iwork" in content
    assert "docker build" in content
    assert "ci-iwork:$env:GITHUB_SHA" in content
    assert "${GITHUB_SHA}" not in content
    assert "清除临时构建上下文中的环境文件" in content
    assert "request_id:" in content
    assert "required: true" in content
    assert "inputs.request_id || github.run_id" not in content
    assert "inputs.request_id || github.sha" in content
    assert "IWORK_REQUEST_ID=" in content


def test_ci_test_job_preserves_non_secret_environment_profiles() -> None:
    """测试Job必须保留供安全契约测试读取的无密钥环境配置模板。"""
    content = _read_workflow()
    test_job = content.split("  build:", maxsplit=1)[0]

    assert "Get-ChildItem -Path . -Recurse" not in test_job
    assert "Remove-Item -LiteralPath .env -Force" in test_job


def test_release_workflow_publishes_image_and_immutable_config_bundle() -> None:
    """Release只能由托管Runner发布同一Commit的镜像与最小配置包。"""
    content = _read_release_workflow()
    lowered = content.lower()
    action_uses = re.findall(r"uses:\s+[^\s]+@([^\s]+)", content)

    assert "workflow_dispatch:" in content
    assert "request_id:" in content
    assert "ci_request_id:" in content
    assert "required: true" in content
    assert "inputs.request_id || github.run_id" not in content
    assert "inputs.request_id || github.sha" in content
    # 发布入口不再接受可变的iwork-v*标签，仅允许带request_id的手工触发。
    assert "iwork-v*" not in content
    assert "runs-on: ubuntu-latest" in content
    assert "needs: verify-ci" in content
    assert "actions/workflows/ci.yml/runs" in content
    assert "run_url: ${{ steps.ci.outputs.run_url }}" in content
    assert "packages: write" in content
    assert "contents: read" in content
    assert "ghcr.io/guchenkano/iwork" in lowered
    assert "org.opencontainers.image.revision" in content
    assert "--format '{{.Manifest.Digest}}'" in content
    assert "[DateTimeOffset]::UtcNow" in content
    assert "duration_seconds" in content
    assert "GITHUB_RUN_ID" in content
    assert "CI_REQUEST_ID" in content
    assert '$_.event -eq "workflow_dispatch"' in content
    assert '([string]$_.display_title).Contains($env:CI_REQUEST_ID)' in content
    assert content.count("$startedAt = [DateTimeOffset]::UtcNow") == 1
    assert "docker push" in content
    assert "docker pull" in content
    assert "docker logout ghcr.io" in content
    assert "New-IworkProductionConfigBundle.ps1" in content
    assert "IWORK_IMAGE_DIGEST=" in content
    assert "IWORK_CONFIG_DIGEST=" in content
    assert "IWORK_CONFIG_ARTIFACT_DIGEST=" in content
    assert "IWORK_REQUEST_ID=" in content
    assert (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
        in content
    )
    assert "iwork-production-config-${{ github.sha }}" in content
    assert "retention-days: 90" in content
    assert "if-no-files-found: error" in content
    assert "persist-credentials: false" in content
    assert "[int] $Attempts = 1" in content
    assert "for ($attempt = 1; $attempt -le $Attempts; $attempt++)" in content
    assert "Start-Sleep -Seconds $DelaySeconds" in content
    assert (
        "Get-RemoteDigest -ImageReference $env:IMAGE_REF -Attempts 6 -DelaySeconds 5"
        in content
    )
    assert content.count("-Attempts 6 -DelaySeconds 5") == 1
    assert content.index("docker push $env:IMAGE_REF") < content.index(
        "Get-RemoteDigest -ImageReference $env:IMAGE_REF -Attempts 6 -DelaySeconds 5"
    )
    assert action_uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in action_uses)

    for forbidden in (
        "pull_request:",
        "pull_request_target",
        "self-hosted",
        ":latest",
        "secrets.",
        "dkt-secrets.env",
        "docker compose up",
        "deploy.ps1",
        "ssh ",
        "192.168.0.97",
    ):
        assert forbidden not in lowered


def test_release_publish_job_keeps_permissions_and_environment_at_job_scope() -> None:
    """Release发布Job的权限声明不能被环境变量映射污染。"""
    workflow = yaml.safe_load(_read_release_workflow())
    jobs = workflow.get("jobs", {})
    publish = jobs.get("publish", {})

    assert publish.get("permissions") == {
        "contents": "read",
        "packages": "write",
    }
    assert publish.get("env", {}).get("IMAGE_NAME") == "ghcr.io/guchenkano/iwork"
    assert "env" not in publish["permissions"]


def test_release_ci_binding_fails_closed_on_duplicate_request_id_matches() -> None:
    """同一Commit和ci_request_id出现多个成功Run时必须拒绝发布。"""
    content = _read_release_workflow()
    verify_ci = content.split("  publish:", maxsplit=1)[0]

    assert "$successfulRuns = @($response.workflow_runs |" in verify_ci
    assert "$successfulRuns.Count -ne 1" in verify_ci
    assert "Select-Object -First 1" not in verify_ci
