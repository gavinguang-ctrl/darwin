def classify_priority(metric_comparison: list[dict], static_scores: dict[str, int],
                      session_history: list[dict] | None = None) -> dict:
    for m in metric_comparison:
        if m["status"] == "DECLINED" and m.get("baseline") and m["baseline"] > 0:
            drop = (m["baseline"] - m["current"]) / m["baseline"]
            if drop > 0.2:
                return {"level": "P0", "reason": f"{m['key']} 暴跌 {drop:.0%}", "action": "先救火：分析该指标下降原因"}

    if session_history and len(session_history) >= 2:
        recent = session_history[-2:]
        declining_keys = set()
        for h in recent:
            for c in h.get("comparison", []):
                if c["status"] == "DECLINED":
                    declining_keys.add(c["key"])
        if declining_keys:
            return {"level": "P1", "reason": f"连续下降: {', '.join(declining_keys)}", "action": "重点关注持续下降的指标"}

    critical_dims = ["hook", "closing", "golden_loop"]
    for dim_id in critical_dims:
        if static_scores.get(dim_id, 10) < 5:
            name = {"hook": "黄金3秒", "closing": "行动号召CTA", "golden_loop": "循环结构"}[dim_id]
            return {"level": "P2", "reason": f"{name} 仅 {static_scores[dim_id]} 分", "action": "修复脚本结构性问题"}

    engagement_dims = ["price_anchor", "reentry"]
    for dim_id in engagement_dims:
        if static_scores.get(dim_id, 10) < 5:
            name = {"price_anchor": "价格锚点", "reentry": "入场信号"}[dim_id]
            return {"level": "P2", "reason": f"{name} 仅 {static_scores[dim_id]} 分", "action": "提升转化支撑"}

    return {"level": "P3", "reason": "无紧急问题", "action": "打磨细节（节奏、过渡、痛点）"}
