import streamlit as st
import sys
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    SUPPORTED_LANGUAGES, SUPPORTED_COUNTRIES, DATA_DIR,
    api_key_for, get_default_models,
)
from llm import get_provider, PROVIDERS
from distill_engine import (
    distill_single, distill_multiple, ratchet_distill,
    fuse_style_into_prompt, save_style_prompt, list_style_prompts,
    rename_style_prompt, delete_style_prompt, abbreviate_product_name,
)
from transcribe import transcribe_audio
from capture import check_live, start_capture, stop_capture, is_capturing, get_capture_info

st.set_page_config(page_title="复刻蒸馏", page_icon="🧪", layout="wide")
st.title("🧪 复刻蒸馏")
st.markdown("从口播稿/录像中棘轮迭代蒸馏出风格提示词，保存到风格库；可把风格融合进直播间提示词。")

if "rk_collected" not in st.session_state:
    st.session_state.rk_collected = []  # {id, source, label, text, selected}

def _add_item(source, label, text):
    st.session_state.rk_collected.append({
        "id": f"{source}_{len(st.session_state.rk_collected)}_{datetime.now().strftime('%H%M%S')}",
        "source": source, "label": label, "text": text, "selected": True,
    })

tab_collect, tab_fuse, tab_lib = st.tabs(["① 采集 + 蒸馏", "② 融合进直播间提示词", "③ 风格库"])

# PLACEHOLDER_COLLECT
with tab_collect:
    src_video, src_text, src_file, src_live, src_kalo = st.tabs(
        ["📹 上传录像", "📝 粘贴脚本", "📄 上传文件", "📡 TikTok直播", "🔍 Kalodata搜索"])

    with src_video:
        up_v = st.file_uploader("视频文件", type=["mp4", "mov", "avi", "mkv", "webm"], key="rk_vid")
        lang_v = st.selectbox("视频语言", list(SUPPORTED_LANGUAGES.keys()),
                              format_func=lambda x: SUPPORTED_LANGUAGES[x], key="rk_vid_lang")
        if up_v and st.button("提取并加入素材", key="rk_vid_btn"):
            with st.spinner("提取音频并转文字..."):
                with tempfile.NamedTemporaryFile(suffix=Path(up_v.name).suffix, delete=False) as tmp:
                    tmp.write(up_v.read()); tmp_path = Path(tmp.name)
                audio_path = tmp_path.with_suffix(".mp3")
                subprocess.run(["ffmpeg", "-i", str(tmp_path), "-vn", "-acodec",
                                "libmp3lame", "-ab", "128k", str(audio_path), "-y"], capture_output=True)
                if audio_path.exists():
                    prog = st.progress(0)
                    text = transcribe_audio(audio_path, language=lang_v,
                                            progress_callback=lambda p, m: prog.progress(p, text=m))
                    prog.empty()
                    if text.strip():
                        _add_item("视频", up_v.name, text); st.success(f"已加入：{len(text)}字")
                    else:
                        st.error("未提取到文字")
                    tmp_path.unlink(missing_ok=True); audio_path.unlink(missing_ok=True)
                else:
                    st.error("音频提取失败，请确认 ffmpeg 已安装"); tmp_path.unlink(missing_ok=True)

    with src_text:
        txt = st.text_area("粘贴口播稿", height=240, key="rk_paste")
        lbl = st.text_input("标签", value="粘贴脚本", key="rk_paste_lbl")
        if txt and st.button("加入素材", key="rk_paste_btn"):
            _add_item("文字", lbl, txt); st.success(f"已加入：{len(txt)}字")

    with src_file:
        up_f = st.file_uploader("文本文件", type=["txt"], key="rk_file")
        if up_f and st.button("加入素材", key="rk_file_btn"):
            content = up_f.read().decode("utf-8")
            if content.strip():
                _add_item("文件", up_f.name, content); st.success(f"已加入：{len(content)}字")
            else:
                st.error("文件内容为空")
