import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="达尔文 — 直播脚本棘轮优化", page_icon="🧬", layout="wide")

# --- 登录认证 ---
_AUTH_FILE = Path(__file__).parent / "data" / ".auth"
_cfg_file = Path(__file__).parent / "config.json"
USERS = json.loads(_cfg_file.read_text(encoding="utf-8")).get("USERS", {}) if _cfg_file.exists() else {}


def _check_auth():
    if st.session_state.get("authenticated"):
        return True
    if _AUTH_FILE.exists():
        user = _AUTH_FILE.read_text(encoding="utf-8").strip()
        if user in USERS:
            st.session_state["authenticated"] = True
            st.session_state["user"] = user
            return True
    return False


if not _check_auth():
    st.title("🧬 达尔文 — 登录")
    with st.form("login"):
        email = st.text_input("邮箱")
        password = st.text_input("密码", type="password")
        if st.form_submit_button("登录", type="primary"):
            if USERS.get(email) == password:
                st.session_state["authenticated"] = True
                st.session_state["user"] = email
                _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
                _AUTH_FILE.write_text(email, encoding="utf-8")
                st.rerun()
            else:
                st.error("邮箱或密码错误")
    st.stop()

# --- 已登录 ---
st.title("🧬 达尔文")
st.subheader("直播脚本棘轮优化系统")

_hdr1, _hdr2, _hdr3, _hdr4 = st.columns([3, 1, 1, 1])
with _hdr1:
    st.caption(f"当前用户：{st.session_state.get('user', '')}")
with _hdr2:
    if st.button("⚙️ API配置"):
        st.session_state["show_config"] = not st.session_state.get("show_config", False)
with _hdr3:
    if st.button("📖 使用说明"):
        st.session_state["show_help"] = not st.session_state.get("show_help", False)
with _hdr4:
    if st.button("退出登录"):
        st.session_state["authenticated"] = False
        if _AUTH_FILE.exists():
            _AUTH_FILE.unlink()
        st.rerun()

if st.session_state.get("show_help"):
    with st.container(border=True):
        tab_quick, tab_detail = st.tabs(["快速入门", "详细功能"])
        with tab_quick:
            st.markdown("""
### 5分钟快速入门

1. **配置 API** — 展开下方「全局 API 配置」，填入 Google/Anthropic 的 Key 并保存
2. **创建直播间** — 进入「直播间管理」→ 新建直播间 → 输入名称和产品信息
3. **导入脚本** — 选择「API自动获取」→ 输入主播ID（如 cottondaylive1）→ 搜索 → 导入
4. **批量评分** — 导入完成后点「开始批量评分」，系统后台自动评分并选出基线
5. **自动优化** — 进入「棘轮分析」→ 选择直播间和场次 → 点「开始自动迭代」
6. **查看结果** — 迭代完成后在「胜出方案」区域查看优化后的脚本和提示词

所有长时间任务（评分、迭代）都在后台运行，可以切换页面不影响。
""")
        with tab_detail:
            st.markdown("""
### 系统架构

**棘轮理论**：锁定每次迭代中被验证有效的脚本元素，确保优化成果不回退。

**双层评分体系**：
- 静态评分（LLM分析脚本质量）：8个维度 × 权重，满分45分
- 实效评分（真实直播数据）：CTR + 停留时长，满分40分

**8个评分维度**：
| 维度 | 权重 | 说明 |
|------|------|------|
| 黄金3秒 | 7 | 每个循环前3秒的Hook强度 |
| 单点卖点 | 5 | 每个循环是否只聚焦一个卖点 |
| 循环结构 | 7 | 是否由15-30秒独立循环组成 |
| 行动号召CTA | 7 | 每个循环末尾的CTA明确度 |
| 节奏密度 | 5 | 句子短而密集，无废话 |
| 痛点速击 | 5 | 前5秒是否戳中痛点 |
| 价格锚点 | 5 | 是否建立价格对比 |
| 入场信号 | 4 | 新观众能否立即理解上下文 |

### 页面功能

**直播间管理**
- 新建直播间，导入历史脚本（API/Excel/手动）
- 批量评分：后台运行，自动选最高分为基线
- 管理原始提示词和基线提示词

**棘轮分析**
- 选择直播间和场次，查看评分雷达图
- 单维度手动优化或自动多轮迭代
- 提示词模式：优化生成脚本的提示词（推荐）
- 脚本模式：直接优化脚本文本
- 胜出方案自动设为新基线，可继续迭代

**模型配置**（侧边栏）
- 评分模型：默认 Gemini 3.1 Pro（代理）
- 提示词/脚本优化：默认 Claude Opus 4.7
- 脚本生成：默认 Gemini 3.0 Flash（代理）

### 后台任务
- 批量评分和自动迭代在后台子进程运行
- 切换页面不影响任务执行
- 可随时点「停止」，停止后以当前最高分保存
- 新最高分自动当选基线方案
""")


# --- 全局 API 配置 ---
import json
from pathlib import Path
from config import BASE_DIR

CONFIG_FILE = BASE_DIR / "config.json"


def load_api_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_api_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


