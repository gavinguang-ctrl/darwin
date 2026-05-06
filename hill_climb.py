from config import STAGNATION_THRESHOLD, SCRIPT_MAX_LENGTH_RATIO
from rubric import (
    STATIC_DIMENSIONS, EFFECT_METRICS,
    find_weakest_dimension, score_script, compute_effect_score, compute_total_score,
    estimate_effect_scores,
)
from llm import LLMProvider
from prompts import OPTIMIZER_SYSTEM_PROMPT, PROMPT_OPTIMIZER_SYSTEM_PROMPT


def diagnose(static_scores: dict[str, int], effect_scores: dict[str, float],
             weight_config: dict | None = None) -> dict:
    weakest = find_weakest_dimension(static_scores, effect_scores, weight_config)
    return {
        "target": weakest,
        "is_effect": weakest["type"] == "effect",
        "current_score": weakest["score"],
        "max_gain": (10 - weakest["score"]) * _get_weight(weakest["id"], weight_config) / 10,
    }


def _get_weight(dim_id: str, weight_config: dict | None = None) -> int:
    if weight_config:
        for section in ("static", "effect"):
            if dim_id in weight_config.get(section, {}):
                return weight_config[section][dim_id]
    for d in STATIC_DIMENSIONS:
        if d["id"] == dim_id:
            return d["weight"]
    for m in EFFECT_METRICS:
        if m["id"] == dim_id:
            return m["weight"]
    return 1


def _get_dim_detail(dim_id: str) -> dict | None:
    for d in STATIC_DIMENSIONS:
        if d["id"] == dim_id:
            return d
    return None


def build_improvement_prompt(
    script: str,
    target: dict,
    static_scores: dict[str, int],
    locked_constraints: list[dict],
) -> str:
    dim = _get_dim_detail(target["id"])

    parts = [f"## 任务\n针对「{target['name']}」维度（当前 {target['score']}/10 分）优化以下直播脚本。\n"]

    if dim:
        parts.append(f"## 维度定义\n- 含义: {dim['desc']}\n")
        if dim.get("ten"):
            parts.append(f"- 满分标准(10分): {dim['ten']}\n")
        if dim.get("one"):
            parts.append(f"- 最差标准(1分): {dim['one']}\n")

    if dim and dim.get("techniques"):
        parts.append("\n## 具体优化手法（请选择适合的应用）\n")
        for tech in dim["techniques"]:
            parts.append(f"- {tech}\n")

    parts.append("\n## 约束\n- 只改进这一个维度，不要大幅改动其他部分\n- 不要改变产品/优惠本身，只优化表达方式\n- 保持15-30秒循环结构：每个循环是Hook→单个卖点→价格→CTA的完整闭环\n")

    if locked_constraints:
        parts.append("- 以下已锁定要素必须保留：\n")
        for c in locked_constraints:
            parts.append(f"  - {c['element']}\n")

    parts.append(f"\n## 当前脚本\n{script}\n")
    parts.append("\n## 输出\n请输出改进后的完整脚本，并在开头用一句话说明你改了什么。")
    return "".join(parts)


def build_rewrite_prompt(script: str, static_scores: dict[str, int], locked_constraints: list[dict]) -> str:
    parts = ["## 任务\n对以下直播脚本进行全局重构（不是微调，是重新组织结构和表达方式）。\n"]
    parts.append("## 当前评分\n")
    for d in STATIC_DIMENSIONS:
        s = static_scores.get(d["id"], 0)
        parts.append(f"- {d['name']}: {s}/10\n")

    if locked_constraints:
        parts.append("\n## 必须保留的要素\n")
        for c in locked_constraints:
            parts.append(f"- {c['element']}\n")

    parts.append(f"\n## 当前脚本\n{script}\n")
    parts.append("\n## 要求\n- 按15-30秒循环结构重组：每个循环 = Hook(3-5秒) → 一个卖点+价格锚(8-15秒) → 社交证明(3-5秒) → CTA(3-5秒)\n- 每个循环只聚焦一个卖点，多个卖点分布在不同循环中\n- 每个循环自成一体，新观众从任何位置进入15-30秒内可获得完整推销\n- 保留所有锁定要素\n- 不改变产品/优惠本身\n- 输出完整脚本")
    return "".join(parts)