# PLACEHOLDER_LIVE
    with src_live:
        live_in = st.text_input("TikTok用户名或直播链接",
                                placeholder="@username 或 https://www.tiktok.com/@username/live", key="rk_live")
        lang_l = st.selectbox("语言", list(SUPPORTED_LANGUAGES.keys()),
                              format_func=lambda x: SUPPORTED_LANGUAGES[x], key="rk_live_lang")
        uname = ""
        if live_in:
            if "tiktok.com/@" in live_in:
                uname = live_in.split("@")[-1].split("/")[0]
            elif live_in.startswith("@"):
                uname = live_in[1:]
            else:
                uname = live_in
        if uname:
            st.caption(f"用户名: @{uname}")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("检测直播", key="rk_live_chk"):
                    with st.spinner("检测中..."):
                        st.success(f"@{uname} 正在直播") if check_live(uname) else st.warning(f"@{uname} 未在直播")
            with c2:
                if not is_capturing(uname):
                    if st.button("开始录制", key="rk_live_start", type="primary"):
                        out = DATA_DIR / "live_captures" / f"{uname}_{datetime.now():%Y%m%d_%H%M%S}.mp3"
                        try:
                            start_capture(uname, out); st.success(f"开始录制 → {out.name}"); st.rerun()
                        except RuntimeError as e:
                            st.error(str(e))
                else:
                    info = get_capture_info(uname)
                    if info:
                        el = info["elapsed_seconds"]; st.info(f"录制中 {el//60}分{el%60}秒")
            with c3:
                if is_capturing(uname) and st.button("停止并转写", key="rk_live_stop"):
                    ap = stop_capture(uname)
                    if ap and Path(ap).exists():
                        with st.spinner("转写中..."):
                            prog = st.progress(0)
                            text = transcribe_audio(Path(ap), language=lang_l,
                                                    progress_callback=lambda p, m: prog.progress(p, text=m))
                            prog.empty()
                        if text.strip():
                            _add_item("直播", f"@{uname}", text); st.success(f"已加入：{len(text)}字"); st.rerun()
                        else:
                            st.error("转写失败")
