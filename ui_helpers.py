"""Shared UI components for Streamlit pages."""
import random
import streamlit as st
from datetime import datetime
from config import OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, get_default_models
from llm import PROVIDERS
from models import Session
from data_io import new_session_id, save_session
from zmeng_api import fetch_task_content
from task_manager import create_task


def import_sessions_from_api(room, rooms_data, save_prompt=True):
    """Import sessions from zmeng API data. Returns (imported, skipped, new_ids)."""
    has_task = [rd for rd in rooms_data if rd.get("geminiTaskId")]
    progress = st.progress(0, text="导入中...")
    imported = 0
    skipped = 0
    new_ids = []
    prompt_saved = False

    for i, rd in enumerate(has_task):
        progress.progress((i + 1) / len(has_task), text=f"导入 {i+1}/{len(has_task)}")
        content = fetch_task_content(rd["geminiTaskId"])
        if not content or not content.get("scripts"):
            skipped += 1
            continue
        if save_prompt and not prompt_saved and content.get("prompt"):
            room.original_prompt = content["prompt"]
            room.base_prompt = content["prompt"]
            room.save()
            st.session_state.pop(f"orig_prompt_{room.id}", None)
            st.session_state.pop(f"prompt_{room.id}", None)
            prompt_saved = True
        metrics = {k: v for k, v in rd.items()
                   if k not in ("roomId", "hostName", "openTime", "geminiTaskId", "duration")}
        sc = random.choice(content["scripts"])
        session = Session(
            id=new_session_id(),
            timestamp=rd["openTime"] or datetime.now().isoformat(),
            script=sc["content"], metrics=metrics, room_id=room.id,
            notes=f"API: {rd['hostName']} room={rd['roomId']} seq={sc['seq']}",
        )
        save_session(session)
        new_ids.append(session.id)
        imported += 1

    progress.empty()
    no_script = len(rooms_data) - len(has_task)
    st.success(f"✅ 导入 {imported} 场（跳过 {no_script} 场无脚本、{skipped} 场获取失败）")
    if prompt_saved:
        st.info("✅ 已保存原始提示词")
    return imported, skipped, new_ids


def scorer_selector(key_prefix):
    """Render scorer model selector widgets. Returns (provider, model, api_key)."""
    api_keys = {"openai": OPENAI_API_KEY, "anthropic": ANTHROPIC_API_KEY,
                "google（代理）": GOOGLE_API_KEY, "google（官方）": GOOGLE_API_KEY}
    prov_keys = list(PROVIDERS.keys())
    defs = get_default_models()
    default_idx = prov_keys.index(defs["scorer"]["provider"]) if defs["scorer"]["provider"] in prov_keys else 0
    prov = st.selectbox("评分提供商", prov_keys, index=default_idx, key=f"{key_prefix}_prov")
    models = PROVIDERS[prov]["models"]
    model_idx = models.index(defs["scorer"]["model"]) if prov == defs["scorer"]["provider"] and defs["scorer"]["model"] in models else 0
    model = st.selectbox("评分模型", models, index=model_idx, key=f"{key_prefix}_model")
    key = api_keys.get(prov, "")
    if not key:
        key = st.text_input("API Key", type="password", key=f"{key_prefix}_key")
    return prov, model, key


def launch_batch_score(room_id, room_name, provider, key, model,
                       desc="", session_ids=None, unscored_only=False):
    """Create a batch_score background task. Returns task or None."""
    if not key:
        st.error("请配置API Key")
        return None
    params = {
        "room_id": room_id,
        "scorer": {"provider": provider, "key": key, "model": model},
    }
    if session_ids:
        params["session_ids"] = session_ids
    if unscored_only:
        params["unscored_only"] = True
    if not desc:
        desc = f"「{room_name}」批量评分"
    task = create_task(room_id, "batch_score", params, desc=desc)
    st.success(f"后台评分已启动（任务 {task.id}）")
    return task
