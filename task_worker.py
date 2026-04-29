"""Background task worker — runs as a subprocess."""
import sys
import json
import traceback
from datetime import datetime


def _update(task_id, progress, best_score=None, log_entry=None):
    from task_manager import update_progress
    update_progress(task_id, progress, best_score, log_entry)


def _check_stop(task_id) -> bool:
    from task_manager import is_stop_requested
    return is_stop_requested(task_id)


def _finish(task_id, status, result=None):
    from task_manager import finish_task
    finish_task(task_id, status, result)


def run_batch_score(task_id, params):
    from room import load_room
    from data_io import list_sessions, save_session
    from llm import get_provider
    from rubric import score_script, compute_effect_score, compute_total_score, load_weight_config
    from models import RatchetState

    room = load_room(params["room_id"])
    all_sessions = list_sessions(params["room_id"])
    # 支持只评指定 session 或只评未评分的
    filter_ids = params.get("session_ids")
    unscored_only = params.get("unscored_only", False)
    if filter_ids:
        sessions = [s for s in all_sessions if s.id in filter_ids]
    elif unscored_only:
        sessions = [s for s in all_sessions if s.total_score <= 0]
    else:
        sessions = all_sessions
    wc = load_weight_config()
    scorer = get_provider(params["scorer"]["provider"], params["scorer"]["key"], params["scorer"]["model"])
    state = RatchetState.load(room.ratchet_state_path())
    all_metrics = [s.metrics for s in all_sessions]

    best_session = None
    best_score = -1
    scored = 0

    for i, s in enumerate(sessions):
        if _check_stop(task_id):
            _update(task_id, f"已停止 ({scored}/{len(sessions)})", best_score,
                    f"用户停止，已评 {scored} 场")
            break
        _update(task_id, f"评分 {i+1}/{len(sessions)}", best_score)
        try:
            dwell = s.metrics.get("dwell_time", 0)
            result = score_script(s.script, scorer, state.locked_constraints, wc, dwell_seconds=dwell)
            s.static_scores = result["scores"]
            s.rubric_reasoning = result.get("reasoning", {})
            s.static_total = result["static_score"]
            s.scorer_model = f"{params['scorer']['provider']}/{params['scorer']['model']}"
            eff_total, eff_scores = compute_effect_score(s.metrics, state.effect_baselines, wc, all_sessions_metrics=all_metrics)
            s.effect_scores = eff_scores
            s.effect_total = eff_total
            s.total_score = compute_total_score(s.static_total, eff_total)
            save_session(s)
            scored += 1
            if s.total_score > best_score:
                best_score = s.total_score
                best_session = s
            _update(task_id, f"评分 {scored}/{len(sessions)}", best_score,
                    f"{s.id[:10]}: {s.total_score:.1f}")
        except Exception as e:
            _update(task_id, f"评分 {i+1}/{len(sessions)}", best_score,
                    f"{s.id[:10]}: 失败 — {str(e)[:80]}")

    if best_session:
        overall_best = best_session
        overall_score = best_score
        for s in all_sessions:
            if s.total_score > overall_score:
                overall_score = s.total_score
                overall_best = s
        room.baseline_session_id = overall_best.id
        if overall_best.prompt:
            room.base_prompt = overall_best.prompt
        room.save()

    _finish(task_id, "stopped" if _check_stop(task_id) else "completed", {
        "scored": scored, "total": len(sessions),
        "best_session_id": best_session.id if best_session else "",
        "best_score": best_score,
    })


