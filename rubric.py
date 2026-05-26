import json
import re
import time
from datetime import datetime as _dt
from pathlib import Path
from llm import LLMProvider
from config import DATA_DIR

WEIGHT_CONFIG_FILE = DATA_DIR / "weight_config.json"

NIGHT_DWELL_DISCOUNT = 0.6


def calibrate_dwell_time(dwell_seconds: float, timestamp: str) -> float:
    """凌晨场(00-06点)停留时长打折，消除挂机影响"""
    try:
        hour = _dt.fromisoformat(timestamp).hour
        if 0 <= hour < 6:
            return dwell_seconds * NIGHT_DWELL_DISCOUNT
    except Exception:
        pass
    return dwell_seconds

STATIC_DIMENSIONS = [
    {
        "id": "hook", "name": "黄金3秒", "weight": 9,
        "desc": "每个30-45秒循环的前3-5秒是否有强力Hook，1句话抓兴趣并预告本循环的核心价值",
        "ten": "每个循环前3-5秒有明确Hook（震撼数据/反常识提问/利益承诺/痛点直击），1句话同时抓兴趣+预告价值，新观众3-5秒内获得继续听下去的强烈理由",
        "one": "开头是寒暄、自我介绍或冗长铺垫，3-5秒内无任何价值信号或仅平淡陈述",
        "techniques": ["震撼数据: '30,000 repeat buyers can't be wrong...'", "反常识提问: 'Why are you still paying $50 for something that costs $12?'", "利益前置: 'Save 70% right now...'", "痛点直击: 'Still struggling with dry skin every winter?'", "制造好奇 + 预告: 'I'm about to show you the one ingredient that...'", "Hook + 价值预告: 在抓兴趣的同一句里暗示本循环要讲的卖点"],
        "affects": ["dwell_time"],
    },
    {
        "id": "product_demo", "name": "单点卖点深度介绍", "weight": 7,
        "desc": "每个循环用15-22秒深度介绍一个卖点，用数据/场景/原理/对比把卖点讲透，让观众听完能复述",
        "ten": "每个循环聚焦一个卖点，用具体数据+使用场景+作用原理+前后对比把卖点讲透，听众听完30秒能清楚转述这个卖点的价值",
        "one": "一个循环里堆砌3-5个卖点，或只有抽象形容词（'very good quality'），无具体支撑，听众听完不知道产品好在哪",
        "techniques": ["单点聚焦深化: 每个循环只说一个卖点，用15-22秒说透", "具体数字: 'lasts 12 hours' not 'long-lasting'", "原理说明: 解释为什么有效（成分/工艺/技术原理）", "使用前后对比: 'Before: oily by noon. After: fresh until midnight'", "场景化演示: 'Picture yourself on a 10-hour flight...'", "感官描述: 触感/视觉/效果而非成分列表", "权威背书: 临床数据/认证/专家推荐"],
        "affects": ["ctr", "dwell_time"],
    },
    {
        "id": "golden_loop", "name": "循环结构", "weight": 7,
        "desc": "脚本是否由多个30-45秒独立循环组成？每个循环结构：Hook(3-5s)→卖点深化(15-22s)→社交证明(3-5s)→CTA+价格(8-13s)",
        "ten": "脚本清晰分为多个30-45秒循环，每个循环结构完整（Hook→卖点深化→社交证明→CTA+价格），循环间无冗长过渡，不同循环切入角度不同",
        "one": "脚本是一整块连续叙述，无循环结构；或循环过短（<25秒）卖点未说透，或循环过长（>50秒）信息冗余",
        "techniques": ["按30-45秒切分脚本为独立循环块", "每循环包含: Hook(3-5s) → 卖点深化(15-22s) → 社交证明(3-5s) → CTA+价格(8-13s)", "不同循环用不同卖点/角度推同一产品", "循环间用1句话自然过渡而非长段落", "每个循环自成一体，无需前文即可理解"],
        "affects": ["dwell_time", "ctr"],
    },
    {
        "id": "closing", "name": "行动号召CTA", "weight": 3,
        "desc": "循环末尾8-13秒是否从容讲清价格对比+具体路径指引？要清晰但不重复逼单，不喧宾夺主",
        "ten": "循环末尾8-13秒包含清晰的价格对比+具体路径指引（'click the yellow basket bottom left'）+适度紧迫感，CTA简洁不重复，不同循环CTA表述有变化",
        "one": "全篇无CTA，或CTA模糊（'go check it out'）；或反向：高频重复CTA轰炸（每5秒喊一次'快下单'）",
        "techniques": ["具体路径指引: 'Click the yellow basket in the bottom left corner'", "适度紧迫感: 'Only 5 left at this price'（不要每个循环都喊）", "CTA简洁: 1-2句话讲清，不要反复重复", "CTA变体: 每个循环换不同表达，避免听觉疲劳", "CTA前置价值: 在CTA前先讲清值得购买的理由（已在卖点深化里）"],
        "affects": ["ctr"],
    },
    {
        "id": "pacing", "name": "节奏密度", "weight": 5,
        "desc": "信息密度高但允许必要展开。短句推进节奏，但讲卖点原理/场景时允许更长的解释句，避免单纯追求短句导致信息缺失",
        "ten": "Hook和CTA用短句推进节奏，卖点深化部分允许15-25词的解释句来讲透原理/场景，整体无填充词，每句推进信息",
        "one": "全篇短句堆砌但卖点说不透；或长复杂句（30+词）+大量填充词（'you know', 'basically'），信息稀疏",
        "techniques": ["Hook/CTA用短句（≤10词）制造节奏", "卖点深化允许15-25词的解释句", "删填充词: 去掉 'you know', 'basically', 'honestly'", "信息密度: 每句至少一个有价值信息点", "节奏变化: 用3-5词超短句制造强调（'Trust me.' 'Game changer.'）"],
        "affects": ["dwell_time"],
    },
    {
        "id": "pain_points", "name": "痛点速击", "weight": 5,
        "desc": "每个循环前8-12秒（Hook 之后、卖点深化之前）是否触达一个具体痛点？痛点→解法过渡自然",
        "ten": "每个循环前8-12秒触达一个具体痛点，痛点→产品解法过渡在2句话内完成，痛点具体可感知",
        "one": "无痛点描述，或痛点抽象（'you have problems'），或痛点与产品无关",
        "techniques": ["场景痛点: 'Tired of foundation sliding off by noon?'", "金钱痛点: 'Stop wasting money on products that don't work'", "社交痛点: 'Embarrassed by flaky skin at meetings?'", "痛点→解法过渡: '...that's exactly why we created...'", "痛点堆叠: 先戳痛再放大（'And it gets worse when...'）"],
        "affects": ["dwell_time", "ctr"],
    },
    {
        "id": "price_anchor", "name": "价格锚点", "weight": 5,
        "desc": "每个循环在卖点深化之后、CTA之中（8-13秒CTA区间内）从容建立价格对比：原价/竞品/日均成本",
        "ten": "每个循环有清晰价格锚（原价/竞品/日均成本对比），从容讲清而非快速带过；价格在卖点说透之后出现",
        "one": "全篇无价格信息；或价格出现在卖点之前（未建立价值就报价）；或只报当前价格无对比基准",
        "techniques": ["原价对比: 'Original price $99, today only $39'", "竞品对比: 'Similar products cost $80, ours...'", "日均成本: 'Less than a dollar a day for perfect skin'", "价格位置: 卖点深化之后、与CTA一起放在循环末尾8-13秒", "价格+赠品: '$39 and you also get a free travel size'", "从容讲清: 至少花5-8秒讲价格对比，不要1秒带过"],
        "affects": ["ctr"],
    },
    {
        "id": "reentry", "name": "入场信号", "weight": 4,
        "desc": "脚本是否每30-45秒有上下文重置？新进入的观众立即理解当前在讲什么，无需听过前文",
        "ten": "每个循环开头自然重新提及产品名和当前卖点话题，新观众无需前文即可跟上",
        "one": "大量'as I mentioned', 'like I said earlier'等前文依赖表达，新观众一头雾水",
        "techniques": ["每个循环开头重新提及产品名/品牌名", "避免'as I was saying'等前文引用", "'If you just joined, we're talking about...'类重置句（每3-4个循环一次）", "每个循环自带足够上下文，不依赖前文", "用产品名代替代词（'this product' → 'the XYZ serum'）"],
        "affects": ["dwell_time"],
    },
]

