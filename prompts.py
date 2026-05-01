SYSTEM_PROMPT = """你是一个专业的直播脚本优化顾问，精通 TikTok 直播带货的运营策略。
你的任务是基于棘轮理论（Ratchet Theory）帮助用户持续优化直播脚本。
棘轮理论的核心：锁定每次迭代中被验证有效的脚本元素，确保优化成果不回退。
请用中文回答，分析要具体到脚本中的具体话术、结构和策略。"""

OPTIMIZER_SYSTEM_PROMPT = """你是一个专业的 TikTok AI数字人直播脚本优化顾问。
你的任务是根据诊断结果，针对性地改进直播脚本。

## 核心认知（必须贯穿优化）
1. 观众随时进入直播间，平均只停留15-30秒
2. 脚本必须由多个15-30秒的"循环"组成，每个循环是一个完整推销闭环
3. 每个循环结构：Hook(3-5秒) → 一个卖点+价格锚(8-15秒) → 社交证明(3-5秒) → CTA(3-5秒)
4. 每个循环只聚焦一个卖点，多个卖点分布在不同循环中
5. 从任何位置开始听15-30秒，观众都应获得一个完整的价值主张+购买理由+行动指引

## 硬性约束（必须遵守）
1. 脚本用于AI数字人直播+TTS朗读，必须TTS友好：
   - 不能有旁白、场景描述、动作指示（如[拿起产品]、（展示效果）等）
   - 不能有中文，脚本语言与目标市场一致
   - 只输出主播说的话，纯口播内容
2. 每次只改进一个维度，保持其他部分稳定
3. 不改变产品/优惠本身，只优化表达方式和脚本结构
4. 必须保留所有已锁定的成功要素
5. 改进要具体到话术层面，不要泛泛而谈
6. 保持脚本总长度基本不变（允许+-10%）
7. 不同循环的Hook、CTA、过渡句必须用不同表达，避免字面重复被TikTok判定为预录制"""

PROMPT_OPTIMIZER_SYSTEM_PROMPT = """你是一个专业的 TikTok AI数字人直播脚本提示词工程师。
你的任务是优化"生成直播脚本的提示词"，使其生成的脚本在特定维度上表现更好。

## 核心认知（必须贯穿优化）
1. 观众随时进入直播间，平均只停留15-30秒
2. 生成的脚本必须由多个15-30秒"循环"组成，每个循环是完整推销闭环
3. 每个循环：Hook(3-5秒) → 一个卖点+价格锚(8-15秒) → 社交证明(3-5秒) → CTA(3-5秒)
4. 每个循环只聚焦一个卖点，多个卖点分布在不同循环中

## 硬性约束（必须遵守）
1. 生成的脚本用于AI数字人直播+TTS朗读，必须TTS友好：
   - 不能有旁白、场景描述、动作指示（如[拿起产品]、（展示效果）等）
   - 不能有中文，脚本语言与目标市场一致
   - 只输出主播说的话，纯口播内容
2. 优化后的提示词必须保持与原始提示词相同的格式结构
3. 约束条件必须放在提示词最前面，防止被忽略
4. 每次只针对一个维度改进提示词中的指令
5. 不改变产品/优惠信息，只优化提示词的策略和约束
6. 必须保留所有已锁定的提示词指令
7. 提示词要具体、可执行，能直接喂给 AI 生成完整脚本
8. 提示词中嵌入的基准脚本是可以修改的——用提供的最新最佳脚本替换，并可在此基础上针对目标维度进一步优化
9. 不同循环的Hook、CTA、过渡句必须用不同表达，避免字面重复被TikTok判定为预录制
10. 输出的是提示词，不是脚本本身"""


def build_analysis_prompt(
    current_script: str,
    previous_script: str | None,
    metric_comparison: list[dict],
    locked_constraints: list[dict],
) -> str:
    parts = ["## 本场直播脚本\n", current_script, "\n"]

    if previous_script:
        parts.append("## 上一场直播脚本\n")
        parts.append(previous_script)
        parts.append("\n")

    parts.append("## 指标对比\n")
    for m in metric_comparison:
        arrow = "↑" if m["status"] == "IMPROVED" else ("→" if m["status"] == "HELD" else "↓")
        baseline_str = f"（基线: {m['baseline']}）" if m.get("baseline") is not None else ""
        parts.append(f"- {m['key']}: {m['current']} {arrow} {m['status']} {baseline_str}")
    parts.append("\n")

    if locked_constraints:
        parts.append("## 已锁定的成功要素\n")
        for c in locked_constraints:
            parts.append(f"- {c['element']}（原因: {c['reason']}）")
        parts.append("\n")

    parts.append("""## 请分析

1. **增益归因**：哪些脚本元素（具体话术、结构、节奏、互动方式）可能导致了指标提升？
2. **下降诊断**：哪些变化可能导致了指标下降？
3. **锁定建议**：建议锁定哪些元素作为未来脚本的必备约束？请以 JSON 列表格式输出：
```json
[{"element": "具体描述", "reason": "关联的指标变化"}]
```
4. **改进方向**：下一场脚本应该在哪些方面重点优化？""")

    return "\n".join(parts)


def build_generation_prompt(
    locked_constraints: list[dict],
    improvement_targets: list[dict],
    baselines: dict[str, float],
    session_count: int,
) -> str:
    parts = [f"## 当前状态\n- 已完成 {session_count} 场迭代\n"]

    parts.append("## 基线指标（历史最佳）\n")
    for key, val in baselines.items():
        parts.append(f"- {key}: {val}")
    parts.append("\n")

    if locked_constraints:
        parts.append("## 🔒 必须保留的成功要素（棘轮锁定）\n")
        for c in locked_constraints:
            parts.append(f"- ✅ {c['element']}（{c['reason']}）")
        parts.append("\n⚠️ 以上要素已被验证有效，下一场脚本必须包含这些元素。\n")

    if improvement_targets:
        parts.append("## 🎯 重点优化目标\n")
        for t in improvement_targets:
            parts.append(f"- {t['key']}: 当前 {t['current']}，目标超越基线 {t['baseline']}")
        parts.append("\n")

    parts.append("""## 请生成下一场直播脚本的优化提示词

要求：
1. 明确列出必须保留的元素和话术框架
2. 针对需要改进的指标，给出具体的脚本调整建议
3. 提供 2-3 个可以尝试的新策略
4. 给出完整的脚本结构建议（开场→产品介绍→互动→逼单→收尾）
5. 提示词应该可以直接喂给 AI 来生成完整脚本""")

    return "\n".join(parts)
