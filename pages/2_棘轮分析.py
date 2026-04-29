import streamlit as st
import plotly.graph_objects as go
from config import RATCHET_STATE_FILE, OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
from models import RatchetState
from data_io import list_sessions, save_session
from ratchet import compare_metrics, get_improvement_targets, ratchet_step
from llm import get_provider, PROVIDERS
from prompts import SYSTEM_PROMPT, build_analysis_prompt, build_generation_prompt
from rubric import (
    STATIC_DIMENSIONS, EFFECT_METRICS,
    score_script, compute_effect_score, compute_total_score, find_weakest_dimension,
    load_weight_config, save_weight_config, get_effective_weights,
)
from hill_climb import (
    diagnose, generate_improvement, generate_rewrite, decide, check_length, check_stagnation,
    generate_prompt_improvement, generate_prompt_rewrite, generate_script_from_prompt,
    auto_iterate, extract_baseline_strengths,
)
from priority import classify_priority
from room import list_rooms, load_room, save_candidate, list_candidates, set_baseline
from models import RatchetState, Candidate
from zmeng_api import script_to_excel_bytes
import audit
import uuid

st.set_page_config(page_title="棘轮分析", page_icon="🔧", layout="wide")
st.title("🔧 棘轮分析")

# --- 侧边栏 ---
with st.sidebar:
    from config import get_default_models
    _defaults = get_default_models()
    _prov_list = list(PROVIDERS.keys())

    def _prov_idx(prov_name):
        return _prov_list.index(prov_name) if prov_name in _prov_list else 0

    def _model_idx(models, model_name):
        return models.index(model_name) if model_name in models else 0

    st.subheader("🎯 评分模型")
    scorer_provider_name = st.selectbox("评分提供商", _prov_list, index=_prov_idx(_defaults["scorer"]["provider"]), key="scorer_prov")
    _scorer_models = PROVIDERS[scorer_provider_name]["models"]
    scorer_model_name = st.selectbox("评分模型", _scorer_models, index=_model_idx(_scorer_models, _defaults["scorer"]["model"]) if scorer_provider_name == _defaults["scorer"]["provider"] else 0, key="scorer_model")

    st.subheader("✏️ 提示词/脚本优化")
    opt_provider_name = st.selectbox("优化提供商", _prov_list, index=_prov_idx(_defaults["optimizer"]["provider"]), key="opt_prov")
    _opt_models = PROVIDERS[opt_provider_name]["models"]
    opt_model_name = st.selectbox("优化模型", _opt_models, index=_model_idx(_opt_models, _defaults["optimizer"]["model"]) if opt_provider_name == _defaults["optimizer"]["provider"] else 0, key="opt_model")

    st.subheader("📝 脚本生成")
    gen_provider_name = st.selectbox("生成提供商", _prov_list, index=_prov_idx(_defaults["generator"]["provider"]), key="gen_prov")
    _gen_models = PROVIDERS[gen_provider_name]["models"]
    gen_model_name = st.selectbox("生成模型", _gen_models, index=_model_idx(_gen_models, _defaults["generator"]["model"]) if gen_provider_name == _defaults["generator"]["provider"] else 0, key="gen_model")

    api_keys = {"openai": OPENAI_API_KEY, "anthropic": ANTHROPIC_API_KEY,
                "google（代理）": GOOGLE_API_KEY, "google（官方）": GOOGLE_API_KEY}
    missing = set()
    for p in [scorer_provider_name, opt_provider_name, gen_provider_name]:
        if not api_keys.get(p):
            missing.add(p)
    manual_key = ""
    if missing:
        manual_key = st.text_input(f"API Key ({', '.join(missing)})", type="password")

    st.divider()
    st.subheader("⚖️ 评分权重配置")
    wc = load_weight_config()
    with st.expander("静态维度权重"):
        static_w = {}
        for d in STATIC_DIMENSIONS:
            static_w[d["id"]] = st.slider(d["name"], 0, 15, wc.get("static", {}).get(d["id"], d["weight"]), key=f"sw_{d['id']}")
        static_sum = sum(static_w.values())
        st.caption(f"静态总权重: {static_sum}")
    with st.expander("实效维度权重"):
        effect_w = {}
        for m in EFFECT_METRICS:
            effect_w[m["id"]] = st.slider(m["name"], 0, 30, wc.get("effect", {}).get(m["id"], m["weight"]), key=f"ew_{m['id']}")
        effect_sum = sum(effect_w.values())
        st.caption(f"实效总权重: {effect_sum}")
    total_weight = static_sum + effect_sum
    st.caption(f"满分 = {total_weight}")
    new_wc = {"static": static_w, "effect": effect_w}
    if new_wc != wc:
        save_weight_config(new_wc)


