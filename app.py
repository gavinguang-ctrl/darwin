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

1. **配置 API** — 点击右上角「⚙️ API配置」，填入 Google / Anthropic 的 Key 并保存
2. **（可选）全局锁定描述** — 首页下方「🔒 全局锁定提示词描述」填入运营硬性要求（极限词禁区、口径规范等）
3. **创建直播间** — 进入「🏠 直播间管理」→ 标签页「新建直播间」→ 输入名称和产品信息
4. **导入脚本** — 「添加场次」→ 选「API自动获取」→ 输入主播ID（如 cottondaylive1）→ 搜索 → 批量导入
5. **批量评分** — 进入标签页「管理直播间」→ 展开直播间 → 点「📝 批量评分」，系统后台打分并选出基线
6. **自动优化** — 进入「🔧 棘轮分析」→ 选直播间和场次 → 点「🚀 开始自动迭代」
7. **查看结果** — 迭代完成后在「🏆 胜出方案」区域查看优化后的提示词和脚本，可设为新基线继续迭代

所有长时间任务（评分、迭代、翻译）都在后台运行，切换页面不影响。随时点「⏹ 停止」以当前最高分保存。
""")
        with tab_detail:
            st.markdown("""
### 一、系统是什么

达尔文是一套**直播脚本棘轮优化系统**，把你历史直播的脚本 + 真实带货数据喂进来，系统就会：

1. **评分** — 用 LLM 从 8 个静态维度（脚本质量）+ 2 个实效维度（CTR / 停留）打分
2. **选基线** — 最高分场次自动成为基线
3. **迭代** — 针对最弱维度生成新提示词 / 新脚本 → 重评分 → 只保留比基线更好的版本（棘轮永不回退）
4. **去重** — 同一提示词跑多份脚本，自动降低字面重复率（避免被平台判定预录制）
5. **翻译** — 把优化好的中英混排提示词译成目标市场的母语表达（12 种语言 + 货币换算）

所有耗时操作都跑在后台子进程里，可以随时停、切换页面不影响。
""")

            st.markdown("""
### 二、开始之前的三件事

**1. 配置 API Key**
点击页面右上角「⚙️ API配置」，至少填一个 Key：
- Google / Anthropic 官方 Key，或 fucheers 代理 Key（国内网络更稳）
- 同一个面板里可以选「默认评分模型」「默认优化模型」「默认生成模型」，所有页面都会沿用

**2. 全局锁定提示词描述（可选但强烈建议）**
首页下方的「🔒 全局锁定提示词描述」是一段会被**每一次迭代强制注入**的硬性约束。典型用途：
- 合规词禁区："禁用最/第一/唯一/绝对等极限词"
- 品牌规范："所有价格必须带原币种符号；主播自称用『我们』不用『我』"
- 渠道要求："脚本不可出现竞品品牌名；不得承诺治疗效果"

写进这里，优化模型在改写提示词时就**不能**把这些约束改掉或稀释掉。直播间级别可继承或覆盖（进「直播间管理」Tab 3 或棘轮分析页顶部展开「🔒 锁定提示词描述」即可）。

**3. 准备数据**
历史直播脚本 + 对应的 CTR、停留时长数据。系统支持三种导入方式：
- **API 自动获取**：从众盟平台按主播 ID / 直播间 ID 拉取（最省事）
- **Excel 上传**：表头含 `script`, `ctr`, `dwell_time` 等字段
- **手动输入**：适合只有零散几场的情况
""")

            st.markdown("""
### 三、核心概念速查

**棘轮理论**
优化只向前不向后。每轮 LLM 改写后的脚本重新评分，**只有高于基线才保留**，否则回滚。被验证有效的要素（话术、结构、CTA 模板）会被锁进 `locked_constraints`，后续迭代必须保留。

**双层评分**
- **静态评分**（LLM 打分）：8 个维度 × 权重，默认满分 45
- **实效评分**（真实数据）：CTR + 停留时长，默认满分 40

两者加权得到综合总分。权重在棘轮分析页侧边栏可调。

**8 个静态维度**