def generate_improvement(script: str, target: dict, static_scores: dict[str, int],
                         locked_constraints: list[dict], optimizer: LLMProvider) -> str:
    prompt = build_improvement_prompt(script, target, static_scores, locked_constraints)
    return optimizer.generate(prompt, system=OPTIMIZER_SYSTEM_PROMPT)


def generate_rewrite(script: str, static_scores: dict[str, int],
                     locked_constraints: list[dict], optimizer: LLMProvider) -> str:
    prompt = build_rewrite_prompt(script, static_scores, locked_constraints)
    return optimizer.generate(prompt, system=OPTIMIZER_SYSTEM_PROMPT)


def decide(old_total: float, new_total: float) -> str:
    return "keep" if new_total > old_total else "revert"


def check_length(original: str, improved: str) -> bool:
    return len(improved) <= len(original) * SCRIPT_MAX_LENGTH_RATIO


def check_stagnation(stagnation_count: int) -> bool:
    return stagnation_count >= STAGNATION_THRESHOLD


# === 提示词模式 ===

def build_prompt_improvement(
    base_prompt: str,
    current_script: str,
    target: dict,
    static_scores: dict[str, int],
    locked_constraints: list[dict],
    product_info: str = "",
    baseline_strengths: str = "",
    original_prompt: str = "",
) -> str:
    filled_prompt = base_prompt
    for placeholder in ["(此处插入基准脚本)", "（此处插入基准脚本）", "{基准脚本}", "{baseline_script}"]:
        if placeholder in filled_prompt:
            filled_prompt = filled_prompt.replace(placeholder, current_script[:3000])

    parts = []
    # 约束条件放最前面
    parts.append("## 硬性约束（优化时必须遵守）\n")
    parts.append("- 脚本用于AI数字人直播+TTS朗读，不能有旁白、场景描述、动作指示，不能有中文\n")
    parts.append("- 只输出主播说的话，纯口播内容\n")
    parts.append("- 优化后的提示词格式必须与原始提示词保持一致\n")
    parts.append("- 约束条件放在提示词最前面\n")
    parts.append("- 提示词中必须包含完整的基准脚本内容，不能用占位符\n")
    parts.append("- 你可以修改提示词中嵌入的基准脚本，使其与优化方向一致\n")
    if locked_constraints:
        parts.append("- 以下已锁定的提示词指令必须保留：\n")
        for c in locked_constraints:
            parts.append(f"  - {c['element']}\n")
    parts.append("- 只针对目标维度改进，不要改变产品/优惠本身\n")
    parts.append("- 基线脚本的优点必须保留\n\n")

    parts.append(f"## 任务\n针对「{target['name']}」维度（当前 {target['score']}/10 分）优化以下直播脚本生成提示词。\n\n")

    dim = _get_dim_detail(target["id"])
    if dim:
        parts.append(f"## 目标维度详情\n- 定义: {dim['desc']}\n")
        if dim.get("ten"):
            parts.append(f"- 满分标准: {dim['ten']}\n")
        if dim.get("affects"):
            parts.append(f"- 影响的效果指标: {', '.join(dim['affects'])}\n")
        if dim.get("techniques"):
            parts.append("\n## 应在提示词中强调的具体手法\n")
            for tech in dim["techniques"]:
                parts.append(f"- {tech}\n")
        parts.append("\n")

    if product_info:
        parts.append(f"## 产品信息\n{product_info}\n\n")
    if baseline_strengths:
        parts.append(f"## 基线脚本的优点（必须保留）\n{baseline_strengths}\n\n")
    if original_prompt and original_prompt != base_prompt:
        parts.append(f"## 原始提示词格式（输出格式必须与此一致）\n```\n{original_prompt[:2000]}\n```\n\n")
    parts.append(f"## 当前提示词\n```\n{filled_prompt}\n```\n")
    parts.append(f"\n## 当前提示词生成的脚本（这是最新的最佳脚本，提示词中的基准脚本应更新为此版本或更优版本）\n{current_script[:3000]}\n")
    parts.append("\n## 输出\n请输出改进后的完整提示词。提示词中的基准脚本应替换为最新的最佳版本（可在此基础上进一步优化）。格式与原始提示词保持一致，约束条件放最前面。")
    return "".join(parts)