def _get_key(provider_name):
    return api_keys.get(provider_name) or manual_key


# --- 选择直播间 ---
rooms = list_rooms()
if not rooms:
    st.warning("暂无直播间。请先前往「直播间管理」创建。")
    st.stop()

room_options = {f"{r.name} ({r.id})": r for r in rooms}
selected_room_label = st.selectbox("选择直播间", list(room_options.keys()))
room = room_options[selected_room_label]
state = RatchetState.load(room.ratchet_state_path())

sessions = list_sessions(room.id)
if not sessions:
    st.warning("该直播间暂无场次数据。")
    st.stop()

# --- 选择场次 ---
_sorted_sessions = sorted(sessions, key=lambda s: s.total_score, reverse=True)
session_options = {}
for s in _sorted_sessions:
    score_str = f" [{s.total_score:.1f}分]" if s.total_score > 0 else ""
    tag = " ⭐基线" if s.id == room.baseline_session_id else ""
    session_options[f"{s.id[:20]} ({s.timestamp[:10]}){score_str}{tag}"] = s
_session_keys = list(session_options.keys())
_baseline_idx = 0
for i, label in enumerate(_session_keys):
    if "⭐基线" in label:
        _baseline_idx = i
        break
selected_label = st.selectbox("选择场次", _session_keys, index=_baseline_idx)
session = session_options[selected_label]

# --- 优化模式 ---
opt_mode = st.radio("优化模式", ["提示词模式（Prompt）", "脚本模式（Script）"], horizontal=True)
is_prompt_mode = "Prompt" in opt_mode

if is_prompt_mode and not room.base_prompt and not session.prompt:
    st.warning("提示词模式需要基线提示词。请在直播间管理中导入带提示词的场次。")

with st.expander("查看完整脚本", expanded=False):
    st.text(session.script)
if session.prompt:
    with st.expander("查看提示词", expanded=False):
        st.text(session.prompt)

# --- A: 指标对比 ---
st.subheader("📊 业务指标对比")
comparison = compare_metrics(session, state)
if comparison:
    metric_cols = st.columns(min(len(comparison), 4))
    for i, m in enumerate(comparison):
        with metric_cols[i % len(metric_cols)]:
            delta = None
            if m["baseline"] is not None and m["baseline"] != 0:
                delta = f"{((m['current'] - m['baseline']) / m['baseline'] * 100):.1f}%"
            st.metric(m["key"], f"{m['current']}", delta=delta)

with st.expander("✏️ 修改指标数据（纠正异常值）"):
    numeric_metrics = {k: v for k, v in session.metrics.items() if not k.startswith("_") and isinstance(v, (int, float))}
    edit_cols = st.columns(min(len(numeric_metrics), 4)) if numeric_metrics else []
    edited_metrics = dict(session.metrics)
    for i, (k, v) in enumerate(numeric_metrics.items()):
        with edit_cols[i % len(edit_cols)]:
            edited_metrics[k] = st.number_input(k, value=float(v), step=0.01, format="%.2f", key=f"edit_m_{session.id}_{k}")
    if st.button("✅ 确认修改指标", type="primary"):
        session.metrics = edited_metrics
        save_session(session)
        st.success("指标已更新，评分将使用修改后的值")
        st.rerun()

# --- B: 双层评分 ---
st.divider()
st.subheader("🎯 脚本质量评分（独立评审）")

