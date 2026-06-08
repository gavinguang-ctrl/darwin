import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from models import RatchetState
from data_io import list_sessions
from rubric import STATIC_DIMENSIONS
from room import list_rooms, load_room
import audit

st.set_page_config(page_title="数据看板", page_icon="📊", layout="wide")
st.title("📊 数据看板")

rooms = list_rooms()
if not rooms:
    st.warning("暂无直播间。")
    st.stop()

room_options = {f"{r.name} ({r.id})": r for r in rooms}
selected = st.selectbox("选择直播间", list(room_options.keys()))
room = room_options[selected]
state = RatchetState.load(room.ratchet_state_path())
sessions = list_sessions(room.id)

if not sessions:
    st.warning("该直播间暂无数据。")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("总场次", len(sessions))
col2.metric("迭代次数", state.iteration_count)
col3.metric("锁定约束", len(state.locked_constraints))
col4.metric("跟踪指标", len(state.baselines))

# --- 指标趋势 ---
st.subheader("指标趋势")
all_keys = set()
for s in sessions:
    all_keys.update(s.metrics.keys())
metric_data = [{"场次": s.id[:15], **s.metrics} for s in sessions]
df = pd.DataFrame(metric_data)
selected_metrics = st.multiselect("选择指标", sorted(all_keys), default=sorted(all_keys)[:4])
if selected_metrics:
    fig = go.Figure()
    for m in selected_metrics:
        if m in df.columns:
            fig.add_trace(go.Scatter(x=df["场次"], y=df[m], mode="lines+markers", name=m))
    fig.update_layout(title="指标趋势", height=400)
    st.plotly_chart(fig, width='stretch')

# --- 评分趋势 ---
scored = [s for s in sessions if s.total_score > 0]
if scored:
    st.subheader("🎯 评分趋势")
    sdf = pd.DataFrame([{"场次": s.id[:15], "综合": s.total_score, "静态": s.static_total, "实效": s.effect_total} for s in scored])
    fig2 = go.Figure()
    for col in ["综合", "静态", "实效"]:
        fig2.add_trace(go.Scatter(x=sdf["场次"], y=sdf[col], mode="lines+markers", name=col))
    fig2.update_layout(title="双层评分趋势", height=400)
    st.plotly_chart(fig2, width='stretch')

    if len(scored) >= 2:
        st.subheader("雷达图对比")
        s1, s2 = scored[-2], scored[-1]
        dims = [d["name"] for d in STATIC_DIMENSIONS]
        v1 = [s1.static_scores.get(d["id"], 0) for d in STATIC_DIMENSIONS]
        v2 = [s2.static_scores.get(d["id"], 0) for d in STATIC_DIMENSIONS]
        fig3 = go.Figure()
        fig3.add_trace(go.Scatterpolar(r=v1+[v1[0]], theta=dims+[dims[0]], fill="toself", name=s1.id[:15], opacity=0.5))
        fig3.add_trace(go.Scatterpolar(r=v2+[v2[0]], theta=dims+[dims[0]], fill="toself", name=s2.id[:15]))
        fig3.update_layout(polar=dict(radialaxis=dict(range=[0, 10])), height=400)
        st.plotly_chart(fig3, width='stretch')

# --- 锁定约束 ---
if state.locked_constraints:
    st.subheader("🔒 锁定约束")
    for i, c in enumerate(state.locked_constraints, 1):
        st.write(f"{i}. **{c['element']}** — {c['reason']}")

# --- 审计日志 ---
st.subheader("📜 审计日志")
log = audit.load_log(room.id)
st.dataframe(log) if log else st.info("暂无记录")

# --- 导出 ---
st.divider()
col_a, col_b = st.columns(2)
with col_a:
    if st.button("导出场次数据"):
        export = [s.to_dict() for s in sessions]
        st.download_button("下载", json.dumps(export, ensure_ascii=False, indent=2), f"{room.name}_场次数据.json")
with col_b:
    if st.button("导出棘轮状态"):
        st.download_button("下载", json.dumps(state.to_dict(), ensure_ascii=False, indent=2), f"{room.name}_棘轮状态.json")
