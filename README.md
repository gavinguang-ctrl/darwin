# 🧬 达尔文 — TikTok 直播脚本棘轮优化系统

基于棘轮理论（Ratchet Theory）的 TikTok AI 数字人直播脚本自动优化系统。通过多维度评分 + 爬山迭代，持续提升直播脚本质量，锁定每次迭代的成功要素，确保优化成果不回退。

## 功能

- **直播间管理** — 创建直播间，通过 API / Excel / 手动导入历史脚本和数据
- **自动评分** — 8 维度静态评分 + 实效数据评分，后台批量运行
- **棘轮优化** — 单维度爬山迭代，提示词模式或脚本直改模式
- **后台任务** — 评分和迭代在子进程运行，切换页面不中断
- **多模型支持** — OpenAI / Anthropic / Google Gemini，支持代理和直连

## 快速开始

```bash
git clone https://github.com/<your-username>/darwin.git
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

## 评分维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 黄金3秒 | 7 | 每个循环前3秒的 Hook 强度 |
| 单点卖点 | 5 | 每个循环是否只聚焦一个卖点 |
| 循环结构 | 7 | 是否由15-30秒独立循环组成 |
| 行动号召CTA | 7 | 每个循环末尾的 CTA 明确度 |
| 节奏密度 | 5 | 句子短而密集，无废话 |
| 痛点速击 | 5 | 前5秒是否戳中痛点 |
| 价格锚点 | 5 | 是否建立价格对比 |
| 入场信号 | 4 | 新观众能否立即理解上下文 |

## 项目结构

```
app.py              # 入口：登录、API配置、概览
config.py           # 配置加载
models.py           # 数据模型
llm.py              # LLM 提供商抽象层
rubric.py           # 评分维度和评分逻辑
hill_climb.py       # 爬山优化引擎
prompts.py          # 系统提示词
task_manager.py     # 后台任务管理
task_worker.py      # 后台任务执行器
ui_helpers.py       # 共享 UI 组件
room.py             # 直播间 CRUD
data_io.py          # 场次数据读写
zmeng_api.py        # 众盟平台 API
pages/
  1_直播间管理.py    # 直播间和场次管理
  2_棘轮分析.py      # 棘轮优化分析
  3_数据看板.py      # 数据可视化
  4_后台任务.py      # 后台任务监控
data/rooms/         # 直播间数据（含场次、候选方案、棘轮状态）
```