if st.button("运行独立评分", type="primary", use_container_width=True):
    key = _get_key(scorer_provider_name)
    if not key:
        st.error("请配置评分模型的 API Key")
        st.stop()
    with st.spinner(f"独立评分中（{scorer_provider_name}/{scorer_model_name}）..."):
        try:
            scorer = get_provider(scorer_provider_name, key, scorer_model_name)
            dwell = session.metrics.get("dwell_time", 0)
            result = score_script(session.script, scorer, state.locked_constraints, new_wc, dwell_seconds=dwell)
            session.static_scores = result["scores"]
            session.rubric_reasoning = result.get("reasoning", {})
            session.static_total = result["static_score"]
            session.scorer_model = f"{scorer_provider_name}/{scorer_model_name}"
            all_metrics = [s.metrics for s in sessions]
            eff_total, eff_scores = compute_effect_score(session.metrics, state.effect_baselines, new_wc, all_sessions_metrics=all_metrics)
            session.effect_scores = eff_scores
            session.effect_total = eff_total
            session.total_score = compute_total_score(session.static_total, eff_total)
            save_session(session)
            audit.append_entry(session.id, 0, session.total_score, "baseline",
                               scorer_model=session.scorer_model, note="评分", room_id=room.id)
            st.rerun()
        except Exception as e:
            st.error(f"评分失败：{e}")

