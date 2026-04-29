import streamlit as st
from datetime import datetime
from config import DEFAULT_METRICS
from models import Session
from data_io import (new_session_id, save_session, list_sessions,
                     parse_metrics_from_excel, parse_metrics_from_json, parse_metrics_from_csv)
from room import create_room, list_rooms, load_room
from zmeng_api import fetch_live_data, extract_script_from_excel, fetch_host_rooms
from task_manager import request_stop, list_tasks, cleanup_dead
from ui_helpers import import_sessions_from_api, scorer_selector, launch_batch_score
import time as _time

st.set_page_config(page_title="直播间管理", page_icon="🏠", layout="wide")
st.title("🏠 直播间管理")

tabs = st.tabs(["新建直播间", "添加场次", "管理直播间"])


def _api_search_import_ui(room, prefix):
    api_host = st.text_input("主播ID（hostName）", placeholder="例：cottondaylive1", key=f"{prefix}_host")
    dc1, dc2 = st.columns(2)
    with dc1:
        api_date = st.date_input("起始日期", value=None if prefix == "imp_api" else datetime.now().date(),
                                 key=f"{prefix}_date")
    with dc2:
        api_end_date = st.date_input("结束日期（留空=至今）", value=None, key=f"{prefix}_end_date")
    if prefix == "imp_api":
        st.caption("起始日期留空则导入全部场次")
    if api_host and st.button("🔍 搜索", type="primary", key=f"{prefix}_search"):
        with st.spinner(f"搜索 {api_host}..."):
            rooms_data = fetch_host_rooms(api_host,
                                          start_date=str(api_date) if api_date else "",
                                          end_date=str(api_end_date) if api_end_date else "")
        if not rooms_data:
            st.warning("未找到直播记录")
        else:
            st.session_state[f"{prefix}_rooms"] = rooms_data
            has_script = sum(1 for r in rooms_data if r.get("geminiTaskId"))
            st.success(f"找到 {len(rooms_data)} 场，{has_script} 场有脚本")
    if st.session_state.get(f"{prefix}_rooms"):
        rooms_data = st.session_state[f"{prefix}_rooms"]
        for rd in rooms_data[:8]:
            tag = " 📝" if rd.get("geminiTaskId") else ""
            st.write(f"  - {rd['openTime']} | ctr={rd['ctr']} dwell={rd['dwell_time']}s{tag}")
        if len(rooms_data) > 8:
            st.caption(f"...还有 {len(rooms_data) - 8} 场")
        if st.button("📥 导入（数据+脚本+提示词）", type="primary", key=f"{prefix}_go"):
            _, _, new_ids = import_sessions_from_api(room, rooms_data)
            st.session_state.pop(f"{prefix}_rooms", None)
            if new_ids:
                st.session_state[f"{prefix}_new_ids"] = new_ids
                st.session_state[f"{prefix}_new_room"] = room.id
            st.rerun()


def _excel_import_ui(room, prefix):
    files = st.file_uploader("上传 Excel（文件名=roomId）", type=["xlsx", "xls"],
                             accept_multiple_files=True, key=f"{prefix}_excel")
    if files and st.button("📥 导入", type="primary", key=f"{prefix}_btn"):
        for f in files:
            fname = f.name.rsplit(".", 1)[0].strip()
            with st.spinner(f"处理 {fname}..."):
                script = extract_script_from_excel(f)
                metrics = fetch_live_data(fname)
                if metrics is None:
                    st.warning(f"❌ {fname}: API未找到数据，跳过")
                    continue
                meta = {k: v for k, v in metrics.items() if k.startswith("_")}
                clean = {k: v for k, v in metrics.items() if not k.startswith("_")}
                session = Session(
                    id=new_session_id(), timestamp=meta.get("_open_time", datetime.now().isoformat()),
                    script=script, metrics=clean, room_id=room.id,
                    notes=f"roomId={fname} host={meta.get('_host', '')}",
                )
                save_session(session)
                st.success(f"✅ {fname}")
        st.rerun()