# PLACEHOLDER_KALO
    with src_kalo:
        sub_manual, sub_excel = st.tabs(["手动输入", "Excel批量"])
        with sub_manual:
            st.caption("⚠️ 会打开一个独立的 Chrome 窗口（专给 Kalodata 用，和你日常 Chrome 互不干扰）。首次登录一次，之后自动复用。")
            if st.button("打开 Kalodata 登录窗口", key="rk_kalo_login"):
                with st.spinner("正在打开独立 Chrome 窗口..."):
                    try:
                        from kalodata import open_kalodata_for_login
                        ok = open_kalodata_for_login(timeout_seconds=300)
                        st.success("已登录，可以开始搜索") if ok else st.warning("超时未检测到登录")
                    except Exception as e:
                        import traceback
                        st.error(f"打开失败: {type(e).__name__}: {e}"); st.code(traceback.format_exc())
            kc1, kc2 = st.columns([3, 1])
            with kc1:
                prod = st.text_input("商品名称", placeholder="建议用当地语言", key="rk_kalo_prod")
            with kc2:
                ctry = st.selectbox("国家", list(SUPPORTED_COUNTRIES.keys()),
                                    format_func=lambda x: SUPPORTED_COUNTRIES[x], key="rk_kalo_ctry")
            vcount = st.slider("视频数量", 1, 5, 3, key="rk_kalo_cnt")
            if prod and st.button("搜索并加入素材", key="rk_kalo_btn", type="primary"):
                with st.spinner(f"Kalodata搜索 [{SUPPORTED_COUNTRIES[ctry]}] {prod}..."):
                    try:
                        from kalodata import search_and_get_scripts
                        scs = search_and_get_scripts(prod, count=vcount, country=ctry)
                        if scs:
                            for i, s in enumerate(scs):
                                _add_item("Kalodata", f"{prod} #{i+1}", s)
                            st.success(f"加入 {len(scs)} 份口播稿")
                            if not st.session_state.get("rk_product_info"):
                                st.session_state.rk_product_info = prod
                        else:
                            st.warning("未找到口播稿")
                    except Exception as e:
                        import traceback
                        st.error(f"搜索失败: {type(e).__name__}: {e}"); st.code(traceback.format_exc())
        with sub_excel:
            st.caption("Excel格式：第1行表头，第2行示例，第3行起为实际数据，需含「产品名称」列")
            up_x = st.file_uploader("Excel文件", type=["xlsx", "xls"], key="rk_excel")
            if up_x:
                import pandas as pd
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(up_x.read()); xpath = tmp.name
                df = pd.read_excel(xpath, header=0); Path(xpath).unlink(missing_ok=True)
                ncol = next((c for c in df.columns if "产品名称" in str(c) or "商品名" in str(c)
                             or "product" in str(c).lower()), None)
                if ncol is None:
                    st.error("未找到「产品名称」列")
                else:
                    prods = df[ncol].dropna().tolist()
                    if len(prods) > 1:
                        prods = prods[1:]
                    st.dataframe(df[[ncol]].dropna()); st.info(f"找到 {len(prods)} 个商品")
                    ex1, ex2 = st.columns(2)
                    with ex1:
                        xcnt = st.slider("每商品视频数", 1, 5, 3, key="rk_excel_cnt")
                    with ex2:
                        xctry = st.selectbox("国家", list(SUPPORTED_COUNTRIES.keys()),
                                             format_func=lambda x: SUPPORTED_COUNTRIES[x], key="rk_excel_ctry")
                    if st.button("批量搜索", key="rk_excel_btn", type="primary"):
                        prog = st.progress(0); total = 0
                        for i, p in enumerate(prods):
                            p = str(p).strip()
                            if not p:
                                continue
                            prog.progress((i + 1) / len(prods), text=f"搜索: {p}")
                            try:
                                from kalodata import search_and_get_scripts
                                for j, s in enumerate(search_and_get_scripts(p, count=xcnt, country=xctry)):
                                    _add_item("Kalodata", f"{p} #{j+1}", s); total += 1
                            except Exception:
                                continue
                        prog.empty(); st.success(f"批量完成，加入 {total} 份口播稿")
# PLACEHOLDER_MATLIB
    st.divider()
    st.subheader(f"素材库 — {len(st.session_state.rk_collected)} 份（勾选要参与蒸馏的）")
    if st.session_state.rk_collected:
        b1, b2, b3 = st.columns([1, 1, 6])
        with b1:
            if st.button("全选", key="rk_all"):
                for it in st.session_state.rk_collected:
                    it["selected"] = True
                st.rerun()
        with b2:
            if st.button("全不选", key="rk_none"):
                for it in st.session_state.rk_collected:
                    it["selected"] = False
                st.rerun()
        with b3:
            if st.button("清空素材库", key="rk_clear"):
                st.session_state.rk_collected = []; st.rerun()
        for i, it in enumerate(st.session_state.rk_collected):
            cs, ci, cd = st.columns([1, 8, 1])
            with cs:
                it["selected"] = st.checkbox(" ", value=it["selected"],
                                             key=f"rk_sel_{it['id']}", label_visibility="collapsed")
            with ci:
                with st.expander(f"[{it['source']}] {it['label']} — {len(it['text'])}字"):
                    st.text_area("内容", it["text"], height=150, key=f"rk_view_{it['id']}", disabled=True)
            with cd:
                if st.button("✕", key=f"rk_del_{it['id']}"):
                    st.session_state.rk_collected.pop(i); st.rerun()
    else:
        st.info("从上方任意标签页加入素材")

    selected = [it for it in st.session_state.rk_collected if it["selected"]]
    if selected:
        st.divider()
        st.subheader(f"棘轮蒸馏 — 已选 {len(selected)} 份素材")
        _defaults = get_default_models()
        _provs = list(PROVIDERS.keys())
        _dd = _defaults["distill"]
        _pidx = _provs.index(_dd["provider"]) if _dd["provider"] in _provs else 0
        m1, m2 = st.columns(2)
        with m1:
            prov_name = st.selectbox("LLM", _provs, index=_pidx, key="rk_distill_prov")
        with m2:
            _ms = PROVIDERS[prov_name]["models"]
            _midx = _ms.index(_dd["model"]) if _dd["model"] in _ms else 0
            model = st.selectbox("模型", _ms, index=_midx, key="rk_distill_model")
        st.caption("大模型配置复用达尔文（API Key 与代理已自动加载）")
        api_key = api_key_for(prov_name)

        product_info = st.text_input("商品信息（用于命名和蒸馏）",
                                     value=st.session_state.get("rk_product_info", ""), key="rk_prodinfo")
        default_name = abbreviate_product_name(product_info) if product_info else "风格"
        prompt_name = st.text_input("风格提示词命名（默认商品名缩写，可改）",
                                    value=default_name, key="rk_name")
        r1, r2, r3 = st.columns(3)
        with r1:
            use_ratchet = st.checkbox("启用棘轮迭代", value=True, key="rk_use_ratchet")
        with r2:
            target = st.slider("目标得分", 60, 95, 85, key="rk_target", disabled=not use_ratchet)
        with r3:
            max_it = st.slider("最大迭代", 1, 8, 4, key="rk_maxit", disabled=not use_ratchet)
