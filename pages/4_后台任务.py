import streamlit as st
from task_manager import list_tasks, request_stop, force_stop, cleanup_dead

st.set_page_config(page_title="后台任务", page_icon="📋", layout="wide")
st.title("📋 后台任务")

cleanup_dead(None)
all_tasks = list_tasks()

if not all_tasks:
    st.info("暂无后台任务")
else:
    running = [t for t in all_tasks if t.status == "running"]
    done = [t for t in all_tasks if t.status != "running"]

    if running:
        st.subheader(f"运行中（{len(running)}）")
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
        import time
        time.sleep(2)
        st.rerun()

    if done:
        st.subheader(f"历史（{len(done)}）")
        for t in done[:30]:
            icon = {"completed": "✅", "stopped": "⏹", "failed": "❌"}.get(t.status, "?")
            with st.container(border=True):
                st.markdown(f"{icon} **{t.desc or t.op}** — {t.best_score:.1f}分")
                st.caption(f"{t.created_at[:16]} | {t.status}")
                if t.log:
                    with st.expander("日志", expanded=False):
                        for entry in t.log[-15:]:
                            st.write(entry)
