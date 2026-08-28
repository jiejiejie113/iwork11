"""生产配置包生成器的行为契约测试。"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


# ======
# 测试路径和固定输入配置
ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "New-IworkProductionConfigBundle.ps1"
IMAGE_DIGEST = "sha256:" + "a" * 64
SOURCE_COMMIT = "4cb8e31188a0022ea5441e1e10490adc4cc8ad8a"


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


def test_generator_is_directly_parseable_by_windows_powershell_51() -> None:
    """声明兼容5.1的脚本必须带UTF-8 BOM，避免中文内容破坏解析。"""
    assert SCRIPT_PATH.read_bytes().startswith(b"\xef\xbb\xbf")


def _run_generator(source_root: Path, output_directory: Path) -> subprocess.CompletedProcess[str]:
    """调用生产配置包生成脚本。

    Args:
        source_root (Path): 包含源配置文件的目录。
        output_directory (Path): 目标配置包目录。

    Returns:
        subprocess.CompletedProcess[str]: PowerShell 执行结果。
    """
    return subprocess.run(  # noqa: S603 - 可执行文件和参数均由测试固定构造
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
            "-SourceCommit",
            SOURCE_COMMIT,
            "-ImageDigest",
            IMAGE_DIGEST,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _write_source(source_root: Path, *, production_env: bytes = b"DKT_ENVIRONMENT=production\n") -> None:
    """写入测试所需的最小生产配置源文件。

    Args:
        source_root (Path): 配置源目录。
        production_env (bytes): 生产环境文件原始字节。
    """
    (source_root / "env").mkdir(parents=True)
    compose = b"services:\r\n  iwork:\r\n    image: example/iwork@sha256:" + b"a" * 64 + b"\r\n"
    (source_root / "docker-compose.yml").write_bytes(b"\xef\xbb\xbf" + compose)
    (source_root / "env" / "production.env").write_bytes(b"\xef\xbb\xbf" + production_env)


def test_generator_creates_verifiable_minimal_bundle(tmp_path: Path) -> None:
    """生成目录型配置包，并写入不自引用的可复验清单。"""
    source_root = tmp_path / "source"
    output_directory = tmp_path / "bundle"
    (source_root / "env").mkdir(parents=True)
    compose = "services:\n  iwork:\n    image: ghcr.io/guchenkano/iwork@" + IMAGE_DIGEST + "\n"
    production_env = "DKT_ENVIRONMENT=production\nDJANGO_DEBUG=False\n"
    (source_root / "docker-compose.yml").write_text(compose, encoding="utf-8", newline="")
    (source_root / "env" / "production.env").write_text(
        production_env,
        encoding="utf-8",
        newline="",
    )

    result = _run_generator(source_root, output_directory)

    assert result.returncode == 0, result.stderr
    assert {
        path.relative_to(output_directory).as_posix()
        for path in output_directory.rglob("*")
        if path.is_file()
    } == {"config-manifest.json", "docker-compose.yml", "env/production.env"}
    manifest = json.loads((output_directory / "config-manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {
        "schema",
        "application",
        "source_commit",
        "image_digest",
        "compose_sha256",
        "production_env_sha256",
        "config_digest",
    }
    assert manifest["schema"] == "iwork-production-config/v1"
    assert manifest["application"] == "iwork"
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert manifest["image_digest"] == IMAGE_DIGEST
    compose_bytes = compose.encode("utf-8")
    env_bytes = production_env.encode("utf-8")
    compose_sha256 = hashlib.sha256(compose_bytes).hexdigest()
    env_sha256 = hashlib.sha256(env_bytes).hexdigest()
    assert manifest["compose_sha256"] == compose_sha256
    assert manifest["production_env_sha256"] == env_sha256
    canonical_config = (
        "schema=iwork-production-config/v1\n"
        "application=iwork\n"
        f"source_commit={SOURCE_COMMIT}\n"
        f"image_digest={IMAGE_DIGEST}\n"
        f"compose_sha256={compose_sha256}\n"
        f"production_env_sha256={env_sha256}\n"
    ).encode("utf-8")
    assert manifest["config_digest"] == "sha256:" + hashlib.sha256(canonical_config).hexdigest()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["config_digest"])
    assert "config_digest" not in (output_directory / "docker-compose.yml").read_text(encoding="utf-8")


def test_generator_normalizes_input_and_is_deterministic(tmp_path: Path) -> None:
    """不同换行表示的同一配置应生成规范化且一致的内容摘要。"""
    source_root = tmp_path / "source"
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    _write_source(source_root, production_env=b"DKT_ENVIRONMENT=production\r\n")

    first_result = _run_generator(source_root, first_output)
    second_result = _run_generator(source_root, second_output)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert (first_output / "config-manifest.json").read_bytes() == (
        second_output / "config-manifest.json"
    ).read_bytes()
    assert (first_output / "docker-compose.yml").read_bytes() == (
        second_output / "docker-compose.yml"
    ).read_bytes()
    assert (first_output / "env" / "production.env").read_bytes() == (
        second_output / "env" / "production.env"
    ).read_bytes()
    for relative_path in (
        "config-manifest.json",
        "docker-compose.yml",
        "env/production.env",
    ):
        payload = (first_output / relative_path).read_bytes()
        assert b"\r" not in payload
        assert not payload.startswith(b"\xef\xbb\xbf")


def test_generator_rejects_invalid_utf8_without_creating_output(tmp_path: Path) -> None:
    """配置源不是严格UTF-8时必须失败且不留下半成品。"""
    source_root = tmp_path / "source"
    output_directory = tmp_path / "bundle"
    _write_source(source_root)
    (source_root / "docker-compose.yml").write_bytes(b"services: \xff\n")

    result = _run_generator(source_root, output_directory)

    assert result.returncode != 0
    assert "有效 UTF-8" in result.stderr
    assert not output_directory.exists()


@pytest.mark.parametrize("key", ["DB_PASSWORD", "JWT_SECRET", "OAUTH_TOKEN", "TLS_PRIVATE_KEY"])
def test_generator_rejects_sensitive_production_environment_keys(tmp_path: Path, key: str) -> None:
    """生产环境文件出现敏感键时不得留下任何配置包。"""
    source_root = tmp_path / "source"
    output_directory = tmp_path / "bundle"
    _write_source(source_root, production_env=f"{key}=not-a-real-secret\n".encode("utf-8"))

    result = _run_generator(source_root, output_directory)

    assert result.returncode != 0
    assert not output_directory.exists()
    assert "敏感键" in result.stderr


def test_generator_rejects_plaintext_secret_values_in_compose(tmp_path: Path) -> None:
    """Compose中敏感变量只能引用运行时环境，不能携带明文值。"""
    source_root = tmp_path / "source"
    output_directory = tmp_path / "bundle"
    _write_source(source_root)
    (source_root / "docker-compose.yml").write_text(
        "services:\n"
        "  iwork:\n"
        "    environment:\n"
        "      DJANGO_SECRET_KEY: plaintext-not-allowed\n",
        encoding="utf-8",
        newline="",
    )

    result = _run_generator(source_root, output_directory)

    assert result.returncode != 0
    assert not output_directory.exists()
    assert "Compose禁止包含敏感明文" in result.stderr


def test_generator_never_overwrites_existing_output(tmp_path: Path) -> None:
    """已有目标目录即使包含额外文件也必须拒绝，且不得改写它。"""
    source_root = tmp_path / "source"
    output_directory = tmp_path / "bundle"
    _write_source(source_root)
    output_directory.mkdir()
    sentinel = output_directory / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = _run_generator(source_root, output_directory)

    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (output_directory / "config-manifest.json").exists()


def test_generator_rejects_explicit_parent_path_segment(tmp_path: Path) -> None:
    """入口目录包含父级跳转段时必须拒绝，而不是先规范化后写出。"""
    source_root = tmp_path / "source"
    _write_source(source_root)

    result = _run_generator(source_root, tmp_path / "nested" / ".." / "bundle")

    assert result.returncode != 0
    assert "父级跳转" in result.stderr
    assert not (tmp_path / "bundle").exists()


def test_generator_rejects_missing_output_parent(tmp_path: Path) -> None:
    """输出目录父级不存在时必须失败，避免隐式创建未知路径。"""
    source_root = tmp_path / "source"
    _write_source(source_root)
    output_directory = tmp_path / "missing-parent" / "bundle"

    result = _run_generator(source_root, output_directory)

    assert result.returncode != 0
    assert "父级不存在" in result.stderr
    assert not output_directory.exists()