if session.static_scores:
    scores = session.static_scores
    reasoning = session.rubric_reasoning

    col_score, col_radar = st.columns([1, 1])
    with col_score:
        st.metric("综合总分", f"{session.total_score}/{total_weight}")
        st.caption(f"静态 {session.static_total}/{static_sum} + 实效 {session.effect_total}/{effect_sum}")
        if session.scorer_model:
            st.caption(f"评分模型: {session.scorer_model}")
    with col_radar:
        dims = [d["name"] for d in STATIC_DIMENSIONS]
        vals = [scores.get(d["id"], 0) for d in STATIC_DIMENSIONS]
        fig = go.Figure(go.Scatterpolar(r=vals + [vals[0]], theta=dims + [dims[0]], fill="toself"))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0, 10])), height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    for d in STATIC_DIMENSIONS:
        s = scores.get(d["id"], 0)
        r = reasoning.get(d["id"], "")
        st.write(f"**{d['name']}** {s}/10 — {r}")

    # --- C: 优先级诊断 ---
    st.divider()
    st.subheader("🚦 优先级诊断")
    priority = classify_priority(comparison, scores, state.history)
    badge = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢"}
    st.write(f"{badge.get(priority['level'], '⚪')} **{priority['level']}** — {priority['reason']}")
    st.write(f"建议: {priority['action']}")

    # --- D: 爬山优化 ---
    st.divider()
    eff_scores = session.effect_scores or {}
    diag = diagnose(scores, eff_scores, new_wc)
    target = diag["target"]

    if is_prompt_mode:
        st.subheader("🧗 提示词模式 — 单维度优化")
        current_prompt = session.prompt or room.base_prompt
        if not current_prompt:
            st.warning("无可用提示词。请先在直播间管理中导入。")
        elif target["type"] == "effect":
            st.info(f"最弱维度是实效指标「{target['name']}」，建议先跑一场验证。")
        else:
            st.write(f"最弱维度: **{target['name']}**（{target['score']}/10），潜在增益 +{diag['max_gain']:.1f}")
            if st.button("🧗 优化提示词", use_container_width=True):
                opt_key, scorer_key, gen_key = _get_key(opt_provider_name), _get_key(scorer_provider_name), _get_key(gen_provider_name)
                if not opt_key or not scorer_key or not gen_key:
                    st.error("请配置 API Key"); st.stop()
                with st.spinner("提炼基线优点 + 优化提示词中..."):
                    optimizer = get_provider(opt_provider_name, opt_key, opt_model_name)
                    baseline_strengths = extract_baseline_strengths(scores, session.script, optimizer)
                    new_prompt = generate_prompt_improvement(
                        current_prompt, session.script, target, scores,
                        state.locked_constraints, optimizer, room.product_info,
                        baseline_strengths=baseline_strengths, original_prompt=room.original_prompt)
                st.subheader("📝 优化后的提示词")
                st.markdown(new_prompt)
                with st.spinner("用新提示词生成脚本..."):
                    gen = get_provider(gen_provider_name, gen_key, gen_model_name)
                    new_script = generate_script_from_prompt(new_prompt, gen, baseline_script=session.script)
                with st.expander("生成的新脚本"):
                    st.text(new_script)
                with st.spinner("独立重评中..."):
                    scorer = get_provider(scorer_provider_name, scorer_key, scorer_model_name)
                    nr = score_script(new_script, scorer, state.locked_constraints, new_wc, dwell_seconds=session.metrics.get("dwell_time", 0))
                    new_static = nr["static_score"]
                    all_metrics = [s.metrics for s in sessions]
                    new_eff, _ = compute_effect_score(session.metrics, state.effect_baselines, new_wc, all_sessions_metrics=all_metrics)
                    new_total = compute_total_score(new_static, new_eff)
                old_total = session.total_score
                decision = decide(old_total, new_total)
                st.write(f"旧分: {old_total} → 新分: {new_total}")
                if decision == "keep":
                    st.success(f"✅ 保留！+{new_total - old_total:.1f}")
                    audit.append_entry(session.id, old_total, new_total, "keep",
                                       dimension=target["id"], priority=priority["level"],
                                       scorer_model=session.scorer_model, note="prompt模式", room_id=room.id)
                    state.stagnation_count = 0; state.save(room.ratchet_state_path())
                    cand = Candidate(
                        id=uuid.uuid4().hex[:8], session_id=session.id, mode="prompt",
                        content=new_prompt, generated_script=new_script,
                        total_score=new_total, static_scores=nr["scores"], effect_scores=session.effect_scores or {},
                        created_at=__import__("datetime").datetime.now().isoformat(), rounds=1,
                    )
                    save_candidate(room, cand)
                    st.info(f"已保存为胜出方案 {cand.id}")
                else:
                    st.error("❌ 回滚。")
                    audit.append_entry(session.id, old_total, new_total, "revert",
                                       dimension=target["id"], priority=priority["level"],
                                       scorer_model=session.scorer_model, note="prompt模式", room_id=room.id)
                    state.stagnation_count += 1; state.save(room.ratchet_state_path())
                st.text_area("复制优化后的提示词", new_prompt, height=300)
    else:
        st.subheader("🧗 脚本模式 — 单维度优化")
        if target["type"] == "effect":
            st.info(f"最弱维度是实效指标「{target['name']}」，建议先跑一场验证。")
        else:
            st.write(f"最弱维度: **{target['name']}**（{target['score']}/10），潜在增益 +{diag['max_gain']:.1f}")
            if st.button("🧗 针对该维度优化脚本", use_container_width=True):
                opt_key, scorer_key = _get_key(opt_provider_name), _get_key(scorer_provider_name)
                if not opt_key or not scorer_key:
                    st.error("请配置 API Key"); st.stop()
                with st.spinner("优化中..."):
                    optimizer = get_provider(opt_provider_name, opt_key, opt_model_name)
                    improved = generate_improvement(session.script, target, scores, state.locked_constraints, optimizer)
                st.markdown(improved)
                if not check_length(session.script, improved):
                    st.warning("脚本超过 150%，建议精简。")
                with st.spinner("独立重评中..."):
                    scorer = get_provider(scorer_provider_name, scorer_key, scorer_model_name)
                    nr = score_script(improved, scorer, state.locked_constraints, new_wc, dwell_seconds=session.metrics.get("dwell_time", 0))
                    new_static = nr["static_score"]
                    all_metrics = [s.metrics for s in sessions]
                    new_eff, _ = compute_effect_score(session.metrics, state.effect_baselines, new_wc, all_sessions_metrics=all_metrics)
                    new_total = compute_total_score(new_static, new_eff)
                old_total = session.total_score
                decision = decide(old_total, new_total)
                st.write(f"旧分: {old_total} → 新分: {new_total}")
                if decision == "keep":
                    st.success(f"✅ 保留！+{new_total - old_total:.1f}")
                    audit.append_entry(session.id, old_total, new_total, "keep",
                                       dimension=target["id"], priority=priority["level"],
                                       scorer_model=session.scorer_model, note="script模式", room_id=room.id)
                    state.stagnation_count = 0; state.save(room.ratchet_state_path())
                    cand = Candidate(
                        id=uuid.uuid4().hex[:8], session_id=session.id, mode="script",
                        content=improved, generated_script="",
                        total_score=new_total, static_scores=nr["scores"], effect_scores=session.effect_scores or {},
                        created_at=__import__("datetime").datetime.now().isoformat(), rounds=1,
                    )
                    save_candidate(room, cand)
                    st.info(f"已保存为胜出方案 {cand.id}")
                else:
                    st.error("❌ 回滚。")
                    audit.append_entry(session.id, old_total, new_total, "revert",
                                       dimension=target["id"], priority=priority["level"],
                                       scorer_model=session.scorer_model, note="script模式", room_id=room.id)
                    state.stagnation_count += 1; state.save(room.ratchet_state_path())

    # --- E: 探索性重写 ---
    if check_stagnation(state.stagnation_count):
        st.divider()
        st.subheader("🔄 探索性重写")
        st.warning(f"连续 {state.stagnation_count} 次回滚，建议全局重构。")

    # --- F: 自动迭代模式 ---
    st.divider()
    st.subheader("🤖 自动迭代模式")
    st.caption("后台运行，可切换页面不影响。点停止后以当前最高分保存。")

    from task_manager import create_task, load_task, request_stop, list_tasks, cleanup_dead
    import time as _time

    cleanup_dead(room.id)
    running_tasks = list_tasks(room_id=room.id, status="running")
    active_task = next((t for t in running_tasks if t.op in ("auto_iterate", "continue_iterate")), None)

    if active_task:
        st.info(f"🔄 后台迭代中：{active_task.progress}")
        st.caption(f"当前最高分：{active_task.best_score:.1f}")
        if active_task.log:
            with st.expander("日志", expanded=False):
                for entry in active_task.log[-10:]:
                    st.write(entry)
        if st.button("⏹ 停止迭代", type="primary"):
            request_stop(active_task.id)
            st.rerun()
        _time.sleep(3)
        st.rerun()
    else:
        recent_done = [t for t in list_tasks(room_id=room.id) if t.op in ("auto_iterate", "continue_iterate") and t.status in ("completed", "stopped")]
        if recent_done:
            last = recent_done[0]
            if last.result.get("candidate_id"):
                st.success(f"上次迭代完成：最高分 {last.best_score:.1f}，方案 {last.result['candidate_id']}")
            elif last.status == "stopped":
                st.info(f"上次迭代已停止：最高分 {last.best_score:.1f}")

        auto_col1, auto_col2 = st.columns(2)
        with auto_col1:
            threshold = st.number_input("提升阈值 (%)", min_value=1.0, max_value=100.0, value=10.0, step=1.0, key="auto_threshold")
        with auto_col2:
            max_rounds = st.number_input("最大轮数", min_value=1, max_value=50, value=10, step=1, key="auto_rounds")

        if st.button("🚀 开始自动迭代", type="primary", use_container_width=True):
            opt_key, scorer_key, gen_key = _get_key(opt_provider_name), _get_key(scorer_provider_name), _get_key(gen_provider_name)
            if not opt_key or not scorer_key or not gen_key:
                st.error("请配置 API Key"); st.stop()

            current_prompt = session.prompt or room.base_prompt
            mode = "prompt" if is_prompt_mode and current_prompt else "script"

            task = create_task(room.id, "auto_iterate", {
                "room_id": room.id,
                "session_id": session.id,
                "mode": mode,
                "threshold": threshold,
                "max_rounds": int(max_rounds),
                "weight_config": new_wc,
                "scorer": {"provider": scorer_provider_name, "key": scorer_key, "model": scorer_model_name},
                "optimizer": {"provider": opt_provider_name, "key": opt_key, "model": opt_model_name},
                "generator": {"provider": gen_provider_name, "key": gen_key, "model": gen_model_name},
            }, desc=f"「{room.name}」{mode}自动迭代 {int(max_rounds)}轮")
            st.success(f"后台迭代已启动（任务 {task.id}）")
            _time.sleep(1)
            st.rerun()