def _manual_input_ui(room, prefix):
    with st.form(f"{prefix}_form"):
        script_text = st.text_area("直播脚本", height=200, key=f"{prefix}_script")
        prompt_text = st.text_area("提示词（可选）", height=100, key=f"{prefix}_prompt")
        cols = st.columns(3)
        metric_vals = {}
        for i, m in enumerate(DEFAULT_METRICS):
            with cols[i % 3]:
                v = st.number_input(m["name"], min_value=0.0, value=0.0, step=0.01, key=f"{prefix}_m_{m['key']}")
                if v > 0:
                    metric_vals[m["key"]] = v
        notes = st.text_input("备注（可选）", key=f"{prefix}_notes")
        if st.form_submit_button("➕ 添加场次"):
            if script_text.strip():
                session = Session(
                    id=new_session_id(), timestamp=datetime.now().isoformat(),
                    script=script_text.strip(), metrics=metric_vals, room_id=room.id,
                    prompt=prompt_text.strip() if prompt_text else "", notes=notes or "",
                )
                save_session(session)
                st.success("场次已添加")
                st.rerun()


def _batch_score_ui(room_id, room_name, prefix):
    cleanup_dead(room_id)
    running = next((t for t in list_tasks(room_id=room_id, status="running") if t.op == "batch_score"), None)
    if running:
        st.info(f"🔄 后台评分中：{running.progress}")
        st.caption(f"当前最高分：{running.best_score:.1f}")
        if running.log:
            with st.expander("日志", expanded=False):
                for entry in running.log[-10:]:
                    st.write(entry)
        if st.button("⏹ 停止评分", key=f"{prefix}_stop"):
            request_stop(running.id)
            st.rerun()
        _time.sleep(3)
        st.rerun()
    else:
        recent = [t for t in list_tasks(room_id=room_id) if t.op == "batch_score" and t.status in ("completed", "stopped")]
        if recent and recent[0].result.get("best_session_id"):
            last = recent[0]
            st.success(f"评分完成：{last.result['scored']}/{last.result['total']} 场，最高分 {last.result['best_score']:.1f}")
        prov, model, key = scorer_selector(prefix)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("🚀 全部重新评分", type="primary", use_container_width=True, key=f"{prefix}_all"):
                if launch_batch_score(room_id, room_name, prov, key, model, desc=f"「{room_name}」全部重新评分"):
                    _time.sleep(1)
                    st.rerun()
        with b2:
            unscored = [s for s in list_sessions(room_id) if s.total_score <= 0]
            if st.button(f"📝 只评未评分（{len(unscored)}场）", use_container_width=True,
                         key=f"{prefix}_unscored", disabled=len(unscored) == 0):
                if launch_batch_score(room_id, room_name, prov, key, model,
                                      desc=f"「{room_name}」未评分{len(unscored)}场", unscored_only=True):
                    _time.sleep(1)
                    st.rerun()


# ============================================================
# Tab 1: 新建直播间
# ============================================================
with tabs[0]:
    st.subheader("创建新直播间")
    room_name = st.text_input("直播间名称", placeholder="例：美妆直播间-口红系列")
    product_info = st.text_area("产品信息", height=100, placeholder="产品名称、卖点、价格区间等")
    if st.button("✅ 创建直播间", type="primary"):
        if not room_name.strip():
            st.error("请输入直播间名称")
        else:
            room = create_room(room_name.strip(), product_info.strip())
            st.success(f"直播间「{room.name}」已创建！")
            st.session_state["new_room_id"] = room.id
            st.rerun()
    if st.session_state.get("new_room_id"):
        room_id = st.session_state["new_room_id"]
        room = load_room(room_id)
        st.divider()
        st.subheader(f"📥 为「{room.name}」导入历史场次")
        method = st.radio("导入方式", ["API自动获取", "上传Excel", "手动输入"], horizontal=True, key="imp_method")
        if method == "API自动获取":
            _api_search_import_ui(room, "imp_api")
        elif method == "上传Excel":
            _excel_import_ui(room, "imp_excel")
        else:
            _manual_input_ui(room, "imp_manual")
        existing = list_sessions(room_id)
        if existing:
            st.write(f"已导入 {len(existing)} 场")
            if st.button("🎯 完成导入，自动评分选基线", type="primary", use_container_width=True):
                st.session_state["ready_to_score"] = room_id
        if st.session_state.get("ready_to_score") == room_id:
            st.divider()
            _batch_score_ui(room_id, room.name, "new_batch")