def run_auto_iterate(task_id, params):
    from room import load_room
    from data_io import list_sessions, load_session
    from llm import get_provider
    from rubric import (score_script, compute_effect_score, compute_total_score,
                        get_effective_weights, load_weight_config)
    from hill_climb import (generate_improvement, generate_prompt_improvement,
                            generate_script_from_prompt, decide)
    from models import RatchetState, Candidate
    from room import save_candidate
    import uuid

    room = load_room(params["room_id"])
    session = load_session(params["session_id"], params["room_id"])
    sessions = list_sessions(params["room_id"])
    state = RatchetState.load(room.ratchet_state_path())
    wc = params.get("weight_config") or load_weight_config()
    mode = params.get("mode", "script")
    threshold = params.get("threshold", 10.0)
    max_rounds = params.get("max_rounds", 5)
    prev_rounds = 0

    # continue_iterate: 从 candidate 状态继续
    cand_id = params.get("candidate_id")
    if cand_id:
        from room import load_candidate
        cand = load_candidate(room, cand_id)
        if cand:
            c_script = cand.generated_script if cand.mode == "prompt" and cand.generated_script else cand.content
            best_content = cand.content
            best_script = c_script
            best_total = cand.total_score
            best_static = dict(cand.static_scores or {})
            best_effect = dict(cand.effect_scores or {})
            mode = cand.mode
            prev_rounds = cand.rounds
        else:
            _finish(task_id, "failed", {"error": f"Candidate {cand_id} not found"})
            return
    else:
        current_prompt = session.prompt or room.base_prompt
        best_content = current_prompt if mode == "prompt" else session.script
        best_script = session.script
        best_total = session.total_score
        best_static = dict(session.static_scores)
        best_effect = dict(session.effect_scores or {})
    completed_rounds = 0
    dwell = session.metrics.get("dwell_time", 0)
    dim_fail_counts: dict[str, int] = {}
    skip_dims: set[str] = set()
    all_metrics = [s.metrics for s in sessions]

    _update(task_id, f"开始迭代，基线 {best_total:.1f}", best_total)

    for r in range(1, int(max_rounds) + 1):
        if _check_stop(task_id):
            _update(task_id, f"已停止于轮{r}，最高分 {best_total:.1f}", best_total, "用户停止")
            break
        try:
            opt = get_provider(params["optimizer"]["provider"], params["optimizer"]["key"], params["optimizer"]["model"])
            scorer = get_provider(params["scorer"]["provider"], params["scorer"]["key"], params["scorer"]["model"])
            gen_cfg = params.get("generator", params["optimizer"])
            gen = get_provider(gen_cfg["provider"], gen_cfg["key"], gen_cfg["model"])

            static_dims, _ = get_effective_weights(wc)
            cands = [{"id": d["id"], "name": d["name"], "type": "static",
                      "score": best_static.get(d["id"], 0),
                      "gain": (10 - best_static.get(d["id"], 0)) * d["weight"]}
                     for d in static_dims if d["weight"] > 0 and d["id"] not in skip_dims]
            if not cands:
                _update(task_id, f"轮{r}: 所有维度已跳过，停止", best_total, "所有维度已跳过")
                break
            dim_target = max(cands, key=lambda x: x["gain"])

            _update(task_id, f"轮{r}/{max_rounds}: 优化 {dim_target['name']}（{dim_target['score']}/10）", best_total,
                    f"轮{r}: 优化 {dim_target['name']}")

            if mode == "prompt" and best_content:
                new_content = generate_prompt_improvement(
                    best_content, best_script, dim_target, best_static,
                    state.locked_constraints, opt, room.product_info,
                    original_prompt=room.original_prompt)
                new_script = generate_script_from_prompt(new_content, gen, baseline_script=best_script)
            else:
                new_content = generate_improvement(best_script, dim_target, best_static, state.locked_constraints, opt)
                new_script = new_content

            nr = score_script(new_script, scorer, state.locked_constraints, wc, dwell_seconds=dwell)
            new_static_total = nr["static_score"]
            new_eff, new_eff_scores = compute_effect_score(session.metrics, state.effect_baselines, wc, all_sessions_metrics=all_metrics)
            new_total = compute_total_score(new_static_total, new_eff)

            if new_total > best_total:
                old = best_total
                best_content = new_content
                best_script = new_script
                best_total = new_total
                best_static = nr["scores"]
                best_effect = new_eff_scores
                completed_rounds += 1
                dim_fail_counts[dim_target["id"]] = 0
                _update(task_id, f"轮{r}: {old:.1f}→{new_total:.1f} ✅", best_total,
                        f"轮{r}: {dim_target['name']} {old:.1f}→{new_total:.1f} ✅")
            else:
                dim_fail_counts[dim_target["id"]] = dim_fail_counts.get(dim_target["id"], 0) + 1
                msg = f"轮{r}: {dim_target['name']} {new_total:.1f} ❌ ({dim_fail_counts[dim_target['id']]}/2)"
                _update(task_id, f"轮{r}: 回滚 {new_total:.1f}<{best_total:.1f}", best_total, msg)
                if dim_fail_counts[dim_target["id"]] >= 2:
                    skip_dims.add(dim_target["id"])
                    _update(task_id, f"轮{r}: {dim_target['name']} 跳过", best_total,
                            f"  ⏭️ {dim_target['name']} 连续2次未提升，跳过")

            target_score = session.total_score * (1 + threshold / 100)
            if best_total >= target_score:
                _update(task_id, f"达到目标 {target_score:.1f}，停止", best_total, "达到目标")
                break

        except Exception as e:
            dim_id = dim_target["id"] if "dim_target" in dir() and dim_target else None
            if dim_id:
                dim_fail_counts[dim_id] = dim_fail_counts.get(dim_id, 0) + 1
                if dim_fail_counts[dim_id] >= 2:
                    skip_dims.add(dim_id)
            _update(task_id, f"轮{r}: 出错", best_total, f"轮{r}: ⚠️ {str(e)[:100]}")
            continue

    cand_result = {}
    if best_total > session.total_score:
        from room import set_baseline
        cand = Candidate(
            id=uuid.uuid4().hex[:8], session_id=session.id, mode=mode,
            content=best_content, generated_script=best_script if mode == "prompt" else "",
            total_score=best_total, static_scores=best_static, effect_scores=best_effect,
            created_at=datetime.now().isoformat(), rounds=prev_rounds + completed_rounds,
        )
        save_candidate(room, cand)
        set_baseline(room, cand)
        cand_result = {"candidate_id": cand.id, "total_score": best_total, "rounds": prev_rounds + completed_rounds}

    _finish(task_id, "stopped" if _check_stop(task_id) else "completed", cand_result)


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    task_id = sys.argv[1]
    from task_manager import load_task
    task = load_task(task_id)
    if not task:
        sys.exit(1)
    try:
        if task.op == "batch_score":
            run_batch_score(task_id, task.params)
        elif task.op in ("auto_iterate", "continue_iterate"):
            run_auto_iterate(task_id, task.params)
        else:
            _finish(task_id, "failed", {"error": f"Unknown op: {task.op}"})
    except Exception as e:
        _finish(task_id, "failed", {"error": str(e), "traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