def build_prompt_rewrite(
    base_prompt: str,
    static_scores: dict[str, int],
    locked_constraints: list[dict],
    product_info: str = "",
) -> str:
    parts = ["## 任务\n对以下直播脚本生成提示词进行全局重构。\n"]
    if product_info:
        parts.append(f"## 产品信息\n{product_info}\n\n")
    parts.append("## 当前评分\n")
    for d in STATIC_DIMENSIONS:
        s = static_scores.get(d["id"], 0)
        parts.append(f"- {d['name']}: {s}/10\n")
    if locked_constraints:
        parts.append("\n## 必须保留的提示词指令\n")
        for c in locked_constraints:
            parts.append(f"- {c['element']}\n")
    parts.append(f"\n## 当前提示词\n```\n{base_prompt}\n```\n")
    parts.append("\n## 要求\n- 全新的提示词结构和策略，不是在原版上修补\n- 保留所有锁定指令\n- 输出完整提示词")
    return "".join(parts)


def extract_baseline_strengths(static_scores: dict[str, int], script: str, optimizer: LLMProvider) -> str:
    high_dims = [(d["name"], static_scores.get(d["id"], 0)) for d in STATIC_DIMENSIONS if static_scores.get(d["id"], 0) >= 7]
    if not high_dims:
        return ""
    dims_str = ", ".join(f"{name}({score}/10)" for name, score in high_dims)
    prompt = f"""以下直播脚本在这些维度得分较高：{dims_str}

## 脚本（前2000字）
{script[:2000]}

请提炼出这个脚本做得好的具体优点（3-6条），每条用一句话描述具体的技巧或策略，而不是泛泛的评价。
格式：每行一条，以"- "开头。"""
    try:
        return optimizer.generate(prompt, system="你是直播脚本分析专家。提炼脚本的具体优点，用于指导后续优化时保留这些优势。")
    except Exception:
        return ""


def generate_prompt_improvement(base_prompt: str, current_script: str, target: dict,
                                static_scores: dict[str, int], locked_constraints: list[dict],
                                optimizer: LLMProvider, product_info: str = "",
                                baseline_strengths: str = "", original_prompt: str = "") -> str:
    prompt = build_prompt_improvement(base_prompt, current_script, target, static_scores,
                                      locked_constraints, product_info, baseline_strengths, original_prompt)
    return optimizer.generate(prompt, system=PROMPT_OPTIMIZER_SYSTEM_PROMPT)


def generate_prompt_rewrite(base_prompt: str, static_scores: dict[str, int],
                            locked_constraints: list[dict], optimizer: LLMProvider,
                            product_info: str = "") -> str:
    prompt = build_prompt_rewrite(base_prompt, static_scores, locked_constraints, product_info)
    return optimizer.generate(prompt, system=PROMPT_OPTIMIZER_SYSTEM_PROMPT)


def generate_script_from_prompt(prompt_text: str, generator: LLMProvider, baseline_script: str = "") -> str:
    filled = prompt_text
    if baseline_script:
        for placeholder in ["(此处插入基准脚本)", "（此处插入基准脚本）", "{基准脚本}", "{baseline_script}"]:
            if placeholder in filled:
                filled = filled.replace(placeholder, baseline_script[:3000])
    return generator.generate(filled)


