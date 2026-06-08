import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
from config import TASKS_DIR
from models import BackgroundTask


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def save_task(task: BackgroundTask):
    p = _task_path(task.id)
    p.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_task(task_id: str) -> BackgroundTask | None:
    p = _task_path(task_id)
    if not p.exists():
        return None
    return BackgroundTask.from_dict(json.loads(p.read_text(encoding="utf-8")))


def list_tasks(room_id: str | None = None, status: str | None = None) -> list[BackgroundTask]:
    tasks = []
    for f in TASKS_DIR.glob("*.json"):
        try:
            t = BackgroundTask.from_dict(json.loads(f.read_text(encoding="utf-8")))
            if room_id and t.room_id != room_id:
                continue
            if status and t.status != status:
                continue
            tasks.append(t)
        except Exception:
            continue
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


def request_stop(task_id: str):
    t = load_task(task_id)
    if t and t.status == "running":
        t.stop_requested = True
        save_task(t)


def force_stop(task_id: str):
    """强制终止：杀进程 + 标记 stopped"""
    import platform
    t = load_task(task_id)
    if not t:
        return
    if t.pid:
        try:
            if platform.system() == "Windows":
                import subprocess
                subprocess.run(["taskkill", "/F", "/PID", str(t.pid)],
                               capture_output=True, timeout=5)
            else:
                import signal
                os.kill(t.pid, signal.SIGTERM)
        except Exception:
            pass
    t.status = "stopped"
    t.log.append("用户强制停止")
    save_task(t)


def update_progress(task_id: str, progress: str, best_score: float = None, log_entry: str = None):
    t = load_task(task_id)
    if not t:
        return
    t.progress = progress
    if best_score is not None:
        t.best_score = best_score
    if log_entry:
        t.log.append(log_entry)
    save_task(t)


def finish_task(task_id: str, status: str, result: dict = None):
    t = load_task(task_id)
    if not t:
        return
    t.status = status
    if result:
        t.result = result
    save_task(t)


def is_stop_requested(task_id: str) -> bool:
    t = load_task(task_id)
    return t.stop_requested if t else True


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive (cross-platform)."""
    import platform
    if platform.system() == "Windows":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def is_running(task_id: str) -> bool:
    t = load_task(task_id)
    if not t or t.status != "running":
        return False
    if t.pid:
        return _pid_alive(t.pid)
    return False


def cleanup_dead(room_id: str | None = None):
    for t in list_tasks(room_id=room_id, status="running"):
        if t.pid and not is_running(t.id):
            t.status = "failed"
            t.log.append("进程异常退出")
            save_task(t)


def create_task(room_id: str, op: str, params: dict, desc: str = "") -> BackgroundTask:
    import uuid
    task = BackgroundTask(
        id=uuid.uuid4().hex[:10],
        room_id=room_id,
        op=op,
        params=params,
        desc=desc,
        created_at=datetime.now().isoformat(),
    )
    save_task(task)
    worker = Path(__file__).parent / "task_worker.py"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(worker), task.id],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    task.pid = proc.pid
    save_task(task)
    return task