# --- G: 胜出方案列表 ---
st.divider()
st.subheader("🏆 胜出方案")
candidates = list_candidates(room)
if candidates:
    for c in candidates:
        baseline_tag = " ⭐基线" if c.is_baseline else ""
        with st.expander(f"{c.mode} | 分数 {c.total_score:.1f} | {c.rounds}轮 | {c.created_at[:16].replace('T',' ')}{baseline_tag}"):
            st.text_area("内容", c.content, height=200, key=f"cand_{c.id}", disabled=True)
            if c.generated_script:
                st.text_area("生成的脚本", c.generated_script, height=150, key=f"cand_script_{c.id}", disabled=True)
            btn_cols = st.columns(3)
            with btn_cols[0]:
                script_text = c.generated_script if c.mode == "prompt" and c.generated_script else c.content
                excel_data = script_to_excel_bytes(script_text)
                st.download_button("📥 下载Excel", excel_data, f"{room.name}_脚本_{c.id}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_{c.id}")
            with btn_cols[1]:
                if c.mode == "prompt":
                    st.download_button("📥 提示词", c.content.encode("utf-8"), f"{room.name}_提示词_{c.id}.txt",
                                       "text/plain", key=f"dl_prompt_{c.id}")
            with btn_cols[2]:
                if c.is_baseline:
                    if st.button("❌ 取消基线", key=f"unbaseline_{c.id}"):
                        import json as _json
                        c.is_baseline = False
                        c_path = room.candidates_dir() / f"{c.id}.json"
                        c_path.write_text(_json.dumps(c.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                        room.baseline_session_id = ""
                        room.save()
                        st.rerun()
                else:
                    if st.button(f"⭐ 设为基线", key=f"baseline_{c.id}"):
                        set_baseline(room, c)
                        st.rerun()

            if c.is_baseline:
                st.divider()
                st.write("**从此基线继续迭代**")
                c_script = c.generated_script if c.mode == "prompt" and c.generated_script else c.content
                c_scores = c.static_scores or {}
                cont_mode = st.radio("模式", ["手动单次", "自动多轮"], horizontal=True, key=f"cont_mode_{c.id}")

                if cont_mode == "手动单次":
                    if st.button("🧗 继续优化一轮", key=f"cont_manual_{c.id}", type="primary", use_container_width=True):
                        opt_key, scorer_key = _get_key(opt_provider_name), _get_key(scorer_provider_name)
                        if not opt_key or not scorer_key:
                            st.error("请配置 API Key"); st.stop()
                        try:
                            optimizer = get_provider(opt_provider_name, opt_key, opt_model_name)
                            scorer_inst = get_provider(scorer_provider_name, scorer_key, scorer_model_name)
                            from rubric import get_effective_weights
                            static_dims, _ = get_effective_weights(new_wc)
                            cands_list = [{"id": d["id"], "name": d["name"], "score": c_scores.get(d["id"], 0),
                                           "gain": (10 - c_scores.get(d["id"], 0)) * d["weight"]}
                                          for d in static_dims if d["weight"] > 0]
                            dim_target = max(cands_list, key=lambda x: x["gain"])
                            st.write(f"优化维度: **{dim_target['name']}**（{dim_target['score']}/10，潜在增益 {dim_target['gain']:.0f}）")
                            with st.spinner("生成优化方案..."):
                                if c.mode == "prompt":
                                    new_content = generate_prompt_improvement(c.content, c_script, dim_target, c_scores,
                                                                              state.locked_constraints, optimizer, room.product_info,
                                                                              original_prompt=room.original_prompt)
                                    st.write("✓ 提示词优化完成")
                                    new_script = generate_script_from_prompt(new_content, optimizer, baseline_script=c_script)
                                else:
                                    new_content = generate_improvement(c_script, dim_target, c_scores, state.locked_constraints, optimizer)
                                    new_script = new_content
                                    st.write("✓ 脚本优化完成")
                            with st.expander("查看优化结果"):
                                if c.mode == "prompt":
                                    st.text_area("优化后提示词", new_content, height=150, key=f"cont_prompt_{c.id}", disabled=True)
                                st.text_area("优化后脚本", new_script[:2000], height=200, key=f"cont_script_{c.id}", disabled=True)
                            with st.spinner("独立评分中..."):
                                dwell = session.metrics.get("dwell_time", 0)
                                nr = score_script(new_script, scorer_inst, state.locked_constraints, new_wc, dwell_seconds=dwell)
                                all_metrics = [s.metrics for s in sessions]
                                new_eff, _ = compute_effect_score(session.metrics, state.effect_baselines, new_wc, all_sessions_metrics=all_metrics)
                                new_total = compute_total_score(nr["static_score"], new_eff)
                            st.write(f"静态: {nr['static_score']:.1f} + 实效: {new_eff:.1f} = **{new_total:.1f}**")
                            st.write(f"旧分: {c.total_score:.1f} → 新分: {new_total:.1f}")
                            if new_total > c.total_score:
                                st.success(f"✅ +{new_total - c.total_score:.1f}")
                                new_cand = Candidate(
                                    id=uuid.uuid4().hex[:8], session_id=session.id, mode=c.mode,
                                    content=new_content, generated_script=new_script if c.mode == "prompt" else "",
                                    total_score=new_total, static_scores=nr["scores"], effect_scores=c.effect_scores or {},
                                    created_at=__import__("datetime").datetime.now().isoformat(), rounds=c.rounds + 1,
                                )
                                save_candidate(room, new_cand)
                                st.info(f"新方案: {new_cand.id}")
                                st.rerun()
                            else:
                                st.error("❌ 未提升，回滚")
                        except Exception as e:
                            st.error(f"出错: {e}")

                else:
                    cont_col1, cont_col2 = st.columns(2)
                    with cont_col1:
                        cont_threshold = st.number_input("提升阈值(%)", 1.0, 100.0, 10.0, 1.0, key=f"cont_th_{c.id}")
                    with cont_col2:
                        cont_rounds = st.number_input("最大轮数", 1, 50, 10, 1, key=f"cont_rd_{c.id}")
                    if st.button("🚀 继续自动迭代", key=f"cont_auto_{c.id}", type="primary", use_container_width=True):
                        opt_key, scorer_key, gen_key = _get_key(opt_provider_name), _get_key(scorer_provider_name), _get_key(gen_provider_name)
                        if not opt_key or not scorer_key or not gen_key:
                            st.error("请配置 API Key"); st.stop()
                        task = create_task(room.id, "continue_iterate", {
                            "room_id": room.id,
                            "session_id": session.id,
                            "candidate_id": c.id,
                            "mode": c.mode,
                            "threshold": cont_threshold,
                            "max_rounds": int(cont_rounds),
                            "weight_config": new_wc,
                            "scorer": {"provider": scorer_provider_name, "key": scorer_key, "model": scorer_model_name},
                            "optimizer": {"provider": opt_provider_name, "key": opt_key, "model": opt_model_name},
                            "generator": {"provider": gen_provider_name, "key": gen_key, "model": gen_model_name},
                        }, desc=f"「{room.name}」从{c.total_score:.1f}分继续迭代 {int(cont_rounds)}轮")
                        st.success(f"后台继续迭代已启动（任务 {task.id}）")
                        _time.sleep(1)
                        st.rerun()
else:
    st.info("暂无胜出方案。运行优化后自动保存。")

# --- F: 锁定 + 下一轮提示词 ---
st.divider()
st.subheader("🔒 锁定要素 & 生成下一轮提示词")
if state.locked_constraints:
    for c in state.locked_constraints:
        st.write(f"- **{c['element']}** — {c['reason']}")
manual_element = st.text_input("手动添加锁定要素")
manual_reason = st.text_input("原因")
confirmed_locks = []
if manual_element and manual_reason:
    confirmed_locks.append({"element": manual_element, "reason": manual_reason})
if st.button("🔒 确认锁定并生成下一轮提示词", type="primary", use_container_width=True):
    opt_key = _get_key(opt_provider_name)
    if not opt_key:
        st.error("请配置 API Key"); st.stop()
    new_state = ratchet_step(session, state, confirmed_locks)
    new_state.save(room.ratchet_state_path())
    targets = get_improvement_targets(comparison)
    gen_prompt = build_generation_prompt(
        locked_constraints=new_state.locked_constraints, improvement_targets=targets,
        baselines=new_state.baselines, session_count=new_state.iteration_count)
    st.success(f"棘轮已更新！迭代 #{new_state.iteration_count}")
    with st.spinner("生成下一轮优化提示词..."):
        optimizer = get_provider(opt_provider_name, opt_key, opt_model_name)
        next_prompt = optimizer.generate(gen_prompt, system=SYSTEM_PROMPT)
        st.markdown(next_prompt)
        st.text_area("复制提示词", next_prompt, height=300)

with st.expander("📜 审计日志"):
    log = audit.load_log(room.id)
    st.dataframe(log) if log else st.info("暂无记录")