def build_dedupe_improvement(base_prompt: str, avg_rep_ratio: float,
                             top_repeat_examples: list[tuple], locked_constraints: list[dict]) -> str:
    """为跨脚本去重生成 prompt 优化指令。"""
    parts = ["## 任务\n"]
    parts.append(f"以下直播脚本生成提示词在被执行多次时，生成的不同脚本之间字面重复率高达 {avg_rep_ratio*100:.1f}%。\n")
    parts.append("需要优化该提示词，让每次生成的脚本在保持核心信息（产品、价格、CTA）相同的前提下，\n")
    parts.append("用不同的措辞、句式、Hook、过渡句、CTA 表达——使多次生成的脚本之间字面重复最少。\n\n")

    parts.append("## 跨脚本重复片段示例（这些片段在不同脚本中被完全复用，必须消除）\n")
    for idx, (i, j, lcs) in enumerate(top_repeat_examples[:5], 1):
        parts.append(f"示例{idx}（脚本{i+1} vs 脚本{j+1}）:\n")
        parts.append(f"```\n{lcs[:300]}\n```\n\n")

    parts.append("## 硬性约束\n")
    parts.append("- 保留所有产品信息、价格、优惠细节（这些必须一致）\n")
    parts.append("- 脚本用于AI数字人直播+TTS朗读，纯口播，无旁白/动作指示\n")
    parts.append("- 保持15-30秒循环结构\n")
    parts.append("- 提示词中必须包含完整的基准脚本，不能用占位符\n")
    if locked_constraints:
        parts.append("- 以下已锁定指令必须保留：\n")
        for c in locked_constraints:
            parts.append(f"  - {c['element']}\n")

    parts.append("\n## 去重策略（在提示词中强制）\n")
    parts.append("- 提供多套 Hook 模板池，每次随机选1套\n")
    parts.append("- 提供多套 CTA 表达池，每个循环随机选1套\n")
    parts.append("- 提供多套过渡句库，避免固定过渡句\n")
    parts.append("- 明确要求：每次生成用不同的措辞重新组织，避免逐字复用示例\n")
    parts.append("- 允许对卖点论述换角度/换比喻，但不改变产品信息本身\n\n")

    parts.append(f"## 当前提示词\n```\n{base_prompt}\n```\n\n")
    parts.append("## 输出\n请输出改进后的完整提示词。提示词中必须包含完整基准脚本，并加入明确的多样化生成指令和模板池。")
    return "".join(parts)


def generate_dedupe_improvement(base_prompt: str, avg_rep_ratio: float,
                                top_repeat_examples: list[tuple],
                                locked_constraints: list[dict],
                                optimizer: LLMProvider) -> str:
    prompt = build_dedupe_improvement(base_prompt, avg_rep_ratio, top_repeat_examples, locked_constraints)
    return optimizer.generate(prompt, system=PROMPT_OPTIMIZER_SYSTEM_PROMPT)


# === 自动迭代 ===

