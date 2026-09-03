"""生产详情卡片 Pointer 拖拽状态机测试。"""

import json
import shutil
import subprocess


def test_card_drag_pointer_lifecycle_preserves_pending_scroll_and_supports_long_press():
    """卡片应允许长按前移动，滚动取消时清理，长按后才交换。"""
    node_executable = shutil.which("node")
    assert node_executable is not None
    result = subprocess.run(  # noqa: S603 - 仅执行PATH解析出的本机Node和仓库内固定测试脚本
        [node_executable, "tests/js/production_card_drag_harness.cjs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout) == {
        "long_press_after_move": True,
        "pending_scroll_not_prevented": True,
        "tap_does_not_activate": True,
        "pointercancel_cleans_pending": True,
    }
