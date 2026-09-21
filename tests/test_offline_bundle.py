"""离线（不依赖 Git）运行包生成器的行为契约测试。"""

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest


# ======
# 测试路径与固定断言
ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "New-IworkOfflineBundle.ps1"

EXPECTED_ENTRIES = (
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    "start.sh",
    "entrypoint.sh",
    "manage.py",
    "requirements-prod.lock",
    "deploy.ps1",
    "env/local.env",
    "env/production.env",
    "iwork/settings.py",
    "iwork/asgi.py",
    "MANIFEST.sha256",
    "logs/.keep",
    "sqlite/.keep",
)

FORBIDDEN_EXACT_ENTRIES = (
    "iwork/.env",
    "iwork/local_dev_settings.py",
    "dkt-secrets.env",
)

FORBIDDEN_FRAGMENTS = (
    ".git/",
    ".venv/",
    "venv311/",
    "__pycache__/",
    ".pytest_cache/",
    "local_dev_db/",
)


def _powershell() -> str:
    """查找可用的 PowerShell 可执行文件。

    Returns:
        str: PowerShell 可执行文件路径。

    Raises:
        pytest.skip.Exception: 当前环境没有可用的 PowerShell。
    """
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("当前环境没有可用的 PowerShell")
    return executable


def _run_bundler(source_root: Path, output_directory: Path) -> subprocess.CompletedProcess[str]:
    """调用离线包生成脚本。

    Args:
        source_root (Path): 打包源目录。
        output_directory (Path): 离线包输出目录。

    Returns:
        subprocess.CompletedProcess[str]: PowerShell 执行结果。
    """
    return subprocess.run(  # noqa: S603 - 可执行文件与参数均由测试固定构造
        [
            _powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PATH),
            "-SourceRoot",
            str(source_root),
            "-OutputDirectory",
            str(output_directory),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )


def test_offline_bundle_script_is_directly_parseable_by_windows_powershell_51() -> None:
    """声明兼容5.1的脚本必须带UTF-8 BOM，避免中文内容破坏解析。"""
    assert SCRIPT_PATH.read_bytes().startswith(b"\xef\xbb\xbf")


def test_offline_bundle_contains_runtime_files_and_excludes_sensitive_content(tmp_path: Path) -> None:
    """离线包应包含运行所需文件，并排除版本库、虚拟环境、缓存与密钥文件。"""
    output_directory = tmp_path / "dist"

    result = _run_bundler(ROOT, output_directory)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["Status"] == "created"
    assert payload["FileCount"] > 100
    bundle_path = Path(payload["Bundle"])
    assert bundle_path.is_file()
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert payload["BundleSha256"] == bundle_hash
    assert payload["ManifestEntries"] == payload["FileCount"]

    with zipfile.ZipFile(bundle_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist()]
        for expected in EXPECTED_ENTRIES:
            assert expected in names, f"离线包缺少运行文件: {expected}"
        for forbidden in FORBIDDEN_EXACT_ENTRIES:
            assert forbidden not in names, f"离线包不得包含: {forbidden}"
        for forbidden in FORBIDDEN_FRAGMENTS:
            assert not any(forbidden in name for name in names), (
                f"离线包不得包含: {forbidden}"
            )
        manifest_text = archive.read("MANIFEST.sha256").decode("utf-8")
        manifest_lines = [line for line in manifest_text.splitlines() if line.strip()]
        assert len(manifest_lines) >= payload["FileCount"] - 1
        for line in manifest_lines:
            digest, _, relative_path = line.partition("  ")
            assert len(digest) == 64 and relative_path
            int(digest, 16)
            assert "\\" not in relative_path, "清单路径必须使用正斜杠"
            assert relative_path in names, f"清单路径不在压缩包内: {relative_path}"
            assert (
                hashlib.sha256(archive.read(relative_path)).hexdigest() == digest
            ), f"清单哈希不一致: {relative_path}"


def test_offline_bundle_fails_closed_when_required_runtime_files_are_missing(
    tmp_path: Path,
) -> None:
    """缺少运行必需文件时必须失败关闭，不得生成看似可用的离线包。"""
    incomplete_root = tmp_path / "incomplete"
    incomplete_root.mkdir()
    (incomplete_root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    result = _run_bundler(incomplete_root, tmp_path / "dist")

    assert result.returncode != 0
    assert not list((tmp_path / "dist").glob("iwork-offline-*.zip"))
