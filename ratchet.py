from config import DEFAULT_METRICS
from models import RatchetState, Session


def get_metric_direction(key: str) -> str:
    for m in DEFAULT_METRICS:
        if m["key"] == key:
            return m["direction"]
    return "higher"


def compare_metrics(session: Session, state: RatchetState) -> list[dict]:
    results = []
    for key, current in session.metrics.items():
        baseline = state.baselines.get(key)
        direction = get_metric_direction(key)

        if baseline is None:
            status = "NEW"
        elif direction == "higher":
            if current > baseline:
                status = "IMPROVED"
            elif current == baseline:
                status = "HELD"
            else:
                status = "DECLINED"
        else:
            if current < baseline:
                status = "IMPROVED"
            elif current == baseline:
                status = "HELD"
            else:
                status = "DECLINED"

        results.append({
            "key": key,
            "current": current,
            "baseline": baseline,
            "status": status,
        })
    return results


def update_baselines(state: RatchetState, comparison: list[dict]) -> dict[str, float]:
    updated = dict(state.baselines)
    for m in comparison:
        key = m["key"]
        if m["status"] in ("IMPROVED", "NEW"):
            updated[key] = m["current"]
    return updated


def lock_elements(state: RatchetState, elements: list[dict], session_id: str) -> list[dict]:
    new_constraints = list(state.locked_constraints)
    for el in elements:
        new_constraints.append({
            "element": el["element"],
            "reason": el["reason"],
            "locked_at_session": session_id,
            "metric_impact": el.get("metric_impact", {}),
        })
    return new_constraints


def get_improvement_targets(comparison: list[dict]) -> list[dict]:
    return [m for m in comparison if m["status"] in ("DECLINED", "HELD") and m["baseline"] is not None]


def ratchet_step(session: Session, state: RatchetState, confirmed_locks: list[dict]) -> RatchetState:
    comparison = compare_metrics(session, state)
    new_baselines = update_baselines(state, comparison)
    new_constraints = lock_elements(state, confirmed_locks, session.id)
    targets = get_improvement_targets(comparison)

    new_state = RatchetState(
        baselines=new_baselines,
        locked_constraints=new_constraints,
        improvement_targets=[t["key"] for t in targets],
        iteration_count=state.iteration_count + 1,
        history=state.history + [{
            "session_id": session.id,
            "metrics_snapshot": dict(session.metrics),
            "baselines_after": dict(new_baselines),
            "new_locks": [el["element"] for el in confirmed_locks],
            "comparison": comparison,
            "total_score": session.total_score,
        }],
        effect_baselines=_update_effect_baselines(state.effect_baselines, session.metrics),
        stagnation_count=state.stagnation_count,
    )
    return new_state


def _update_effect_baselines(current: dict[str, float], metrics: dict[str, float]) -> dict[str, float]:
    from rubric import EFFECT_METRICS
    updated = dict(current)
    for m in EFFECT_METRICS:
        key = m["id"]
        val = metrics.get(key, 0)
        if val > updated.get(key, 0):
            updated[key] = val
    return updated
