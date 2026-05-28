import streamlit as st
from datetime import datetime
from config import DEFAULT_METRICS
from models import Session
from data_io import (new_session_id, save_session, list_sessions,
                     parse_metrics_from_excel, parse_metrics_from_json, parse_metrics_from_csv)
from room import create_room, list_rooms, load_room, load_tags, add_tag
from zmeng_api import fetch_live_data, extract_script_from_excel, fetch_host_rooms, fetch_rooms_by_ids
from task_manager import request_stop, list_tasks, cleanup_dead
from ui_helpers import import_sessions_from_api, scorer_selector, launch_batch_score
from llm import PROVIDERS
from hill_climb import generate_script_from_prompt
import time as _time


def _latest_session_date(sessions) -> str:
    """从 sessions 里返回最近一场的日期 (YYYY-MM-DD)，没有就返回空串。"""
    ts_list = [s.timestamp for s in sessions if getattr(s, "timestamp", "")]
    if not ts_list:
        return ""
    return max(ts_list)[:10]

st.set_page_config(page_title="直播间管理", page_icon="🏠", layout="wide")
st.title("🏠 直播间管理")

tabs = st.tabs(["新建直播间", "添加场次", "管理直播间"])


def _api_search_import_ui(room, prefix):
    search_mode = st.radio("搜索方式", ["按主播ID", "按直播间ID"], horizontal=True, key=f"{prefix}_mode")

    if search_mode == "按主播ID":
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
    else:
        room_ids_input = st.text_area("直播间ID（每行一个，或用逗号/空格分隔）",
                                      placeholder="7399000000000000000\n7399000000000000001",
                                      height=100, key=f"{prefix}_room_ids")
        if room_ids_input and st.button("🔍 查询", type="primary", key=f"{prefix}_search_ids"):
            import re
            ids = [x.strip() for x in re.split(r'[,\s\n]+', room_ids_input) if x.strip()]
            with st.spinner(f"查询 {len(ids)} 个直播间..."):
                rooms_data = fetch_rooms_by_ids(ids)
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


