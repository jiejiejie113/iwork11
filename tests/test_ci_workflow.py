"""GitHub Actions纯CI工作流安全契约测试。"""

import re
from pathlib import Path

import yaml


# ======
# CI文件路径配置
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PR_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci-pr.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile"
PRODUCTION_LOCK_PATH = ROOT / "requirements-prod.lock"


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


def _read_pr_workflow() -> str:
    """读取PR轻量检查工作流文本。

    Returns:
        str: PR轻量检查工作流完整文本。
    """
    return PR_WORKFLOW_PATH.read_text(encoding="utf-8")


def _read_dockerfile() -> str:
    """读取生产镜像构建文件。

    Returns:
        str: Dockerfile完整文本。
    """
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _read_production_lock() -> str:
    """读取生产依赖锁定文件。

    Returns:
        str: 生产依赖锁文件完整文本。
    """
    return PRODUCTION_LOCK_PATH.read_text(encoding="utf-8")


def test_production_dockerfile_uses_digest_and_hashed_lock() -> None:
    """生产镜像必须固定基础镜像并通过哈希锁安装依赖。"""
    content = _read_dockerfile()

    assert re.search(r"(?m)^FROM python:3\.11-slim@sha256:[0-9a-f]{64}\s*$", content)
    assert 'test "$ID" = "debian"' in content
    assert 'test "$VERSION_CODENAME" = "trixie"' in content
    assert "COPY requirements-prod.lock ." in content
    assert "pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-prod.lock" in content
    assert "COPY requirements.txt" not in content
    assert "-r requirements.txt" not in content


def test_production_dockerfile_pins_source_build_backend() -> None:
    """源码包构建不得在隔离环境中解析未锁定的构建后端。"""
    dockerfile = _read_dockerfile()
    lock = _read_production_lock()

    assert "--no-build-isolation" in dockerfile
    assert re.search(r"(?m)^setuptools==[0-9][^\\s]* \\\s*$", lock)


def test_production_dockerfile_uses_snapshot_apt_without_recommends() -> None:
    """生产镜像的Debian输入必须固定快照并禁止安装推荐包。"""
    content = _read_dockerfile()

    assert re.search(r"(?m)^ARG DEBIAN_SNAPSHOT=\d{8}T\d{6}Z\s*$", content)
    assert "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" in content
    assert "snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}" in content
    assert "apt-get install -y --no-install-recommends --no-install-suggests" in content
    assert re.search(r"apt-get(?:\s+-o [^\n;]+)? update", content)


def test_production_lock_has_exact_versions_hashes_and_no_dev_tools() -> None:
    """生产依赖锁必须是精确版本哈希，并排除开发及桌面打包依赖。"""
    content = _read_production_lock()
    package_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "--"))
    ]

    assert package_lines
    assert all("==" in line for line in package_lines)
    assert not re.search(r"(?:>=|<=|~=|>|<)", content)
    assert re.search(r"--hash=sha256:[0-9a-f]{64}", content)
    assert not re.search(
        r"(?im)^(?:pytest(?:-asyncio)?|pyinstaller|customtkinter)==",
        content,
    )


def test_production_lock_excludes_linux_irrelevant_windows_only_packages() -> None:
    """Linux生产镜像不得把Windows条件依赖固化成无条件安装。"""
    content = _read_production_lock()

    assert not re.search(r"(?im)^(?:colorama|win32-setctime)==", content)


def test_production_build_inputs_have_stable_text_bytes() -> None:
    """生产构建锁和Dockerfile必须固定为LF，避免跨平台字节漂移。"""
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "Dockerfile text eol=lf" in attributes
    assert "requirements-prod.in text eol=lf" in attributes
    assert "requirements-prod.lock text eol=lf" in attributes


def test_ci_workflow_is_manual_only_and_keeps_request_id() -> None:
    """完整CI只能手工触发，并保留请求关联ID输入。"""
    content = _read_workflow()

    assert "  push:" not in content
    assert "  pull_request:" not in content
    assert "  workflow_dispatch:" in content
    assert "request_id:" in content
    assert "iwork ci · ${{ inputs.request_id }} · ${{ github.sha }}" in content
    assert "group: iwork-ci-${{ github.sha }}" in content
    assert "cancel-in-progress: false" in content


def test_ci_pr_workflow_is_a_pinned_lightweight_pull_request_gate() -> None:
    """PR轻量Workflow只能做托管Runner静态检查，不得触碰生产或发布。"""
    content = _read_pr_workflow()
    lowered = content.lower()
    action_uses = re.findall(r"uses:\s+[^\s]+@([^\s]+)", content)

    assert "pull_request:" in content
    assert "      - Keycloak" in content
    assert "runs-on: ubuntu-latest" in content
    assert "contents: read" in content
    assert "requirements-ci.txt" in content
    assert "python -m ruff check --no-cache" in content
    assert action_uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in action_uses)

    for forbidden in (
        "push:",
        "workflow_dispatch:",
        "pull_request_target",
        "self-hosted",
        "docker login",
        "docker push",
        "docker compose up",
        "ghcr.io",
        "dkt-secrets.env",
        "production.env",
        "secrets.",
        "ssh ",
    ):
        assert forbidden not in lowered


