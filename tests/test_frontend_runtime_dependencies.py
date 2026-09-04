"""iwork 页面运行时依赖与脚本失败降级测试。"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE_PATHS = [
    ROOT / "iwork" / "templates" / "iwork" / "dashboard.html",
    ROOT / "iwork" / "templates" / "iwork" / "production_detail.html",
    ROOT / "iwork" / "templates" / "iwork" / "today_targets.html",
]
RUNTIME_PAGE_PATHS = [
    *PAGE_PATHS,
    ROOT / "iwork" / "templates" / "iwork" / "kanban.html",
]
EXPECTED_RUNTIME_ASSETS = {
    "iwork/vendor/tailwindcss.cdn.js",
    "iwork/vendor/vue.global.prod.js",
}
EXPECTED_VENDOR_SHA256 = {
    "tailwindcss.cdn.js": "176e894661aa9cdc9a5cba6c720044cbbf7b8bd80d1c9a142a7c24b1b6c50d15",
    "chart.umd.min.js": "48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a",
    "vue.global.prod.js": "aae6339a0e744cc3503f2a3ae63f5ee0d99ce39f45517e7a51fcb9ecc290ca2c",
}


def _script_sources(template: str) -> list[str]:
    """提取页面中的脚本地址。"""
    return re.findall(r'<script\s+src="([^"]+)"', template)


def test_iwork_pages_use_local_runtime_assets_instead_of_public_cdns():
    """页面不能因公网 CDN 不可达而阻断 Vue 挂载。"""
    for path in RUNTIME_PAGE_PATHS:
        template = path.read_text(encoding="utf-8")
        sources = _script_sources(template)
        assert not [source for source in sources if source.startswith(("http://", "https://"))]
        assert EXPECTED_RUNTIME_ASSETS <= set(
            source.removeprefix("{% static '").removesuffix("' %}")
            for source in sources
        )
        assert "iwork/vendor/vue.global.prod.js" in template
        if path in PAGE_PATHS:
            assert template.index("runtime_guard.js") < template.index("vue.global.prod.js")


def test_iwork_pages_hide_unmounted_app_and_show_runtime_error():
    """脚本加载失败时应显示明确错误，而不是永久显示加载中。"""
    for path in PAGE_PATHS:
        template = path.read_text(encoding="utf-8")
        assert 'id="iwork-runtime-error"' in template
        assert re.search(r'<div id="app"[^>]*v-cloak', template)
        assert "runtime_guard.js" in template


def test_pinned_vendor_assets_exist_with_expected_digests():
    """本地运行时依赖必须是已核验的固定版本文件。"""
    vendor_root = ROOT / "static" / "iwork" / "vendor"
    for name, expected_digest in EXPECTED_VENDOR_SHA256.items():
        asset = vendor_root / name
        assert asset.is_file()
        actual_digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        assert actual_digest == expected_digest


def test_pinned_vendor_assets_are_served_by_the_application(client):
    """应用静态路由必须能返回页面所需的固定运行时文件。"""
    for name in EXPECTED_VENDOR_SHA256:
        response = client.get(f"/static/iwork/vendor/{name}")
        assert response.status_code == 200
        body = b"".join(response.streaming_content)
        assert hashlib.sha256(body).hexdigest() == EXPECTED_VENDOR_SHA256[name]


def test_kanban_page_renders_local_runtime_assets(client):
    """产量看板模板也必须能渲染固定的本地运行时地址。"""
    response = client.get("/kanban/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "https://cdn.tailwindcss.com" not in body
    assert "https://unpkg.com/vue@3" not in body
    assert "/iwork/static/iwork/vendor/tailwindcss.cdn.js" in body
    assert "/iwork/static/iwork/vendor/vue.global.prod.js" in body


def test_runtime_guard_hides_broken_app_and_recovers_after_vue_mount():
    """运行时守卫在脚本失败和 Vue 正常挂载两种状态下都应切换正确。"""
    node_executable = shutil.which("node")
    assert node_executable is not None
    result = subprocess.run(  # noqa: S603 - 仅执行 PATH 解析出的本机 Node 和仓库内固定测试脚本
        [node_executable, "tests/js/runtime_guard_harness.cjs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["failed"] == {"app_hidden": True, "error_hidden": False}
    assert payload["recovered"] == {"app_hidden": False, "error_hidden": True}