| 维度 | 默认权重 | 说明 |
|------|---------|------|
| 黄金3秒 | 7 | 每个循环前3秒的 Hook 强度 |
| 单点卖点 | 5 | 每个循环是否只聚焦一个卖点 |
| 循环结构 | 7 | 是否由 15–30 秒独立循环组成 |
| 行动号召CTA | 7 | 每个循环末尾的 CTA 明确度 |
| 节奏密度 | 5 | 句子短而密集，无废话 |
| 痛点速击 | 5 | 前5秒是否戳中痛点 |
| 价格锚点 | 5 | 是否建立价格对比 |
| 入场信号 | 4 | 新观众能否立即理解上下文 |

**提示词模式 vs 脚本模式**

| | 提示词模式（推荐） | 脚本模式 |
|---|---|---|
| 优化对象 | "生成脚本的提示词" | 脚本文本本身 |
| 每轮产物 | 新提示词 + 用它生成的脚本 | 新脚本 |
| 适合场景 | 有基线提示词，要求多次复现 | 只有单个脚本要打磨 |
| 自动去重 | ✅ 自动触发 | ❌ 不触发 |

**优先级 Badge**
综合评分下方的 `🟡 P2 — 原因 · 建议` 是系统根据指标趋势给出的优化优先级提示，P0 最紧急，P3 最低。
""")

            st.markdown("""
### 四、页面详解

#### 🏠 直播间管理

**Tab 1「新建直播间」**
输入直播间名称 + 产品信息（产品卖点、价格带、优惠等）。产品信息会作为上下文注入后续的优化提示词，写详细点能明显提升优化质量。

**Tab 2「添加场次」**
给某个已有直播间增加历史场次，三种方式：
- API 自动获取（按主播 ID 或按直播间 ID 批量拉）
- 上传 Excel
- 手动输入

导入后脚本 + 指标会保存到该直播间，等待评分。

**Tab 3「管理直播间」**（主战场）
每个直播间展开后能做的事：
- 📌 编辑**原始提示词模板**（导入时带的原版，不会被迭代覆盖，保底用）
- 📝 编辑**基线提示词**（当前最优版，会随胜出方案自动更新）
- 🔒 设置**锁定提示词描述**（继承全局 或 本直播间专属）
- 📝 **批量评分** / 重评已评分场次 / 未评分场次单独评分
- 🎯 评分后自动选出**基线场次**
- 🧹 清除脚本 / 🗑️ 删除直播间

#### 🔧 棘轮分析（核心工作台）

进入时先选「直播间」和「场次」，默认选中基线场次。页面自上而下分成几块：

**① 查看脚本**：展开「查看完整脚本」就能看当前场次的全文。

**② 锁定提示词描述**：直播间级配置，支持勾选「使用全局」或覆盖。

**③ 评分展示**：
- 上部：综合总分 + 优先级 badge + 静态/实效分拆分 + 雷达图
- 下部：8 个维度逐一列出分数和 LLM 给出的理由（方便你看到"为什么是这个分"）

**④ 🤖 自动迭代模式**（首选入口）：
- 设提升阈值（默认 10%）和最大轮数（默认 10）
- 点「🚀 开始自动迭代」→ 系统派一个后台子进程：
  1. 找当前最弱维度
  2. 调优化模型生成新提示词 / 新脚本
  3. 调生成模型产出新脚本（仅提示词模式）
  4. 独立重评分
  5. 高于基线 → 保留；否则 → 回滚，该维度连续失败 2 次就跳过
  6. 达标或停滞时结束
- 结束后若有净提升，自动保存为胜出方案 + 自动触发「跨脚本去重」子任务（仅提示词模式）
- 迭代过程中随时可点「⏹ 停止迭代」，以当前最高分保存

**⑤ 🧗 单维度优化**（精细调试）：
- 针对当前最弱维度生成一次改进 → 独立重评 → 决策保留或回滚
- 适合想看"这一步到底改了什么"的情况，结果同样存为胜出方案

**⑥ 🔄 探索性重写**（仅在连续停滞时出现）：
连续 N 次回滚后提示全局重构。点击后会丢弃局部微调，直接请求一次结构性重写。

**⑦ 🏆 胜出方案列表**：
按分数从高到低排列历史所有成功迭代。每个方案展开后可以：
- 👁 查看内容（提示词 + 生成的脚本）
- 📥 下载（xlsx / txt）
- ⭐ 设为新基线（下次迭代从这里继续）
- ▶ 继续迭代（在该方案基础上再跑 N 轮）
- 🌐 **翻译**：选目标语言（12 种），系统起一个后台任务把提示词译成目标市场母语表达（含货币换算），完成后可下载 txt
- 🔄 **跨脚本去重**（仅提示词模式）：用这个提示词并发跑 50 份脚本，度量字面重复率并迭代降低

