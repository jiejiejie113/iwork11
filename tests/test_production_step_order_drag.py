"""生产详情工序顺序拖拽状态机测试。"""

import json
import shutil
import subprocess


def test_step_order_drag_pointer_lifecycle_and_storage():
    """工序手柄应支持排序、详情隔离、缓存和列表边缘自动滚动。"""
    node_executable = shutil.which("node")
    assert node_executable is not None
    result = subprocess.run(  # noqa: S603 - 仅执行PATH解析出的本机Node和固定测试脚本
        [node_executable, "tests/js/production_step_order_drag_harness.cjs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout) == {
        "default_numeric_order": True,
        "cache_normalization": True,
        "detail_isolation": True,
        "handle_drag_saves_order": True,
        "filtered_hidden_steps_preserved": True,
        "pointercancel_restores_state": True,
        "edge_scroll_preserves_drag": True,
    }