# ============================================================
# Tab 2: 添加场次
# ============================================================
# PLACEHOLDER_TAB2
with tabs[1]:
    st.subheader("为已有直播间添加新场次")
    rooms = list_rooms()
    if not rooms:
        st.info("暂无直播间，请先创建。")
    else:
        room_options = {f"{r.name} ({r.id})": r for r in rooms}
        selected = st.selectbox("选择直播间", list(room_options.keys()), key="add_room")
        room = room_options[selected]
        add_method = st.radio("添加方式", ["API自动获取", "上传Excel", "手动输入"],
                              horizontal=True, key="add_method_radio")
        if add_method == "API自动获取":
            _api_search_import_ui(room, "add_api")
            if st.session_state.get("add_api_new_ids") and st.session_state.get("add_api_new_room") == room.id:
                new_ids = st.session_state["add_api_new_ids"]
                st.info(f"新导入 {len(new_ids)} 场，可立即评分")
                prov, model, key = scorer_selector("add_score")
                if st.button("🚀 评分新导入的场次", type="primary", key="add_score_go"):
                    if launch_batch_score(room.id, room.name, prov, key, model,
                                          desc=f"「{room.name}」新增{len(new_ids)}场评分", session_ids=new_ids):
                        st.session_state.pop("add_api_new_ids", None)
                        st.rerun()
        elif add_method == "上传Excel":
            _excel_import_ui(room, "add_excel")
        else:
            script_method = st.radio("脚本输入方式", ["手动粘贴", "上传文件"], horizontal=True, key="add_script_method")
            script_text = ""
            if script_method == "手动粘贴":
                script_text = st.text_area("直播脚本", height=300, key="add_script_text")
            else:
                f = st.file_uploader("上传脚本", type=["txt", "md"], key="add_file")
                if f:
                    script_text = f.read().decode("utf-8")
            prompt_text = st.text_area("提示词（可选）", height=100, key="add_prompt_text")
            metrics_method = st.radio("数据输入", ["手动填写", "上传文件"], horizontal=True, key="add_metrics_method")
            metrics = {}
            if metrics_method == "手动填写":
                cols = st.columns(3)
                for i, m in enumerate(DEFAULT_METRICS):
                    with cols[i % 3]:
                        v = st.number_input(m["name"], min_value=0.0, value=0.0, step=0.01, key=f"add_m_{m['key']}")
                        if v > 0:
                            metrics[m["key"]] = v
            else:
                data_file = st.file_uploader("上传数据", type=["xlsx", "xls", "csv", "json"], key="add_data")
                if data_file:
                    try:
                        name = data_file.name.lower()
                        if name.endswith((".xlsx", ".xls")):
                            metrics = parse_metrics_from_excel(data_file)
                        elif name.endswith(".csv"):
                            metrics = parse_metrics_from_csv(data_file)
                        elif name.endswith(".json"):
                            metrics = parse_metrics_from_json(data_file)
                        st.json(metrics)
                    except Exception as e:
                        st.error(f"解析失败：{e}")
            notes = st.text_input("备注（可选）", key="add_notes")
            if st.button("✅ 提交场次", type="primary", use_container_width=True, key="add_submit"):
                if not script_text.strip():
                    st.error("请输入脚本")
                elif not metrics:
                    st.error("请输入至少一项数据")
                else:
                    session = Session(id=new_session_id(), timestamp=datetime.now().isoformat(),
                                     script=script_text.strip(), metrics=metrics, room_id=room.id,
                                     prompt=prompt_text.strip(), notes=notes)
                    save_session(session)
                    st.success(f"场次已添加到「{room.name}」！")

