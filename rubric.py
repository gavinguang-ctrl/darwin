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
        "id": "hook", "name": "黄金3秒", "weight": 7,
        "desc": "每个15-30秒循环的前3秒是否有强力Hook，能否阻止新进观众滑走",
        "ten": "每个循环前3秒有明确Hook（震撼数据/反常识提问/利益承诺/痛点直击），零废话，新观众3秒内获得留下的理由",
        "one": "开头是寒暄、自我介绍或冗长铺垫，3秒内无任何价值信号",
        "techniques": ["震撼数据: '30,000 repeat buyers can't be wrong...'", "反常识提问: 'Why are you still paying $50 for something that costs $12?'", "利益前置: 'Save 70% right now...'", "痛点直击: 'Still struggling with dry skin every winter?'", "制造好奇: 'I'm about to show you something most people don't know...'"],
        "affects": ["dwell_time"],
    },
    {
        "id": "product_demo", "name": "单点卖点", "weight": 5,
        "desc": "每个循环是否只聚焦一个卖点并说透？多个卖点应分布在不同循环中，不要在一个循环内堆砌",
        "ten": "每个循环聚焦一个卖点，用数字/场景/对比具体说明，听众5秒内明白该卖点的价值",
        "one": "一个循环里堆砌3-5个卖点，或只有抽象形容词（'very good quality'），无具体支撑",
        "techniques": ["单点聚焦: 每个循环只说一个卖点，说透", "具体数字: 'lasts 12 hours' not 'long-lasting'", "使用前后对比: 'Before: oily by noon. After: fresh until midnight'", "场景化: 'Picture yourself waking up with perfect skin...'", "感官描述: 描述触感/效果而非成分列表"],
        "affects": ["ctr", "dwell_time"],
    },
    {
        "id": "golden_loop", "name": "循环结构", "weight": 7,
        "desc": "脚本是否由多个15-30秒独立循环组成？每个循环是一个完整推销闭环（Hook→单个卖点+价格→CTA），不同循环换不同卖点",
        "ten": "脚本清晰分为多个15-30秒循环，每个循环结构完整（Hook→Benefit→Price→CTA），循环间无冗长过渡，不同循环切入角度不同",
        "one": "脚本是一整块连续叙述，无循环结构，用户从中间进入需要听完前文才能理解",
        "techniques": ["按15-30秒切分脚本为独立循环块", "每个循环必须包含Hook→单个卖点→价格→CTA完整闭环", "不同循环用不同卖点/角度推同一产品", "循环间用1句话自然过渡而非长段落", "每个循环自成一体，无需前文即可理解"],
        "affects": ["dwell_time", "ctr"],
    },
    {
        "id": "closing", "name": "行动号召CTA", "weight": 7,
        "desc": "每个循环末尾是否有明确CTA？包括具体点击路径指引+紧迫感/稀缺性",
        "ten": "每个循环有具体CTA路径（'click the yellow basket bottom left'）+FOMO元素（数量/时间稀缺），不同循环CTA表述有变化",
        "one": "全篇无CTA，或CTA模糊（'go check it out'），无任何紧迫感",
        "techniques": ["具体路径指引: 'Click the yellow basket in the bottom left corner'", "数量稀缺: 'Only 5 left at this price'", "时间稀缺: 'This deal ends when the livestream ends'", "互动引导: 'Type 1 in the chat if you want the link'", "CTA变体: 每个循环换不同表达避免听觉疲劳"],
        "affects": ["ctr"],
    },
    {
        "id": "pacing", "name": "节奏密度", "weight": 5,
        "desc": "句子是否短而密集？无废话、无冗余过渡、无空洞填充词，TTS播放时保持高信息密度",
        "ten": "平均句长15词以内，无填充词，每句话推进信息或推动行动，节奏紧凑",
        "one": "长复杂句（30+词），大量填充词（'you know', 'basically'），信息稀疏，TTS播放拖沓",
        "techniques": ["短句: 每句不超过15个词", "删填充词: 去掉 'you know', 'basically', 'honestly'", "信息密度: 每句至少一个有价值信息点", "节奏变化: 用3-5词超短句制造强调（'Trust me.' 'Game changer.'）", "删冗余过渡: 去掉 'moving on to', 'let me tell you about'"],
        "affects": ["dwell_time"],
    },
    {
        "id": "pain_points", "name": "痛点速击", "weight": 5,
        "desc": "用户听到的前5秒内是否被戳中痛点？痛点必须具体、可感知、与产品解决方案直接关联",
        "ten": "每个循环前5秒触达一个具体痛点，痛点→解法过渡在一句话内完成",
        "one": "无痛点描述，或痛点抽象（'you have problems'），或痛点与产品无关",
        "techniques": ["场景痛点: 'Tired of foundation sliding off by noon?'", "金钱痛点: 'Stop wasting money on products that don't work'", "社交痛点: 'Embarrassed by flaky skin at meetings?'", "痛点→解法一句话: '...that's exactly why we created...'", "痛点堆叠: 先戳痛再放大（'And it gets worse when...'）"],
        "affects": ["dwell_time", "ctr"],
    },
    {
        "id": "price_anchor", "name": "价格锚点", "weight": 5,
        "desc": "每个循环是否建立价格对比？原价→直播价 或 竞品价→直播价，让观众10秒内感知'超值'",
        "ten": "每个循环有清晰价格锚（原价/竞品/日均成本对比），价格在卖点之后、CTA之前",
        "one": "全篇无价格信息，或只报当前价格无对比基准",
        "techniques": ["原价对比: 'Original price $99, today only $39'", "竞品对比: 'Similar products cost $80, ours...'", "日均成本: 'Less than a dollar a day for perfect skin'", "价格位置: 放在卖点之后、CTA之前（先建价值再报价）", "价格+赠品: '$39 and you also get a free travel size'"],
        "affects": ["ctr"],
    },
    {
        "id": "reentry", "name": "入场信号", "weight": 4,
        "desc": "脚本是否每15-30秒有上下文重置？新进入的观众立即理解当前在讲什么，无需听过前文",
        "ten": "每个循环开头自然重新提及产品名和当前话题，新观众无需前文即可跟上",
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
- 观众随机时刻进入直播间，平均只停留15-30秒
- 你评分的是：如果观众从任意位置开始听15-30秒，这段内容的效果如何

评分原则：
- 10分：每个15-30秒片段都完美体现该维度，参见各维度的满分标准
- 7-9分：多数片段做到了，有少量遗漏
- 4-6分：部分片段做到了，但不一致
- 1-3分：几乎没有体现该维度，参见各维度的最差标准

请严格按照各维度的满分/最差标准打分（1-10），并给出简短理由。
输出必须是纯 JSON 格式。"""


WORDS_PER_MINUTE = 250
DEFAULT_DWELL_SECONDS = 30
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


def _longest_common_substring_len(a: str, b: str) -> tuple[int, str]:
    """Return (length, substring) of the longest common substring."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0, ""
    # Optimize: limit to reasonable size to avoid O(m*n) memory on huge scripts
    if m > 5000:
        a = a[:5000]
        m = 5000
    if n > 5000:
        b = b[:5000]
        n = 5000
    prev = [0] * (n + 1)
    best_len = 0
    best_end = 0
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best_len:
                    best_len = curr[j]
                    best_end = i
        prev = curr
    return best_len, a[best_end - best_len:best_end]


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