OLD_TO_NEW_DIM_MAP = {"interaction": "golden_loop", "trust": "price_anchor", "structure": "reentry"}

def migrate_scores(scores: dict) -> dict:
    return {OLD_TO_NEW_DIM_MAP.get(k, k): v for k, v in scores.items()}

EFFECT_METRICS = [
    {"id": "ctr",        "name": "商品点击率",     "weight": 20},
    {"id": "dwell_time", "name": "平均用户在线时长", "weight": 20},
]


def load_weight_config() -> dict:
    if WEIGHT_CONFIG_FILE.exists():
        return json.loads(WEIGHT_CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        "static": {d["id"]: d["weight"] for d in STATIC_DIMENSIONS},
        "effect": {m["id"]: m["weight"] for m in EFFECT_METRICS},
    }


def save_weight_config(config: dict):
    WEIGHT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEIGHT_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_effective_weights(config: dict | None = None) -> tuple[list[dict], list[dict]]:
    """返回应用了自定义权重的 (static_dims, effect_metrics)"""
    if config is None:
        config = load_weight_config()
    static = []
    for d in STATIC_DIMENSIONS:
        w = config.get("static", {}).get(d["id"], d["weight"])
        static.append({**d, "weight": w})
    effect = []
    for m in EFFECT_METRICS:
        w = config.get("effect", {}).get(m["id"], m["weight"])
        effect.append({**m, "weight": w})
    return static, effect

