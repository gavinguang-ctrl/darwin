"""TikTok 直播录制 — 自包含版（复刻蒸馏用）。

仅依赖 username + 输出路径，不依赖任何数据模型。
通过 streamlink + ffmpeg 把直播音频录成 mp3。
"""
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_active: dict[str, subprocess.Popen] = {}
_paths: dict[str, Path] = {}
_start_times: dict[str, datetime] = {}

_python = sys.executable


def check_live(username: str) -> bool:
    """检测 TikTok 用户是否正在直播。"""
    try:
        result = subprocess.run(
            [_python, "-m", "streamlink",
             f"https://www.tiktok.com/@{username}/live", "best", "--json"],
            capture_output=True, text=True, timeout=20,
        )
        return result.returncode == 0 and '"url"' in result.stdout
    except Exception:
        return False


def start_capture(username: str, output_path: Path) -> Path:
    """开始录制指定用户的直播到 output_path。"""
    if username in _active:
        raise RuntimeError(f"@{username} 正在录制中")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://www.tiktok.com/@{username}/live"
    proc = subprocess.Popen(
        f'"{_python}" -m streamlink "{url}" best -O 2>nul | '
        f'ffmpeg -i pipe:0 -vn -acodec libmp3lame -ab 128k "{output_path}" -y',
        shell=True,
    )
    _active[username] = proc
    _paths[username] = output_path
    _start_times[username] = datetime.now()

    # 后台线程：开播后至少录2分钟，之后每60秒检测下播，下播自动停止
    def _watch():
        time.sleep(120)
        while username in _active:
            if not check_live(username):
                time.sleep(30)
                if not check_live(username):
                    stop_capture(username)
                    return
            time.sleep(60)

    threading.Thread(target=_watch, daemon=True).start()
    return output_path


def stop_capture(username: str) -> Path | None:
    """停止录制，返回已录制的音频路径。"""
    proc = _active.pop(username, None)
    path = _paths.pop(username, None)
    _start_times.pop(username, None)
    if proc is None:
        return None
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    return path


def is_capturing(username: str) -> bool:
    proc = _active.get(username)
    if proc is None:
        return False
    if proc.poll() is not None:
        _active.pop(username, None)
        return False
    return True


def get_capture_info(username: str) -> dict | None:
    if username not in _active:
        return None
    start = _start_times.get(username)
    path = _paths.get(username)
    elapsed = (datetime.now() - start).total_seconds() if start else 0
    return {
        "start_time": start.isoformat() if start else "",
        "elapsed_seconds": int(elapsed),
        "audio_path": str(path) if path else "",
    }
