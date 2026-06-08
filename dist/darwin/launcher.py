"""Darwin launcher — entry point for PyInstaller packaged app."""
import sys
import os
import subprocess
from pathlib import Path


def get_app_dir():
    """Get the application directory (works both in dev and packaged mode)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_data_dir():
    """Get writable data directory (next to the exe, not inside _MEIPASS)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def main():
    os.environ["PYTHONUTF8"] = "1"
    app_dir = get_app_dir()
    data_dir = get_data_dir()

    # Ensure config.json exists
    config_file = data_dir / "config.json"
    if not config_file.exists():
        example = app_dir / "config.example.json"
        if example.exists():
            import shutil
            shutil.copy2(example, config_file)
            print(f"已创建 config.json，请编辑填入 API Keys 后重新启动。")
            print(f"配置文件位置: {config_file}")
            input("按回车键退出...")
            return

    # Ensure data directories exist
    (data_dir / "data" / "rooms").mkdir(parents=True, exist_ok=True)
    (data_dir / "data" / "tasks").mkdir(parents=True, exist_ok=True)

    # Set working directory
    os.chdir(str(data_dir))

    # Launch streamlit
    streamlit_script = app_dir / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(streamlit_script),
        "--server.port", "8501",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]

    print("=" * 50)
    print("  🧬 达尔文 — TikTok 直播脚本棘轮优化系统")
    print("=" * 50)
    print(f"\n  浏览器访问: http://localhost:8501")
    print(f"  按 Ctrl+C 停止服务\n")

    try:
        proc = subprocess.run(cmd, cwd=str(data_dir))
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
