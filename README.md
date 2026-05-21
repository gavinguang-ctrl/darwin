# 🧬 达尔文 — TikTok 直播脚本棘轮优化系统

基于棘轮理论（Ratchet Theory）的 TikTok AI 数字人直播脚本自动优化系统。通过多维度评分 + 爬山迭代，持续提升直播脚本质量，锁定每次迭代的成功要素，确保优化成果不回退。

## 核心特性

- **直播间管理** — 创建直播间，通过众盟 API / Excel / 手动导入历史脚本和数据；支持冷启动模式（无历史数据的全新直播间）
- **多维度评分** — 8 维度静态评分 + 实效数据预估，支持自定义权重；可选「全部观众」或「成交用户」评分时间窗口
- **棘轮自动迭代** — 后台爬山优化，提示词模式或脚本直改模式，支持参考脚本段落注入
- **锁定约束** — 全局 + 按直播间的锁定提示词描述，确保迭代不违反运营硬性要求
- **后台任务** — 评分和迭代在子进程运行，支持停止/强制停止，历史任务可跳转对应直播间
- **多模型支持** — OpenAI / Anthropic / Google Gemini，支持代理和直连
- **脚本翻译** — 一键翻译为 12 种语言，适配多国直播间
- **跨脚本去重** — 检测多次生成脚本间的重复片段，优化提示词降低重复率

## 快速开始

```bash
git clone https://github.com/gavinguang-ctrl/darwin.git
cd darwin
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json，填入 API keys 和登录账号
streamlit run app.py
```

浏览器打开 `http://localhost:8501`，用 config.json 中配置的账号登录。

## 配置说明

编辑 `config.json`（从 `config.example.json` 复制）：

| 字段 | 说明 |
|------|------|
| `GOOGLE_API_KEY` | Google Gemini API Key |
| `GOOGLE_PROXY_KEY` | fucheers 代理 Key（可选） |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `OPENAI_API_KEY` | OpenAI API Key |
| `*_PROXY_URL` | 代理地址，默认 fucheers.top |
| `ZMENG_AUTH_TOKEN` | 众盟平台 Token（API导入用） |
| `ZMENG_COOKIE` | 众盟平台 Cookie |
| `DEFAULT_SCORER` | 默认评分模型 |
| `DEFAULT_OPTIMIZER` | 默认优化模型 |
| `DEFAULT_GENERATOR` | 默认生成模型 |
| `USERS` | 登录账号 `{"email": "password"}` |

也可以在首页「API配置」面板中修改（会自动保存到 config.json）。

## 使用流程

```
1. 创建直播间 → 导入历史场次数据（或使用冷启动）
2. 批量评分 → 系统对所有脚本进行多维度打分
3. 棘轮分析 → 选择直播间，查看评分，启动自动迭代
4. 查看结果 → 在后台任务中跟踪进度，迭代完成后查看优化方案
5. 设为基线 → 将最优方案设为新基线，进入下一轮迭代
```

### 冷启动（全新直播间）

适用于完全没有历史数据的新直播间：
1. 创建直播间时选择「冷启动模式」
2. 填写基线提示词 → 系统自动生成初始脚本
3. 自动进行首次评分，生成合成场次数据
4. 之后即可正常使用棘轮迭代

## 评分维度

| 维度 | 默认权重 | 说明 |
|------|----------|------|
| 黄金3秒 | 7 | 每个循环前3秒的 Hook 强度 |
| 单点卖点 | 5 | 每个循环是否只聚焦一个卖点 |
| 循环结构 | 7 | 是否由15-30秒独立循环组成 |
| 行动号召CTA | 7 | 每个循环末尾的 CTA 明确度 |
| 节奏密度 | 5 | 句子短而密集，无废话 |
| 痛点速击 | 5 | 前5秒是否戳中痛点 |
| 价格锚点 | 5 | 是否建立价格对比 |
| 入场信号 | 4 | 新观众能否立即理解上下文 |

权重可在棘轮分析页面侧边栏自定义调整。

## 程序架构