# PLACEHOLDER_DISTILL_RUN
        if st.button("开始蒸馏", type="primary", key="rk_distill_go"):
            if not api_key:
                st.error(f"请配置 {prov_name} 的 API Key")
            elif not prompt_name.strip():
                st.error("请填写风格提示词命名")
            else:
                llm = get_provider(prov_name, api_key, model)
                texts = [it["text"] for it in selected]
                _gen = _defaults["generator"]; _sco = _defaults["scorer"]
                gen_llm = get_provider(_gen["provider"], api_key_for(_gen["provider"]), _gen["model"])
                eval_llm = get_provider(_sco["provider"], api_key_for(_sco["provider"]), _sco["model"])

                if use_ratchet:
                    box = st.empty(); logs = []
                    def _cb(it_n, status, data):
                        logs.append(f"[{it_n}] {status}: {data.get('msg','')}")
                        box.info("\n".join(logs[-8:]))
                    with st.spinner("棘轮迭代蒸馏中..."):
                        res = ratchet_distill(texts, llm, target_score=target, max_iterations=max_it,
                                              product_info=product_info, progress_callback=_cb,
                                              gen_llm=gen_llm, eval_llm=eval_llm)
                    box.empty()
                    final_prompt = res["final_prompt"]; iters = res["iterations"]
                    st.success(f"蒸馏完成！最终得分 {res['final_score']} | {len(iters)}轮 | {res['stopped_reason']}")
                    with st.expander(f"查看迭代过程（{len(iters)}轮）"):
                        for it in iters:
                            sc = it["evaluation"].get("scores", {})
                            st.markdown(f"**第 {it['iteration']} 轮 — 得分 {it['evaluation'].get('overall_score',0)}**")
                            if sc:
                                cols = st.columns(5)
                                for col, (k, lbl) in zip(cols, [("content_coverage","内容"),
                                        ("style_similarity","风格"),("rhythm_similarity","节奏"),
                                        ("persuasion_similarity","说服"),("emotion_similarity","情感")]):
                                    col.metric(lbl, sc.get(k, 0))
                            for g in it["evaluation"].get("gaps", []):
                                st.markdown(f"- {g}")
                    src_info = {"type": "复刻蒸馏", "detail": f"{len(selected)}份素材，棘轮{len(iters)}轮，得分{res['final_score']}",
                                "items": [{"source": it["source"], "label": it["label"]} for it in selected]}
                    save_style_prompt(prompt_name.strip(), final_prompt, src_info)
                    st.markdown("### 最终风格提示词（已保存到风格库）")
                    st.code(final_prompt, language="markdown")
                else:
                    with st.spinner("蒸馏中..."):
                        result = (distill_single(texts[0], llm, product_info) if len(texts) == 1
                                  else distill_multiple(texts, llm, product_info))
                    src_info = {"type": "复刻蒸馏", "detail": f"{len(selected)}份素材（单次）",
                                "items": [{"source": it["source"], "label": it["label"]} for it in selected]}
                    save_style_prompt(prompt_name.strip(), result, src_info)
                    st.success("蒸馏完成！已保存到风格库")
                    st.code(result, language="markdown")