def _cold_start_ui(room, prefix):
    """冷启动模式：按用户提供的提示词生成一份脚本，合成默认指标的 session，自动评分。"""
    from config import (get_default_models, get_effective_locked_prompt,
                        OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY)
    from llm import get_provider

    st.caption("未开播的冷启动模式：系统按你给的提示词生成一份脚本，"
               "用默认指标合成一场 session 并自动评分；等真实直播数据进来后再覆盖。")

    cold_prompt = st.text_area(
        "原始提示词（必填）",
        value=room.original_prompt, height=280, key=f"{prefix}_prompt",
        placeholder="粘贴你准备让数字人跑的完整原始提示词...",
    )
    c1, c2 = st.columns(2)
    with c1:
        default_ctr = st.number_input("默认 CTR (%)", min_value=0.1, max_value=20.0,
                                      value=3.0, step=0.1, key=f"{prefix}_ctr")
    with c2:
        default_dwell = st.number_input("默认停留时长 (秒)", min_value=1, max_value=600,
                                        value=15, step=1, key=f"{prefix}_dwell")

    defs = get_default_models()
    st.markdown("**脚本生成模型**")
    prov_keys = list(PROVIDERS.keys())
    gprov_col, gmodel_col = st.columns(2)
    with gprov_col:
        default_gidx = prov_keys.index(defs["generator"]["provider"]) if defs["generator"]["provider"] in prov_keys else 0
        gen_prov = st.selectbox("生成提供商", prov_keys, index=default_gidx, key=f"{prefix}_gprov")
    gen_models = PROVIDERS[gen_prov]["models"]
    with gmodel_col:
        gmidx = gen_models.index(defs["generator"]["model"]) if gen_prov == defs["generator"]["provider"] and defs["generator"]["model"] in gen_models else 0
        gen_model = st.selectbox("生成模型", gen_models, index=gmidx, key=f"{prefix}_gmodel")

    st.markdown("**评分模型**")
    sprov, smodel, skey = scorer_selector(f"{prefix}_score")

    gkey_map = {"openai": OPENAI_API_KEY, "anthropic": ANTHROPIC_API_KEY,
                "google（代理）": GOOGLE_API_KEY, "google（官方）": GOOGLE_API_KEY}
    gen_key = gkey_map.get(gen_prov, "")
    if not gen_key:
        gen_key = st.text_input("生成模型 API Key", type="password", key=f"{prefix}_gkey")

    if st.button("🚀 生成脚本并自动评分", type="primary", use_container_width=True, key=f"{prefix}_go"):
        if not cold_prompt.strip():
            st.error("请粘贴原始提示词"); return
        if not gen_key or not skey:
            st.error("请配置生成模型和评分模型的 API Key"); return

        room.original_prompt = cold_prompt.strip()
        if not room.base_prompt:
            room.base_prompt = cold_prompt.strip()
        room.save()

        with st.spinner("用提示词生成脚本中..."):
            locked_desc = get_effective_locked_prompt(room)
            gen = get_provider(gen_prov, gen_key, gen_model)
            try:
                script = generate_script_from_prompt(
                    cold_prompt.strip(), gen,
                    baseline_script="",
                    locked_description=locked_desc,
                )
            except Exception as e:
                st.error(f"生成失败：{e}"); return

        if not script or not script.strip():
            st.error("生成器返回空脚本，请检查模型和网络"); return

        session = Session(
            id=new_session_id(),
            timestamp=datetime.now().isoformat(),
            script=script.strip(),
            metrics={"ctr": float(default_ctr) / 100.0,
                     "dwell_time": float(default_dwell)},
            room_id=room.id,
            prompt=cold_prompt.strip(),
            notes=(f"冷启动合成：ctr={default_ctr}%, dwell={default_dwell}s, "
                   f"gen={gen_prov}/{gen_model}"),
        )
        save_session(session)

        launch_batch_score(room.id, room.name, sprov, skey, smodel,
                           desc=f"「{room.name}」冷启动首场评分",
                           session_ids=[session.id])
        st.success(f"脚本已生成并提交评分（session {session.id[:12]}）。"
                   f"切到「管理直播间」可查看进度；评分完成后即可进「棘轮分析」迭代。")
        _time.sleep(1)
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
    if st.button("✅ 创建直播间", type="primary"):
        if not room_name.strip():
            st.error("请输入直播间名称")
        else:
            room = create_room(room_name.strip(), "")
            st.success(f"直播间「{room.name}」已创建！")
            st.session_state["new_room_id"] = room.id
            st.rerun()
    if st.session_state.get("new_room_id"):
        room_id = st.session_state["new_room_id"]
        room = load_room(room_id)
        st.divider()
        create_mode = st.radio(
            "模式",
            ["导入历史场次（已开播）", "全新直播间（冷启动，未开播）"],
            horizontal=True, key="create_mode",
        )
        if create_mode.startswith("导入"):
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
        else:
            st.subheader(f"🧬 「{room.name}」冷启动生成首场")
            _cold_start_ui(room, "imp_cold")

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
        _existing_sessions = list_sessions(room.id)
        _latest = _latest_session_date(_existing_sessions)
        if _latest:
            st.caption(f"📅 系统内最近一场：**{_latest}**（共 {len(_existing_sessions)} 场）— 请从此日期之后添加")
        else:
            st.caption("📅 该直播间暂无历史场次")
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
        # Tag filter
        all_tags = load_tags()
        tag_filter = st.multiselect("按标签筛选", all_tags, default=[], key="mgmt_tag_filter")
        if tag_filter:
            rooms = [r for r in rooms if r.tag in tag_filter]
            if not rooms:
                st.info("该标签下暂无直播间。")

        # Batch tag assignment
        with st.expander("🏷️ 批量打标签"):
            batch_selected = []
            for r in rooms:
                if st.checkbox(f"{r.name} [{r.tag}]" if r.tag else r.name, key=f"batch_cb_{r.id}"):
                    batch_selected.append(r.id)
            if batch_selected:
                bc1, bc2 = st.columns([2, 1])
                with bc1:
                    batch_tag_options = [""] + all_tags
                    batch_tag = st.selectbox("选择标签", batch_tag_options, key="batch_tag_select")
                    batch_new_tag = st.text_input("或输入新标签", key="batch_new_tag")
                with bc2:
                    st.write("")
                    st.write("")
                    if st.button(f"✅ 为 {len(batch_selected)} 个直播间打标签", type="primary", key="batch_tag_go"):
                        target_tag = batch_new_tag.strip() if batch_new_tag.strip() else batch_tag
                        if target_tag and target_tag not in all_tags:
                            add_tag(target_tag)
                        for rid in batch_selected:
                            rm = load_room(rid)
                            rm.tag = target_tag
                            rm.save()
                        st.success(f"已为 {len(batch_selected)} 个直播间设置标签「{target_tag}」")
                        st.rerun()

        for r in rooms:
            sessions = list_sessions(r.id)
            baseline_tag = f" | 基线: {r.baseline_session_id[:15]}" if r.baseline_session_id else ""
            prompt_tag = " | 有基线提示词" if r.base_prompt else ""
            latest_date = _latest_session_date(sessions)
            latest_tag = f" | 最近一场: {latest_date}" if latest_date else ""
            room_tag_label = f" [{r.tag}]" if r.tag else ""
            with st.expander(f"**{r.name}**{room_tag_label} — {len(sessions)} 场{latest_tag}{baseline_tag}{prompt_tag}"):
                # Name and tag editing
                nc1, nc2 = st.columns([3, 2])
                with nc1:
                    new_name = st.text_input("直播间名称", value=r.name, key=f"name_{r.id}")
                with nc2:
                    tag_options = [""] + all_tags
                    current_idx = tag_options.index(r.tag) if r.tag in tag_options else 0
                    new_tag = st.selectbox("标签", tag_options, index=current_idx, key=f"tag_{r.id}")
                    new_custom_tag = st.text_input("新增标签", key=f"newtag_{r.id}", placeholder="输入新标签名...")
                if new_custom_tag:
                    if st.button("➕ 添加标签", key=f"addtag_{r.id}"):
                        all_tags = add_tag(new_custom_tag.strip())
                        r.tag = new_custom_tag.strip()
                        r.save()
                        st.rerun()
                if new_name != r.name or new_tag != r.tag:
                    if st.button("💾 保存名称/标签", key=f"save_name_{r.id}"):
                        r.name = new_name.strip() if new_name.strip() else r.name
                        r.tag = new_tag
                        r.save()
                        st.success("已保存")
                        st.rerun()

                st.caption(f"ID: {r.id}  |  创建: {r.created_at[:10]}")
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

                with st.expander("🔒 锁定提示词描述（棘轮迭代时必遵守）"):
                    from config import get_global_locked_prompt as _get_gl
                    _global_locked = _get_gl()
                    _use_global = st.checkbox(
                        "使用全局锁定描述",
                        value=r.use_global_locked_prompt,
                        key=f"ulg_{r.id}",
                        help="勾选则迭代时使用首页配置的全局锁定描述；取消勾选后在下方填写本直播间专属内容。",
                    )
                    if _use_global:
                        st.text_area(
                            "当前生效（来自全局，只读）",
                            value=_global_locked if _global_locked else "（全局未配置，迭代时不会注入锁定段）",
                            height=150,
                            disabled=True,
                            key=f"gl_show_{r.id}",
                        )
                        _override_text = r.locked_prompt_description
                    else:
                        _seed = r.locked_prompt_description or _global_locked
                        _override_text = st.text_area(
                            "本直播间专用锁定描述（默认以全局内容为基础，可增删改）",
                            value=_seed,
                            height=200,
                            placeholder="示例：所有价格保留原币种符号；禁用「最」「第一」等极限词；主播自称必须用「我们」不用「我」。",
                            key=f"lpd_{r.id}",
                        )
                    if st.button("💾 保存锁定描述", key=f"save_lpd_{r.id}"):
                        r.use_global_locked_prompt = _use_global
                        r.locked_prompt_description = _override_text
                        r.save()
                        st.success("已保存，下一次迭代立即生效")
                        st.rerun()

                # Scored sessions with rescore checkboxes
                scored_sessions = [s for s in sessions if s.total_score > 0]
                if scored_sessions:
                    with st.expander(f"📊 已评分场次（{len(scored_sessions)}场）"):
                        selected_ids = []
                        for s in scored_sessions:
                            label = f"{s.id[:20]} | {s.total_score:.1f}分 | 静态{s.static_total:.1f} 实效{s.effect_total:.1f}"
                            if st.checkbox(label, key=f"rescore_cb_{r.id}_{s.id}"):
                                selected_ids.append(s.id)
                        if selected_ids:
                            if st.button(f"🔄 重新评分选中的 {len(selected_ids)} 场", type="primary",
                                         key=f"rescore_selected_{r.id}"):
                                from config import GOOGLE_API_KEY as _gk2, get_default_models as _gdm2
                                from data_io import save_session as _save
                                defs = _gdm2()
                                for sid in selected_ids:
                                    s = next(x for x in scored_sessions if x.id == sid)
                                    s.total_score = 0
                                    s.static_total = 0
                                    s.effect_total = 0
                                    s.static_scores = {}
                                    s.effect_scores = {}
                                    _save(s)
                                launch_batch_score(r.id, r.name, defs["scorer"]["provider"], _gk2, defs["scorer"]["model"],
                                                   desc=f"「{r.name}」重评{len(selected_ids)}场",
                                                   session_ids=selected_ids)
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