SCORER_SYSTEM_PROMPT = """你是一位严格的 TikTok 直播脚本质量评审官。
你的唯一任务是对直播脚本片段进行客观评分，不提供任何优化建议。

核心前提：
- 脚本用于AI数字人直播+TTS朗读，纯口播内容（无动作/表情/画面辅助）
- 观众随机时刻进入直播间，平均停留30-45秒
- 你评分的是：如果观众从任意位置开始听30-45秒，这段内容的效果如何

评分优先级：
- **强 Hook + 卖点深度** 是核心：Hook 是否能抓兴趣并预告价值，卖点是否被用数据/场景/原理/对比说透
- CTA 简洁明确即可，**不奖励高频重复逼单**——把 closing 维度看作"循环末尾有清晰路径指引"而非"反复喊话"

评分原则：
- 10分：每个30-45秒片段都完美体现该维度，参见各维度的满分标准
- 7-9分：多数片段做到了，有少量遗漏
- 4-6分：部分片段做到了，但不一致
- 1-3分：几乎没有体现该维度，参见各维度的最差标准

请严格按照各维度的满分/最差标准打分（1-10），并给出简短理由。
输出必须是纯 JSON 格式。"""


WORDS_PER_MINUTE = 250
DEFAULT_DWELL_SECONDS = 38
NUM_WINDOWS = 10