def test_ci_workflow_is_hosted_and_cannot_touch_production() -> None:
    """CI只能使用GitHub托管Runner，且不得包含任何生产部署入口。"""
    content = _read_workflow()
    lowered = content.lower()

    assert "runs-on: windows-latest" in content
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
    """CI必须固定Action提交，并执行代码、迁移、配置和脚本检查。"""
    content = _read_workflow()
    action_uses = re.findall(r"uses:\s+[^\s]+@([^\s]+)", content)

    assert action_uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in action_uses)
    assert "contents: read" in content
    assert "python -m pytest tests/ -q" in content
    assert "python -m ruff check --no-cache" in content
    assert "--ignore E402,W292 iwork" in content
    assert "docker compose --env-file env/local.env config --quiet" in content
    assert "docker build" not in content
    assert "  build:" not in content
    assert "${GITHUB_SHA}" not in content
    assert "request_id:" in content
    assert "required: true" in content
    assert "inputs.request_id || github.run_id" not in content
    assert "inputs.request_id || github.sha" not in content
    assert "IWORK_REQUEST_ID=" in content
    assert "GITHUB_REPOSITORY -cne 'GuChenkano/iwork'" in content
    assert "GITHUB_REF -cne 'refs/heads/Keycloak'" in content
    assert "GITHUB_STEP_SUMMARY" in content


def test_ci_test_job_preserves_non_secret_environment_profiles() -> None:
    """测试Job必须在不读取生产密钥的情况下校验Compose配置。"""
    content = _read_workflow()
    test_job = content[content.index("  test:"):]

    assert "Get-ChildItem -Path . -Recurse" not in test_job
    assert "Remove-Item -LiteralPath .env -Force" in test_job
    assert "docker compose --env-file env/local.env config --quiet" in test_job
    assert "IWORK_DJANGO_SECRET_KEY: ci-only-django-secret" in test_job
    assert "IWORK_APP_DB_PASSWORD: ci-only-app-password" in test_job
    assert "IWORK_DB_PASSWORD: ci-only-read-password" in test_job


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
    assert "Invoke-WebRequest -UseBasicParsing -Method Head" in content
    assert "Docker-Content-Digest" in content
    assert "statusCode -eq 404" in content
    assert "statusCode -in @(401, 403, 429)" in content
    assert "per_page=$perPage&page=$page" in content
    assert "[DateTimeOffset]::UtcNow" in content
    assert "duration_seconds" in content
    assert "GITHUB_RUN_ID" in content
    assert "CI_REQUEST_ID" in content
    assert '$_.event -eq "workflow_dispatch"' in content
    assert "function Get-ExactRequestId" in content
    assert 'GITHUB_REPOSITORY -cne "GuChenkano/iwork"' in content
    assert 'GITHUB_ACTOR -cne "GuChenkano"' in content
    assert "(Get-ExactRequestId -Title ([string]$_.display_title)) -ceq $env:CI_REQUEST_ID.ToLowerInvariant()" in content
    assert 'display_title).Contains($env:CI_REQUEST_ID)' not in content
    assert content.count("$startedAt = [DateTimeOffset]::UtcNow") == 1
    assert "docker push" in content
    assert "docker pull" in content
    assert "docker logout ghcr.io" in content
    assert "New-IworkProductionConfigBundle.ps1" in content
    assert 'if (-not $?) { throw "生产配置包生成失败" }' in content
    assert 'if ($LASTEXITCODE -ne 0) { throw "生产配置包生成失败" }' not in content
    assert "IWORK_IMAGE_DIGEST=" in content
    assert "IWORK_CONFIG_DIGEST=" in content
    assert "IWORK_CONFIG_ARTIFACT_DIGEST=" in content
    assert "RAW_ARTIFACT_DIGEST" in content
    assert 'sha256:$rawArtifactDigest' in content
    assert 'Artifact digest格式无效' in content
    assert "release-manifest.json" in content
    assert "IWORK_RELEASE_MANIFEST_ARTIFACT_ID" in content
    assert "IWORK_RELEASE_MANIFEST_ARTIFACT_DIGEST" in content
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
        "dkt-secrets.env",
        "docker compose up",
        "deploy.ps1",
        "ssh ",
        "192.168.0.97",
    ):
        assert forbidden not in lowered


