import streamlit as st
from pathlib import Path
from datetime import datetime
from task_manager import list_tasks, request_stop, force_stop, cleanup_dead
from config import TASKS_DIR

st.set_page_config(page_title="后台任务", page_icon="📋", layout="wide")
st.title("📋 后台任务")

cleanup_dead(None)
all_tasks = list_tasks()

running = [t for t in all_tasks if t.status == "running"]
done = [t for t in all_tasks if t.status != "running"]


def _finished_time(task_id: str) -> str:
    """从任务文件的修改时间推断完成时间。"""
    p = TASKS_DIR / f"{task_id}.json"
    if p.exists():
        mtime = p.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    return ""


def _render_running():
    if not running:
        st.info("当前没有运行中的任务")
        return
    for t in running:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"🔄 **{t.desc or t.op}**")
                st.caption(f"{t.progress} | 最高分 {t.best_score:.1f}")
                if t.stop_requested:
                    st.warning("⏳ 已请求停止，等待当前轮次完成...")
            with c2:
                if t.stop_requested:
                    if st.button("⛔ 强制停止", key=f"force_{t.id}", type="primary"):
                        force_stop(t.id)
                        st.rerun()
                else:
                    if st.button("⏹ 停止", key=f"stop_{t.id}"):
                        request_stop(t.id)
                        st.rerun()
            if t.log:
                with st.expander("日志", expanded=False):
                    for entry in t.log[-15:]:
                        st.write(entry)


def _render_history():
    if not done:
        st.info("暂无历史任务")
        return
    for t in done[:50]:
        icon = {"completed": "✅", "stopped": "⏹", "failed": "❌"}.get(t.status, "?")
        finished = _finished_time(t.id)
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"{icon} **{t.desc or t.op}** — {t.best_score:.1f}分")
                time_info = f"创建: {t.created_at[:16]}"
                if finished:
                    time_info += f" → 完成: {finished}"
                st.caption(f"{time_info} | {t.status}")
            with c2:
                if t.room_id:
                    if st.button("🔧 棘轮分析", key=f"goto_{t.id}"):
                        st.session_state["goto_room_id"] = t.room_id
                        st.switch_page("pages/2_棘轮分析.py")
            if t.log:
                with st.expander("日志", expanded=False):
                    for entry in t.log[-15:]:
                        st.write(entry)


if not all_tasks:
    st.info("暂无后台任务")
elif running:
    if st.button("🔄 刷新状态", key="refresh_tasks"):
        st.rerun()
    tab_running, tab_history = st.tabs([f"运行中（{len(running)}）", f"历史任务（{len(done)}）"])
    with tab_running:
        _render_running()
    with tab_history:
        _render_history()
else:
    _render_history()