def auto_iterate(
    current_script: str,
    current_scores: dict[str, int],
    current_effect_scores: dict[str, float],
    current_total: float,
    threshold: float,
    max_rounds: int,
    locked_constraints: list[dict],
    effect_baselines: dict[str, float],
    optimizer: LLMProvider,
    scorer: LLMProvider,
    mode: str = "script",
    base_prompt: str = "",
    product_info: str = "",
    weight_config: dict | None = None,
    callback=None,
    history_sessions: list | None = None,
    dwell_seconds: float = 0,
) -> dict:
    """
    自动迭代爬山。始终优化静态维度，实效通过预估。
    history_sessions: 历史场次列表，用于学习静态→实效映射关系。
    """
    from rubric import get_effective_weights

    target_score = current_total * (1 + threshold / 100)
    best_content = base_prompt if mode == "prompt" else current_script
    best_script = current_script
    best_total = current_total
    best_static = dict(current_scores)
    best_effect = dict(current_effect_scores)
    stag = 0
    log = []

    # 从历史数据学习静态→实效关联，注入预估 prompt
    correlation_hint = _build_correlation_hint(history_sessions) if history_sessions else ""

    # 提炼基线优点（prompt模式下注入优化流程）
    baseline_strengths = ""
    if mode == "prompt" and best_script:
        baseline_strengths = extract_baseline_strengths(current_scores, best_script, optimizer)

    for r in range(1, max_rounds + 1):
        try:
            # 找带权潜在增益最大的静态维度
            static_dims, _ = get_effective_weights(weight_config)
            static_candidates = [{"id": d["id"], "name": d["name"], "type": "static",
                                  "score": best_static.get(d["id"], 0),
                                  "gain": (10 - best_static.get(d["id"], 0)) * d["weight"]}
                                 for d in static_dims if d["weight"] > 0]
            if not static_candidates:
                log.append({"round": r, "status": "stop", "note": "无可优化的静态维度"})
                if callback:
                    callback(r, log[-1])
                break
            target = max(static_candidates, key=lambda x: x["gain"])

            # 优化静态维度
            if mode == "prompt" and best_content:
                new_content = generate_prompt_improvement(
                    best_content, best_script, target, best_static, locked_constraints, optimizer, product_info,
                    baseline_strengths=baseline_strengths)
                new_script = generate_script_from_prompt(new_content, optimizer, baseline_script=best_script)
            else:
                new_content = generate_improvement(best_script, target, best_static, locked_constraints, optimizer)
                new_script = new_content

            # 独立评分（静态）
            nr = score_script(new_script, scorer, locked_constraints, weight_config, dwell_seconds=dwell_seconds)
            new_static_total = nr["static_score"]

            # 预估实效（基于静态评分 + 历史关联）
            new_eff_total, new_eff = estimate_effect_scores(
                new_script, nr["scores"], effect_baselines, scorer, weight_config, correlation_hint)
            new_total = compute_total_score(new_static_total, new_eff_total)

            decision = decide(best_total, new_total)
            entry = {"round": r, "dim": target["name"], "old": best_total, "new": new_total,
                     "static": new_static_total, "effect_est": new_eff_total, "status": decision}

            if decision == "keep":
                best_content = new_content
                best_script = new_script
                best_total = new_total
                best_static = nr["scores"]
                best_effect = new_eff
                stag = 0
            else:
                stag += 1

            log.append(entry)
            if callback:
                callback(r, entry)

            if best_total >= target_score:
                log.append({"round": r, "status": "target_reached", "note": f"达到目标 {target_score:.1f}"})
                break

            if stag >= STAGNATION_THRESHOLD:
                log.append({"round": r, "status": "stagnation", "note": "连续停滞，停止"})
                break

        except Exception as e:
            log.append({"round": r, "status": "error", "note": f"第{r}轮出错: {e}"})
            if callback:
                callback(r, log[-1])
            break

    return {
        "content": best_content,
        "generated_script": best_script if mode == "prompt" else "",
        "total_score": best_total,
        "static_scores": best_static,
        "effect_scores": best_effect,
        "rounds": len([e for e in log if "dim" in e]),
        "log": log,
    }


def _build_correlation_hint(sessions: list) -> str:
    """从历史场次中提取静态评分→实效数据的关联模式"""
    scored = [s for s in sessions if s.static_scores and s.metrics]
    if len(scored) < 2:
        return ""
    lines = ["历史数据中静态评分与实效的关联："]
    for s in scored[-5:]:
        static_str = ", ".join(f"{k}={v}" for k, v in s.static_scores.items())
        effect_str = ", ".join(f"{k}={v}" for k, v in s.metrics.items()
                               if k in ("ctr", "dwell_time") and v > 0)
        if effect_str:
            lines.append(f"- 静态[{static_str}] → 实效[{effect_str}]")
    return "\n".join(lines) if len(lines) > 1 else ""
