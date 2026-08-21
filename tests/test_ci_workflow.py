"""GitHub Actions纯CI工作流安全契约测试。"""

import re
from pathlib import Path


# ======
# CI文件路径配置
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"


def _read_workflow() -> str:
    """读取CI工作流文本。

    Returns:
        str: CI工作流完整文本。
    """
    return WORKFLOW_PATH.read_text(encoding="utf-8")


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


def test_ci_test_job_preserves_non_secret_environment_profiles() -> None:
    """测试Job必须保留供安全契约测试读取的无密钥环境配置模板。"""
    content = _read_workflow()
    test_job = content.split("  build:", maxsplit=1)[0]

    assert "Get-ChildItem -Path . -Recurse" not in test_job
    assert "Remove-Item -LiteralPath .env -Force" in test_job