```
darwin/
├── app.py                 # 入口：登录认证、API配置、使用说明
├── config.py              # 配置加载、全局锁定提示词管理
├── models.py              # 数据模型（RatchetState, Candidate, Session）
├── llm.py                 # LLM 提供商抽象层（OpenAI/Anthropic/Google）
├── rubric.py              # 评分维度定义、评分逻辑、实效预估
├── hill_climb.py          # 爬山优化引擎（诊断→生成→评分→决策）
├── prompts.py             # 系统提示词模板
├── task_manager.py        # 后台任务管理（创建/列表/停止）
├── task_worker.py         # 后台任务执行器（auto_iterate/batch_score）
├── room.py                # 直播间 CRUD + 候选方案管理
├── data_io.py             # 场次数据读写
├── zmeng_api.py           # 众盟平台 API 对接
├── priority.py            # 优先级诊断（识别最弱维度）
├── audit.py               # 操作审计日志
├── ui_helpers.py          # 共享 UI 组件
├── pages/
│   ├── 1_直播间管理.py     # 直播间CRUD、场次导入、冷启动
│   ├── 2_棘轮分析.py       # 棘轮优化：评分、自动迭代、单维度优化
│   ├── 3_数据看板.py       # 数据可视化、趋势图表
│   └── 4_后台任务.py       # 后台任务监控、历史任务、跳转链接
├── data/
│   ├── rooms/             # 直播间数据
│   │   └── {room_id}/
│   │       ├── room.json       # 直播间配置
│   │       ├── ratchet.json    # 棘轮状态
│   │       ├── candidates/     # 候选优化方案
│   │       └── sessions/       # 历史场次数据
│   ├── tasks/             # 后台任务状态文件
│   └── weight_config.json # 评分权重配置
├── config.json            # API keys 和用户配置
├── config.example.json    # 配置模板
└── requirements.txt       # Python 依赖
```

### 核心模块职责

| 模块 | 职责 |
|------|------|
| `hill_climb.py` | 爬山优化核心：诊断最弱维度 → 构建优化prompt → 生成改进版本 → 评分对比 → 决策保留/回退 |
| `rubric.py` | 定义8个静态维度 + 实效指标，调用LLM评分，计算加权总分 |
| `task_worker.py` | 子进程执行器：`auto_iterate`（自动迭代）、`batch_score`（批量评分） |
| `llm.py` | 统一的LLM调用接口，支持3家提供商 + 代理模式 |
| `config.py` | 配置读写 + 全局/按直播间锁定提示词解析 |

### 数据流

```
用户操作 → Streamlit UI → task_manager.create_task()
                                    ↓
                          subprocess → task_worker.py
                                    ↓
                hill_climb.auto_iterate() ←→ llm.py ←→ LLM API
                                    ↓
                    评分+决策 → 更新 candidates/ + ratchet.json
```

## 更新日志

### v0.5 (2026-05-19)

- **锁定提示词修复**：prompt模式下不再将锁定条件原文照搬到输出提示词中（避免重复），改为运行时自动注入
- **页面跳转修复**：从后台任务跳转到棘轮分析后，直播间选择不再因页面交互而重置
- **后台任务重构**：运行中/历史任务分Tab显示，显示完成时间，支持跳转到对应直播间
- **参考脚本段落**：自动迭代和单维度优化支持粘贴优秀脚本片段作为优化方向参考
- **评分时间窗口**：新增「成交用户」模式（停留时长×6），适用于高客单价场景
- **冷启动模式**：全新直播间无需历史数据，从提示词直接生成初始脚本并评分
- **自动去重禁用**：迭代后不再自动触发跨脚本去重（避免不必要的额外轮次）
- **脚本翻译**：支持12种语言一键翻译
- **全局/按直播间锁定描述**：运营硬性要求可全局设置或按直播间单独配置

### v0.4 (2026-05-08)

- 跨脚本去重优化
- LCS 算法加速（滚动窗口 seed-and-extend）
- 后台自动迭代 + 批量评分
- 众盟 API 对接

### v0.3 (2026-05-07)

- 多模型支持（OpenAI/Anthropic/Google）
- 评分权重自定义
- 数据看板可视化

## 技术栈

- **前端**: Streamlit 1.45+
- **LLM**: OpenAI GPT-4o / Anthropic Claude / Google Gemini
- **数据**: JSON 文件存储（无需数据库）
- **图表**: Plotly
- **部署**: 本地运行，支持局域网访问