# PLACEHOLDER_FUSE

with tab_fuse:
    st.markdown("填入直播间提示词，选择一套已保存的风格提示词，LLM 会把风格融合进去，输出最终提示词供下载。")
    styles = list_style_prompts()
    if not styles:
        st.info("风格库为空，请先在「① 采集 + 蒸馏」生成风格提示词。")
    else:
        base_prompt = st.text_area("直播间提示词", height=240,
                                   placeholder="粘贴直播间的运营提示词...", key="rk_fuse_base")
        names = [s["name"] for s in styles]
        pick = st.selectbox("选择风格提示词", names, key="rk_fuse_pick")
        picked = styles[names.index(pick)]
        with st.expander("查看选中的风格提示词"):
            st.code(picked.get("distill_prompt", ""), language="markdown")

        _fdefaults = get_default_models()
        _fprovs = list(PROVIDERS.keys())
        _fdd = _fdefaults["distill"]
        _fpidx = _fprovs.index(_fdd["provider"]) if _fdd["provider"] in _fprovs else 0
        fc1, fc2 = st.columns(2)
        with fc1:
            fprov = st.selectbox("融合用 LLM", _fprovs, index=_fpidx, key="rk_fuse_prov")
        with fc2:
            _fms = PROVIDERS[fprov]["models"]
            _fmidx = _fms.index(_fdd["model"]) if _fdd["model"] in _fms else 0
            fmodel = st.selectbox("模型", _fms, index=_fmidx, key="rk_fuse_model")

        if st.button("融合生成最终提示词", type="primary", key="rk_fuse_go"):
            if not base_prompt.strip():
                st.error("请填写直播间提示词")
            elif not api_key_for(fprov):
                st.error(f"请配置 {fprov} 的 API Key")
            else:
                with st.spinner("融合中..."):
                    llm = get_provider(fprov, api_key_for(fprov), fmodel)
                    fused = fuse_style_into_prompt(base_prompt, picked.get("distill_prompt", ""), llm)
                st.success("融合完成！")
                st.markdown("### 最终提示词")
                st.code(fused, language="markdown")
                st.download_button("下载最终提示词", fused,
                                   file_name=f"融合_{pick}.md", mime="text/markdown", key="rk_fuse_dl")

# PLACEHOLDER_LIB

with tab_lib:
    st.markdown("已保存的风格提示词。可重命名、下载、删除。")
    lib = list_style_prompts()
    if not lib:
        st.info("风格库为空。")
    else:
        st.caption(f"共 {len(lib)} 套风格提示词")
        for p in lib:
            with st.expander(f"🎨 {p['name']} — {p['created_at'][:16].replace('T',' ')}"):
                src = p.get("source_info", {})
                st.caption(f"来源: {src.get('type','')} | {src.get('detail','')}")
                items = src.get("items", [])
                if items:
                    st.caption("素材: " + " · ".join(f"[{it['source']}]{it['label']}" for it in items))
                st.code(p["distill_prompt"], language="markdown")
                lc1, lc2, lc3 = st.columns([3, 1, 1])
                with lc1:
                    new_name = st.text_input("重命名", value=p["name"], key=f"rk_rn_{p['file_path']}")
                    if st.button("保存名称", key=f"rk_rnbtn_{p['file_path']}"):
                        rename_style_prompt(p["file_path"], new_name.strip() or p["name"])
                        st.success("已重命名"); st.rerun()
                with lc2:
                    st.download_button("下载", p["distill_prompt"], file_name=f"{p['name']}.md",
                                       mime="text/markdown", key=f"rk_dl_{p['file_path']}")
                with lc3:
                    if st.button("删除", key=f"rk_delp_{p['file_path']}"):
                        delete_style_prompt(p["file_path"]); st.rerun()
