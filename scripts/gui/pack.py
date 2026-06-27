"""
PyInstaller 打包脚本
用法: python pack.py
"""

import subprocess
import sys
from pathlib import Path


def main():
    gui_dir = Path(__file__).parent
    main_file = gui_dir / "main.py"
    script_dir = gui_dir.parent
    icon_file = gui_dir / "icon.ico"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "pytckreg3导出工具",
        "--add-data", f"{script_dir / 'export_pytckreg3.py'};.",
        str(main_file),
    ]

    if icon_file.exists():
        cmd.insert(4, f"--icon={icon_file}")

    print(f"执行: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("打包完成，输出目录: dist/")


if __name__ == "__main__":
    main()