def test_release_ghcr_head_accepts_index_and_single_manifest_media_types() -> None:
    """GHCR HEAD 查询必须兼容索引和两种单镜像 Manifest。"""
    content = _read_release_workflow()
    head_block = content[content.index("function Get-RemoteDigest"):content.index("function Invoke-LocalImageSmoke")]

    assert "application/vnd.oci.image.index.v1+json" in head_block
    assert "application/vnd.docker.distribution.manifest.list.v2+json" in head_block
    assert "application/vnd.oci.image.manifest.v1+json" in head_block
    assert "application/vnd.docker.distribution.manifest.v2+json" in head_block


def test_release_reused_image_requires_repository_source_label() -> None:
    """复用已有 Digest 时必须同时绑定 OCI source 与当前仓库。"""
    content = _read_release_workflow()
    revision_block = content[content.index("function Assert-ImageRevision"):content.index("$digest = Get-RemoteDigest")]

    assert "org.opencontainers.image.source" in revision_block
    assert '$expectedSource = "https://github.com/$env:GITHUB_REPOSITORY"' in revision_block
    assert "$actualSource -cne $expectedSource" in revision_block
    assert "source label" in revision_block.lower()


def test_release_existing_sha_tag_fails_closed_without_trusted_provenance() -> None:
    """已有 SHA 标签缺少可信历史 Manifest/Artifact 时必须拒绝复用。"""
    content = _read_release_workflow()
    reuse_start = content.index("if ($digest) {")
    reuse_end = content.index("else {", reuse_start)
    reuse_block = content[reuse_start:reuse_end]

    assert "throw" in reuse_block
    assert "可信" in reuse_block
    assert "Manifest" in reuse_block
    assert "Artifact" in reuse_block
    assert "Assert-ImageRevision" not in reuse_block
    assert "Invoke-LocalImageSmoke" not in reuse_block


def test_release_manifest_requires_detached_asymmetric_signature() -> None:
    """Release Manifest必须生成可由生产端独立验证的非对称签名。"""
    content = _read_release_workflow()
    manifest_block = content[content.index("生成独立Release Manifest"):content.index("发布独立Release Manifest Artifact")]

    assert "IWORK_RELEASE_MANIFEST_SIGNING_PRIVATE_KEY_PEM" in manifest_block
    assert "IWORK_RELEASE_MANIFEST_SIGNING_KEY_ID" in manifest_block
    assert "signature_algorithm" in manifest_block
    assert "signature_key_id" in manifest_block
    assert "RSASignaturePadding]::Pkcs1" in manifest_block
    assert "SignData" in manifest_block
    assert "release-manifest.sig" in manifest_block
    assert "manifest_artifact_name" in manifest_block
    assert "IWORK_RELEASE_MANIFEST_SIGNING_PRIVATE_KEY_PEM" not in content[content.index("记录Manifest Artifact与稳定机器证据"):]
    assert "Remove-Item Env:IWORK_RELEASE_MANIFEST_SIGNING_PRIVATE_KEY_PEM" in manifest_block
    assert "$ErrorActionPreference = 'Stop'" in content[content.index("清除临时构建上下文中的敏感文件"):content.index("使用短期令牌登录GHCR")]


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


def test_release_resolves_runner_temp_at_step_runtime() -> None:
    """Release不能在Job级表达式中使用仅步骤可用的runner上下文。"""
    workflow = yaml.safe_load(_read_release_workflow())
    publish = workflow.get("jobs", {}).get("publish", {})

    assert "CONFIG_SOURCE_PATH" not in publish.get("env", {})
    assert "${{ runner.temp }}" not in _read_release_workflow()
    assert "$env:RUNNER_TEMP" in _read_release_workflow()


def test_release_ci_binding_fails_closed_on_duplicate_request_id_matches() -> None:
    """同一Commit和ci_request_id出现多个成功Run时必须拒绝发布。"""
    content = _read_release_workflow()
    verify_ci = content.split("  publish:", maxsplit=1)[0]

    assert "$successfulRuns = @($response.workflow_runs |" in verify_ci
    assert "$successfulRuns.Count -ne 1" in verify_ci
    assert "Select-Object -First 1" not in verify_ci


def test_release_manifest_uses_verified_ci_job_outputs() -> None:
    """Manifest必须引用verify-ci Job输出，不能读取publish Job不存在的steps上下文。"""
    content = _read_release_workflow()

    assert "CI_RUN_ID: ${{ needs.verify-ci.outputs.run_id }}" in content
    assert "CI_RUN_ATTEMPT: ${{ needs.verify-ci.outputs.run_attempt }}" in content
    assert "CI_REQUEST_ID: ${{ needs.verify-ci.outputs.ci_request_id }}" in content
    assert "CI_RUN_ID: ${{ steps.ci.outputs.run_id }}" not in content
    assert "CI_RUN_ATTEMPT: ${{ steps.ci.outputs.run_attempt }}" not in content
    assert "CI_REQUEST_ID: ${{ steps.ci.outputs.ci_request_id }}" not in content