def _extract_windows(script: str, dwell_seconds: float) -> list[str]:
    window_chars = max(100, int(dwell_seconds / 60 * WORDS_PER_MINUTE))
    total = len(script)
    if total <= window_chars:
        return [script]
    n = min(NUM_WINDOWS, max(1, total // window_chars))
    step = max(1, (total - window_chars) // (n - 1)) if n > 1 else 0
    windows = []
    for i in range(n):
        start = min(i * step, total - window_chars)
        windows.append(script[start:start + window_chars])
    return windows


def build_scoring_prompt(script: str, locked_constraints: list[dict] | None = None,
                         weight_config: dict | None = None,
                         dwell_seconds: float = 0,
                         window_index: int = 0, total_windows: int = 1) -> str:
    static_dims, _ = get_effective_weights(weight_config)

    if dwell_seconds > 0:
        context = f"用户平均停留 {dwell_seconds:.0f} 秒。以下是用户可能听到的脚本片段（第{window_index+1}/{total_windows}段，模拟不同时间进入的用户）。"
    else:
        context = "请对以下直播脚本进行质量评分。"

    parts = [f"{context}\n"]
    parts.append("## 脚本内容\n")
    parts.append(script)
    parts.append("\n\n## 评分维度\n")
    for d in static_dims:
        parts.append(f"- **{d['name']}**（权重{d['weight']}）: {d['desc']}")
        if d.get('ten'):
            parts.append(f"  - 满分(10): {d['ten']}")
        if d.get('one'):
            parts.append(f"  - 最差(1): {d['one']}")

    if locked_constraints:
        parts.append("\n\n## 参考：已验证有效的要素\n")
        for c in locked_constraints:
            parts.append(f"- {c['element']}")

    parts.append("""\n\n## 输出格式
请严格输出以下 JSON，不要输出其他内容：
```json
{
  "scores": {"hook": 7, "product_demo": 8, "golden_loop": 6, "closing": 7, "pacing": 5, "pain_points": 6, "price_anchor": 7, "reentry": 8},
  "reasoning": {"hook": "理由...", "product_demo": "理由...", "golden_loop": "理由...", "closing": "理由...", "pacing": "理由...", "pain_points": "理由...", "price_anchor": "理由...", "reentry": "理由..."}
}
```""")
    return "\n".join(parts)


def parse_rubric_scores(llm_response: str) -> dict:
    match = re.search(r'\{[\s\S]*\}', llm_response)
    if not match:
        raise ValueError("LLM 响应中未找到 JSON")
    data = json.loads(match.group())
    if "scores" not in data:
        raise ValueError("JSON 中缺少 scores 字段")
    return data


def compute_static_score(scores: dict[str, int], weight_config: dict | None = None) -> float:
    static_dims, _ = get_effective_weights(weight_config)
    total = sum(scores.get(d["id"], 0) * d["weight"] for d in static_dims)
    return round(total / 10, 1)


def compute_effect_score(metrics: dict[str, float], baselines: dict[str, float],
                         weight_config: dict | None = None,
                         all_sessions_metrics: list[dict] | None = None) -> tuple[float, dict[str, float]]:
    """返回 (实效总分, {指标id: 1-10分})。用百分位排名映射到1-10分。"""
    _, effect_mets = get_effective_weights(weight_config)
    effect_scores = {}
    for m in effect_mets:
        current = metrics.get(m["id"], 0)
        if all_sessions_metrics and len(all_sessions_metrics) > 1:
            all_vals = sorted(s.get(m["id"], 0) for s in all_sessions_metrics)
            rank = sum(1 for v in all_vals if v < current)
            percentile = rank / (len(all_vals) - 1) if len(all_vals) > 1 else 0.5
            effect_scores[m["id"]] = round(1 + percentile * 9, 1)
        elif current > 0:
            effect_scores[m["id"]] = 5.0
        else:
            effect_scores[m["id"]] = 0.0
    total = sum(effect_scores.get(m["id"], 0) * m["weight"] for m in effect_mets)
    return round(total / 10, 1), effect_scores


def compute_total_score(static_score: float, effect_score: float) -> float:
    return round(static_score + effect_score, 1)


def find_weakest_dimension(static_scores: dict[str, int], effect_scores: dict[str, float],
                           weight_config: dict | None = None) -> dict:
    """找出带权潜在增益最大的维度，即 (10-score)*weight 最大的"""
    static_dims, effect_mets = get_effective_weights(weight_config)
    candidates = []
    for d in static_dims:
        s = static_scores.get(d["id"], 0)
        gain = (10 - s) * d["weight"]
        candidates.append({"id": d["id"], "name": d["name"], "type": "static", "score": s, "weighted": gain})
    for m in effect_mets:
        s = effect_scores.get(m["id"], 0)
        gain = (10 - s) * m["weight"]
        candidates.append({"id": m["id"], "name": m["name"], "type": "effect", "score": s, "weighted": gain})
    return max(candidates, key=lambda x: x["weighted"])


REPETITION_MIN_LEN = 20
REPETITION_MAX_PENALTY = 10


def _longest_common_substring_len(a: str, b: str, min_len: int = None) -> tuple[int, str]:
    """Find longest common substring using rolling-window + seed-and-extend.
    Much faster than DP: O((m+n)*k) expected vs O(m*n).
    Substrings shorter than min_len are ignored (returns 0 if nothing >= min_len).
    """
    if min_len is None:
        min_len = REPETITION_MIN_LEN
    if len(a) < min_len or len(b) < min_len:
        return 0, ""
    # Index all min_len substrings of b
    b_subs: dict[str, int] = {}
    for j in range(len(b) - min_len + 1):
        seed = b[j:j + min_len]
        if seed not in b_subs:
            b_subs[seed] = j

    best_len = 0
    best_str = ""
    i = 0
    while i <= len(a) - min_len:
        seed = a[i:i + min_len]
        j = b_subs.get(seed)
        if j is None:
            i += 1
            continue
        # Extend right
        end_a, end_b = i + min_len, j + min_len
        while end_a < len(a) and end_b < len(b) and a[end_a] == b[end_b]:
            end_a += 1
            end_b += 1
        # Extend left
        start_a, start_b = i, j
        while start_a > 0 and start_b > 0 and a[start_a - 1] == b[start_b - 1]:
            start_a -= 1
            start_b -= 1
        length = end_a - start_a
        if length > best_len:
            best_len = length
            best_str = a[start_a:end_a]
        # Skip past this match in a to avoid redundant work
        i = end_a - min_len + 1 if end_a - min_len + 1 > i + 1 else i + 1
    return best_len, best_str


def compute_repetition_penalty(script: str, dwell_seconds: float = 0) -> dict:
    """检测循环间字面重复，返回扣分信息。"""
    if not dwell_seconds:
        dwell_seconds = DEFAULT_DWELL_SECONDS
    windows = _extract_windows(script, dwell_seconds)
    if len(windows) < 2:
        return {"penalty": 0, "repeat_ratio": 0, "longest_repeat": ""}

    overlaps = []
    longest_repeat = ""
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            lcs_len, lcs_str = _longest_common_substring_len(windows[i], windows[j])
            if lcs_len < REPETITION_MIN_LEN:
                overlaps.append(0)
                continue
            min_len = min(len(windows[i]), len(windows[j]))
            overlap = lcs_len / min_len if min_len > 0 else 0
            overlaps.append(overlap)
            if lcs_len > len(longest_repeat):
                longest_repeat = lcs_str

    repeat_ratio = sum(overlaps) / len(overlaps) if overlaps else 0
    penalty = round(repeat_ratio * REPETITION_MAX_PENALTY, 1)
    return {"penalty": penalty, "repeat_ratio": round(repeat_ratio, 3), "longest_repeat": longest_repeat}


def compute_cross_script_repetition(scripts: list[str]) -> dict:
    """检测多个脚本之间的字面重复。用于跨脚本去重优化。
    返回 {avg_ratio, max_ratio, longest_repeat, top_pairs: [(i, j, lcs_str)]}
    """
    n = len(scripts)
    if n < 2:
        return {"avg_ratio": 0, "max_ratio": 0, "longest_repeat": "", "top_pairs": []}

    overlaps = []
    longest_repeat = ""
    pair_results = []  # (ratio, i, j, lcs_str)
    for i in range(n):
        for j in range(i + 1, n):
            lcs_len, lcs_str = _longest_common_substring_len(scripts[i], scripts[j])
            if lcs_len < REPETITION_MIN_LEN:
                overlaps.append(0)
                continue
            min_len = min(len(scripts[i]), len(scripts[j]))
            overlap = lcs_len / min_len if min_len > 0 else 0
            overlaps.append(overlap)
            pair_results.append((overlap, i, j, lcs_str))
            if lcs_len > len(longest_repeat):
                longest_repeat = lcs_str

    avg_ratio = sum(overlaps) / len(overlaps) if overlaps else 0
    max_ratio = max(overlaps) if overlaps else 0
    # Top 5 worst pairs with their LCS strings
    pair_results.sort(reverse=True)
    top_pairs = [(p[1], p[2], p[3]) for p in pair_results[:5]]
    return {
        "avg_ratio": round(avg_ratio, 3),
        "max_ratio": round(max_ratio, 3),
        "longest_repeat": longest_repeat,
        "top_pairs": top_pairs,
    }


def score_script(script: str, scorer: LLMProvider, locked_constraints: list[dict] | None = None,
                 weight_config: dict | None = None, dwell_seconds: float = 0) -> dict:
    """用独立的 scorer LLM 评分。dwell_seconds>0时用窗口模式。"""
    if dwell_seconds > 0 and len(script) > int(dwell_seconds / 60 * WORDS_PER_MINUTE) * 1.5:
        windows = _extract_windows(script, dwell_seconds)
        n = len(windows)
        # 开头窗口权重略高（更多用户从开头进入），其余均分
        if n == 1:
            weights = [1.0]
        else:
            base = 1.0 / n
            bonus = base * 0.3
            weights = [base + bonus] + [base - bonus / (n - 1)] * (n - 1)

        all_scores = {}
        all_reasoning = {}
        for i, window in enumerate(windows):
            prompt = build_scoring_prompt(window, locked_constraints, weight_config,
                                          dwell_seconds, i, len(windows))
            for attempt in range(3):
                try:
                    response = scorer.generate(prompt, system=SCORER_SYSTEM_PROMPT)
                    result = parse_rubric_scores(response)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            for dim_id, score in result["scores"].items():
                all_scores.setdefault(dim_id, []).append(score * weights[i])
            for dim_id, reason in result.get("reasoning", {}).items():
                all_reasoning.setdefault(dim_id, []).append(f"[片段{i+1}] {reason}")

        merged_scores = {k: round(sum(v), 1) for k, v in all_scores.items()}
        merged_reasoning = {k: " | ".join(v) for k, v in all_reasoning.items()}
        rep = compute_repetition_penalty(script, dwell_seconds)
        static = compute_static_score(merged_scores, weight_config)
        return {
            "scores": merged_scores,
            "reasoning": merged_reasoning,
            "static_score": round(max(0, static - rep["penalty"]), 1),
            "repetition": rep,
        }

    prompt = build_scoring_prompt(script, locked_constraints, weight_config)
    response = scorer.generate(prompt, system=SCORER_SYSTEM_PROMPT)
    result = parse_rubric_scores(response)
    rep = compute_repetition_penalty(script, dwell_seconds)
    static = compute_static_score(result["scores"], weight_config)
    result["static_score"] = round(max(0, static - rep["penalty"]), 1)
    result["repetition"] = rep
    return result


EFFECT_ESTIMATOR_PROMPT = """你是一位 TikTok 直播数据分析专家。
根据直播脚本的质量评分，预估该脚本在实际直播中的实效表现。
你需要基于脚本质量和历史基线数据，给出每个实效指标的预估分数（1-10分）。
10分 = 达到或超越历史最佳，1分 = 远低于历史水平。
输出必须是纯 JSON 格式。"""


def build_effect_estimation_prompt(
    script: str,
    static_scores: dict[str, int],
    baselines: dict[str, float],
    weight_config: dict | None = None,
    correlation_hint: str = "",
) -> str:
    _, effect_mets = get_effective_weights(weight_config)
    parts = ["根据以下脚本和静态评分，预估实际直播效果。\n"]
    parts.append(f"## 脚本（前2000字）\n{script[:2000]}\n")
    parts.append("\n## 静态评分\n")
    for d in STATIC_DIMENSIONS:
        s = static_scores.get(d["id"], 0)
        parts.append(f"- {d['name']}: {s}/10")
    if baselines:
        parts.append("\n\n## 历史实效基线（最佳值）\n")
        for m in effect_mets:
            b = baselines.get(m["id"])
            if b:
                parts.append(f"- {m['name']}: {b}")
    if correlation_hint:
        parts.append(f"\n\n## 历史静态→实效关联数据\n{correlation_hint}")
    parts.append("\n\n## 预估维度\n")
    for m in effect_mets:
        parts.append(f"- **{m['name']}**（权重{m['weight']}）: 预估 1-10 分")
    parts.append("""\n\n## 预估逻辑
- 黄金3秒Hook强 + 入场信号好 → 停留时长高（新观众被抓住并快速获得上下文）
- 痛点速击准 + 节奏密度高 → 停留时长高（观众被戳中且不无聊）
- 循环结构好 → 停留时长高 + 商品点击率高（任何入场点都能获得完整推销闭环）
- 单点卖点清晰 + 价格锚点明确 → 商品点击率高（知道产品好且觉得值）
- 行动号召CTA强 + 价格锚点好 → 商品点击率高（知道怎么买且觉得是好deal）
- 循环结构是基础：循环结构差则其他维度效果打折
- 参考历史基线，10分=达到历史最佳

## 输出格式
```json
{"ctr": 7, "dwell_time": 6, "reasoning": "简短预估理由"}
```""")
    return "\n".join(parts)


def estimate_effect_scores(
    script: str,
    static_scores: dict[str, int],
    baselines: dict[str, float],
    scorer: LLMProvider,
    weight_config: dict | None = None,
    correlation_hint: str = "",
) -> tuple[float, dict[str, float]]:
    """用 LLM 预估实效分数，返回 (实效总分, {指标id: 1-10分})"""
    prompt = build_effect_estimation_prompt(script, static_scores, baselines, weight_config, correlation_hint)
    response = scorer.generate(prompt, system=EFFECT_ESTIMATOR_PROMPT)
    match = re.search(r'\{[\s\S]*\}', response)
    if not match:
        _, effect_mets = get_effective_weights(weight_config)
        return 0.0, {m["id"]: 5.0 for m in effect_mets}
    data = json.loads(match.group())
    _, effect_mets = get_effective_weights(weight_config)
    effect_scores = {}
    for m in effect_mets:
        effect_scores[m["id"]] = min(10, max(0, float(data.get(m["id"], 5))))
    total = sum(effect_scores[m["id"]] * m["weight"] for m in effect_mets)
    return round(total / 10, 1), effect_scores
