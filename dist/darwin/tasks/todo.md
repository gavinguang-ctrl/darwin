# darwin-skill 2.0 升级移植计划

## 5 个升级点

### 升级 1: 多评委共识评分
**位置**: `rubric.py` 的 `score_script()`
**方案**: 
- 新增 `consensus_score_script()` 包装函数，内部调用 `score_script()` 3次（不同 system prompt 变体）
- 变体策略：保持同一评分 prompt 但注入不同评审视角（"严格评审" / "行业专家" / "观众视角"）
- 取各维度**中位数**作为最终得分（3次取中位数，比平均值抗噪更好）
- 在 `task_worker.py` 的自动迭代中使用 consensus 版本
- UI 单步优化仍用单次评分（避免 3x 耗时影响交互体验），但提供 checkbox 开关
- config.py 新增 `CONSENSUS_JUDGES = 3`

### 升级 2: 维度相关性集群
**位置**: `hill_climb.py` 新增 `DIMENSION_CLUSTERS` 常量 + 修改目标选择逻辑
**方案**:
- 定义关联簇:
  - 簇A "吸引力": hook, pain_points, reentry (都关于吸引/留住观众)
  - 簇B "转化力": product_demo, price_anchor, closing (都关于推动购买)
  - 簇C "结构力": golden_loop, pacing (整体结构和节奏)
- 修改 `auto_iterate()` 和 `task_worker.py` 的维度选择:
  - 选出最弱维度后，检查其所在簇的其他维度分数
  - 若簇内有更低分维度（可能是根因），优先优化根因维度
  - 用 `_find_cluster_root()` 辅助函数实现
- 在 `generate_improvement` 的 prompt 里加提示："该维度与 X/Y 关联，优化时注意协同"

### 升级 3: 连续边际增益早停
**位置**: `hill_climb.py` 的 `auto_iterate()` + `task_worker.py` 的迭代循环
**方案**:
- 新增 `MARGINAL_GAIN_THRESHOLD = 1.5`（连续2轮增益<1.5分则停止）
- 跟踪 `recent_gains: list[float]` 最近 2 轮的实际增益
- 停止条件: `len(recent_gains) >= 2 and all(g < MARGINAL_GAIN_THRESHOLD for g in recent_gains[-2:])`
- 停止原因标记为 `"marginal_gains"` 便于日志区分
- 不影响现有 stagnation 逻辑（那是"完全不提升"的情况）

### 升级 4: 优化前反模式检查
**位置**: `hill_climb.py` 新增 `_check_anti_patterns()` + 修改 `generate_improvement` / `generate_prompt_improvement`
**方案**:
- 定义领域反模式列表 `ANTI_PATTERNS`:
  1. closing 分低但脚本已有 3+ CTA → 问题不是"缺CTA"而是"CTA无效/被稀释"，禁止"加更多CTA"
  2. pacing 分低但脚本已超过推荐时长 → 问题不是"内容不够"而是"太冗长"，禁止"加更多内容"
  3. hook 分低但前 5 秒已有问句 → 问题不是"缺 Hook"而是"Hook 无力"，引导"换 Hook 策略"
  4. reentry 分低但已有 3+ 循环 → 不是"循环不够"而是"循环间缺重置"，引导"加上下文重置"
  5. product_demo 分低但已有数据/对比 → 不是"缺信息"而是"信息组织差"，引导"重组卖点结构"
- `_check_anti_patterns(target, script, scores)` → 返回 list[str] 额外约束
- 把额外约束注入 `generate_improvement` 的 prompt（"本次优化禁止：..."）
- 轻量实现：规则基于简单文本检测（字数/CTA计数/循环计数），不需要额外 LLM 调用

### 升级 5: 自动探索性重写触发
**位置**: `task_worker.py` 的 `run_auto_iterate()` 循环 + `hill_climb.py` 的 `auto_iterate()`
**方案**:
- 新逻辑：第 1 轮优化如果增益 < 2 分（`new_total - initial_total < 2`），自动触发一次全量重写
- 重写后重新评分，若分数比当前最佳高则采纳，否则继续正常迭代
- 只在**第 1 轮**触发（避免每轮都重写浪费 token）
- 标记 `rewrite_attempted = True` 防止重复触发
- 回调/日志标记 "auto_rewrite_triggered"

## 实施顺序
1. 升级 3（边际增益早停）— 改动最小，纯逻辑
2. 升级 2（维度相关性集群）— 新增常量+选择逻辑
3. 升级 5（自动重写触发）— 在迭代循环加条件分支
4. 升级 4（反模式检查）— 新增检测函数+注入 prompt
5. 升级 1（多评委共识）— 改动最大，涉及评分核心函数

## 影响范围
- `rubric.py`: 升级1（consensus wrapper）
- `hill_climb.py`: 升级2/3/4/5（集群、早停、反模式、重写触发）
- `task_worker.py`: 升级1/3/5（共识评分开关、边际早停、重写触发）
- `config.py`: 新增 CONSENSUS_JUDGES, MARGINAL_GAIN_THRESHOLD, DIMENSION_CLUSTERS
- `prompts.py`: 升级4（反模式注入 prompt 的 helper）
- `pages/3_棘轮分析.py`: UI 显示升级效果（日志、停止原因）

## 验证
- 全部文件语法检查
- 单元级：consensus scorer 调用3次取中位数；集群根因选择正确；边际增益条件触发；反模式规则匹配；重写条件触发
- 集成：启动 darwin，自动迭代能跑完不报错，日志里能看到新机制的痕迹