# ============================================================
# Tab 3: 管理直播间
# ============================================================
# PLACEHOLDER_TAB3
with tabs[2]:
    st.subheader("直播间列表")
    rooms = list_rooms()
    if not rooms:
        st.info("暂无直播间。")
    else:
        for r in rooms:
            sessions = list_sessions(r.id)
            baseline_tag = f" | 基线: {r.baseline_session_id[:15]}" if r.baseline_session_id else ""
            prompt_tag = " | 有基线提示词" if r.base_prompt else ""
            with st.expander(f"**{r.name}** — {len(sessions)} 场{baseline_tag}{prompt_tag}"):
                st.caption(f"产品: {r.product_info[:100]}  |  ID: {r.id}  |  创建: {r.created_at[:10]}")
                with st.expander("📌 原始提示词模板"):
                    orig_prompt = st.text_area("原始提示词", value=r.original_prompt, height=200,
                                               key=f"orig_prompt_{r.id}", placeholder="输入原始提示词模板...")
                    if orig_prompt != r.original_prompt:
                        if st.button("💾 保存原始提示词", key=f"save_orig_{r.id}"):
                            r.original_prompt = orig_prompt
                            if not r.base_prompt:
                                r.base_prompt = orig_prompt
                            r.save()
                            st.success("已保存")
                            st.rerun()
                new_prompt = st.text_area("基线提示词", value=r.base_prompt, height=150,
                                          key=f"prompt_{r.id}", placeholder="输入基线提示词...")
                if new_prompt != r.base_prompt:
                    if st.button("💾 保存提示词", key=f"save_prompt_{r.id}"):
                        if not r.original_prompt:
                            r.original_prompt = new_prompt
                        r.base_prompt = new_prompt
                        r.save()
                        st.success("已保存")
                        st.rerun()
                unscored_list = [s for s in sessions if s.total_score <= 0]
                if unscored_list:
                    running_for_room = [t for t in list_tasks(room_id=r.id, status="running") if t.op == "batch_score"]
                    if running_for_room:
                        st.info(f"📝 {len(unscored_list)}场未评分（后台运行中）")
                    elif st.button(f"📝 {len(unscored_list)}场未评分（批量评分）", key=f"unscored_{r.id}"):
                        from config import GOOGLE_API_KEY as _gk, get_default_models as _gdm
                        defs = _gdm()
                        launch_batch_score(r.id, r.name, defs["scorer"]["provider"], _gk, defs["scorer"]["model"],
                                           desc=f"「{r.name}」{len(unscored_list)}场未评分", unscored_only=True)
                        st.rerun()
                if sessions and not r.baseline_session_id:
                    if st.button("🎯 批量评分选基线", key=f"batch_{r.id}"):
                        st.session_state["batch_room_id"] = r.id
                        st.rerun()
                if sessions and r.baseline_session_id:
                    if st.button("🔄 全部重新评分", key=f"rescore_{r.id}"):
                        st.session_state["batch_room_id"] = r.id
                        st.rerun()
                st.divider()
                st.write("**📥 添加场次**")
                mgmt_method = st.radio("方式", ["API自动获取", "上传Excel", "手动输入"],
                                       horizontal=True, key=f"mgmt_add_{r.id}")
                if mgmt_method == "API自动获取":
                    _api_search_import_ui(r, f"mgmt_api_{r.id}")
                elif mgmt_method == "上传Excel":
                    _excel_import_ui(r, f"mgmt_excel_{r.id}")
                else:
                    _manual_input_ui(r, f"mgmt_manual_{r.id}")
                st.divider()
                if sessions and st.button(f"🧹 清除所有脚本（{len(sessions)}场）", key=f"clear_{r.id}"):
                    st.session_state[f"confirm_clear_{r.id}"] = True
                if st.session_state.get(f"confirm_clear_{r.id}"):
                    st.warning(f"确定清除「{r.name}」的全部 {len(sessions)} 场数据？")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("确认清除", key=f"yes_clear_{r.id}", type="primary"):
                            import shutil
                            sd = r.sessions_dir()
                            if sd.exists():
                                shutil.rmtree(sd)
                                sd.mkdir()
                            r.baseline_session_id = ""
                            r.save()
                            st.session_state.pop(f"confirm_clear_{r.id}", None)
                            st.rerun()
                    with cc2:
                        if st.button("取消", key=f"no_clear_{r.id}"):
                            st.session_state.pop(f"confirm_clear_{r.id}", None)
                            st.rerun()
                if st.button("🗑️ 删除此直播间", key=f"del_room_{r.id}"):
                    st.session_state[f"confirm_del_{r.id}"] = True
                if st.session_state.get(f"confirm_del_{r.id}"):
                    st.warning(f"确定删除「{r.name}」及其所有数据？不可恢复。")
                    d1, d2 = st.columns(2)
                    with d1:
                        if st.button("确认删除", key=f"yes_del_{r.id}", type="primary"):
                            import shutil
                            shutil.rmtree(r.dir(), ignore_errors=True)
                            st.session_state.pop(f"confirm_del_{r.id}", None)
                            st.rerun()
                    with d2:
                        if st.button("取消", key=f"no_del_{r.id}"):
                            st.session_state.pop(f"confirm_del_{r.id}", None)
                            st.rerun()
        batch_rid = st.session_state.get("batch_room_id")
        if batch_rid:
            batch_room = load_room(batch_rid)
            st.divider()
            st.subheader(f"⚙️ 批量评分「{batch_room.name}」")
            _batch_score_ui(batch_rid, batch_room.name, "mgmt_batch")