#### 📊 数据看板

按直播间查看：
- 综合评分趋势
- 各维度评分趋势
- 真实指标（GMV / CTR / 停留 / 转粉率）趋势
- 棘轮锁定的成功要素清单

用于观察"改了几轮后实际效果有没有抬起来"。

#### 📋 后台任务

所有子进程任务的统一看板：
- 运行中的任务（进度、最高分、日志、⏹ 停止按钮）
- 已完成 / 已停止 / 失败的历史任务
- 可清理死进程、可查看完整日志

批量评分、自动迭代、跨脚本去重、翻译全部在这里汇总。
""")

            st.markdown("""
### 五、推荐工作流

**第一次使用**
1. 首页配 API Key → 写全局锁定描述
2. 直播间管理 → 新建直播间 → 填产品信息
3. 添加场次 → API 批量导入 6–10 场历史数据
4. 管理直播间 → 批量评分 → 等后台跑完
5. 棘轮分析 → 选基线场次 → 看雷达图找短板
6. 🚀 自动迭代 10 轮 → 等完成
7. 胜出方案里挑最高分的 → 翻译成目标语言 → 下载 txt 给主播/数字人用

**持续优化**
1. 每场新直播结束后，到直播间管理补一条新场次
2. 批量评分（只评未评分的）
3. 棘轮分析用新场次再跑自动迭代
4. 若已有胜出方案，直接在「胜出方案 → ▶ 继续迭代」基础上叠加

**出海本地化**
1. 跑完优化拿到中文提示词 + 混合外语话术
2. 胜出方案 → 🌐 翻译 → 选目标语言（越南/泰语/英语 等）
3. 下载译文 txt → 检查货币换算是否合理 → 投流
""")

            st.markdown("""
### 六、常见问题

**Q：自动迭代跑了 10 轮一点没提升？**
A：说明当前脚本已接近局部最优。试试：① 调低权重让系统关注新维度；② 到胜出方案点「🔄 探索性重写」；③ 换更强的优化模型（Opus 4.7）。

**Q：迭代后生成的脚本丢了关键要素（比如价格、品牌词）？**
A：把这些要素加到「🔒 锁定提示词描述」里，重跑一次。锁定段会以硬性约束身份注入每一轮，模型不能改。

**Q：翻译后的价格数字看起来怪？**
A：系统会把源币种按实时汇率换算成目标市场货币，并四舍五入到自然锚点（如 ¥1,980 / Rp99.000）。如果源脚本里有占位符 `{price}` 或非价格数字（SKU、评分），系统会保留不动。

**Q：后台任务看起来卡住了？**
A：进「📋 后台任务」页查看实时日志。如果是网络错误，系统会自动补偿轮数继续跑。真卡死就点「⏹ 停止」，已完成部分会保留最高分。

**Q：同一个直播间开两次自动迭代会冲突吗？**
A：不会。每次迭代是独立子进程，但最后一次完成且有净提升的会更新基线。建议先停旧任务再跑新的。
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
            new_cfg = dict(cfg)  # 保留 USERS / GLOBAL_LOCKED_PROMPT 等未在 UI 中编辑的字段
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

# --- 全局锁定提示词描述 ---
with st.container(border=True):
    st.subheader("🔒 全局锁定提示词描述")
    st.caption("这段描述会作为硬性约束注入到每次棘轮迭代的 prompt 里，optimizer 不能修改，每次迭代必须严格遵守。直播间默认继承全局，也可在「直播间管理」或「棘轮分析」侧边栏里单独覆盖。")
    _cur_locked = load_api_config().get("GLOBAL_LOCKED_PROMPT", "")
    _locked_val = st.text_area(
        "锁定描述（可留空）",
        value=_cur_locked,
        height=200,
        placeholder="示例：所有价格保留原币种符号；禁用「最」「第一」「唯一」等极限词；主播自称必须用「我们」不用「我」。",
        key="cfg_locked_prompt",
        label_visibility="collapsed",
    )
    if st.button("💾 保存锁定描述", type="primary", key="save_locked_prompt"):
        _cfg = load_api_config()
        _cfg["GLOBAL_LOCKED_PROMPT"] = _locked_val
        save_api_config(_cfg)
        st.success("全局锁定描述已保存，下一次迭代立即生效")

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