if st.session_state.get("show_config"):
    with st.container(border=True):
        st.subheader("⚙️ 全局 API 配置")
        cfg = load_api_config()
        st.caption("修改后点保存，所有页面生效。")

        from llm import PROVIDERS
        _all_prov = list(PROVIDERS.keys())
        _all_models = []
        for p in _all_prov:
            for m in PROVIDERS[p]["models"]:
                _all_models.append(f"{p}/{m}")

        st.markdown("**默认模型**")
        mc1, mc2, mc3 = st.columns(3)
        _scorer_default = cfg.get("DEFAULT_SCORER", "google（代理）/gemini-3.1-pro-preview")
        _opt_default = cfg.get("DEFAULT_OPTIMIZER", "anthropic/claude-opus-4-7")
        _gen_default = cfg.get("DEFAULT_GENERATOR", "google（代理）/gemini-3-flash-preview")
        with mc1:
            scorer_choice = st.selectbox("评分模型", _all_models, index=_all_models.index(_scorer_default) if _scorer_default in _all_models else 0, key="cfg_scorer")
        with mc2:
            opt_choice = st.selectbox("优化模型", _all_models, index=_all_models.index(_opt_default) if _opt_default in _all_models else 0, key="cfg_opt")
        with mc3:
            gen_choice = st.selectbox("生成模型", _all_models, index=_all_models.index(_gen_default) if _gen_default in _all_models else 0, key="cfg_gen")

        st.markdown("**API Keys**")
        c1, c2 = st.columns(2)
        with c1:
            google_key = st.text_input("Google API Key", value=cfg.get("GOOGLE_API_KEY", ""), type="password", key="cfg_google")
            google_proxy_key = st.text_input("Google 代理 Key (fucheers)", value=cfg.get("GOOGLE_PROXY_KEY", ""), type="password", key="cfg_gproxy")
            google_proxy_url = st.text_input("Google 代理 URL", value=cfg.get("GOOGLE_PROXY_URL", "https://www.fucheers.top"), key="cfg_gproxy_url")
            anthropic_key = st.text_input("Anthropic API Key", value=cfg.get("ANTHROPIC_API_KEY", ""), type="password", key="cfg_anthropic")
            anthropic_proxy_url = st.text_input("Anthropic 代理 URL", value=cfg.get("ANTHROPIC_PROXY_URL", "https://www.fucheers.top"), key="cfg_aproxy_url")
        with c2:
            openai_key = st.text_input("OpenAI API Key", value=cfg.get("OPENAI_API_KEY", ""), type="password", key="cfg_openai")
            openai_proxy_url = st.text_input("OpenAI 代理 URL", value=cfg.get("OPENAI_PROXY_URL", "https://www.fucheers.top"), key="cfg_oproxy_url")
            zmeng_token = st.text_input("众盟 Auth Token", value=cfg.get("ZMENG_AUTH_TOKEN", ""), type="password", key="cfg_zmeng")
            zmeng_cookie = st.text_area("众盟 Cookie", value=cfg.get("ZMENG_COOKIE", ""), height=68, key="cfg_zmeng_cookie")
        if st.button("💾 保存配置", type="primary"):
            new_cfg = dict(cfg)  # 保留 USERS 等未在 UI 中编辑的字段
            new_cfg.update({
                "GOOGLE_API_KEY": google_key,
                "GOOGLE_PROXY_KEY": google_proxy_key,
                "GOOGLE_PROXY_URL": google_proxy_url,
                "ANTHROPIC_API_KEY": anthropic_key,
                "ANTHROPIC_PROXY_URL": anthropic_proxy_url,
                "OPENAI_API_KEY": openai_key,
                "OPENAI_PROXY_URL": openai_proxy_url,
                "ZMENG_AUTH_TOKEN": zmeng_token,
                "ZMENG_COOKIE": zmeng_cookie,
                "DEFAULT_SCORER": scorer_choice,
                "DEFAULT_OPTIMIZER": opt_choice,
                "DEFAULT_GENERATOR": gen_choice,
            })
            save_api_config(new_cfg)
            import os
            for k, v in new_cfg.items():
                if not k.startswith("DEFAULT_") and isinstance(v, str):
                    os.environ[k] = v
            st.success("配置已保存")

# 启动时从 config.json 加载到环境变量
_saved = load_api_config()
if _saved:
    import os
    for k, v in _saved.items():
        if v and isinstance(v, str):
            os.environ[k] = v

st.divider()

st.markdown("""
**棘轮理论**：每场直播的成功要素被锁定为基线约束，指标只升不降，脚本持续进化。

**工作流程**：
1. **直播间管理** — 创建直播间，导入历史脚本+数据，系统自动评分选基线
2. **棘轮分析** — 独立 AI 评分 → 优先级诊断 → 单维度爬山优化 → 锁定增益
3. **数据看板** — 按直播间查看指标趋势、评分趋势和棘轮进展
""")

st.divider()

from room import list_rooms
from data_io import list_sessions

rooms = list_rooms()
if not rooms:
    st.info("尚无直播间。前往「直播间管理」创建第一个直播间。")
else:
    st.subheader("直播间概览")
    for r in rooms:
        sessions = list_sessions(r.id)
        scored = [s for s in sessions if s.total_score > 0]
        best_score = max((s.total_score for s in scored), default=0)
        cols = st.columns([3, 1, 1, 1])
        cols[0].write(f"**{r.name}**")
        cols[1].metric("场次", len(sessions))
        cols[2].metric("最高分", best_score if best_score else "—")
        cols[3].metric("基线", "✅" if r.baseline_session_id else "—")
