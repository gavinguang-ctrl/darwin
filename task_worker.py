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
    from rubric import score_script, compute_effect_score, compute_total_score, load_weight_config, calibrate_dwell_time
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
    calibrated_metrics = []
    for s in all_sessions:
        m = dict(s.metrics)
        m["dwell_time"] = calibrate_dwell_time(m.get("dwell_time", 0), s.timestamp)
        calibrated_metrics.append(m)

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
            dwell = calibrate_dwell_time(s.metrics.get("dwell_time", 0), s.timestamp)
            result = score_script(s.script, scorer, state.locked_constraints, wc, dwell_seconds=dwell)
            s.static_scores = result["scores"]
            s.rubric_reasoning = result.get("reasoning", {})
            s.static_total = result["static_score"]
            s.scorer_model = f"{params['scorer']['provider']}/{params['scorer']['model']}"
            eff_total, eff_scores = compute_effect_score(s.metrics, state.effect_baselines, wc, all_sessions_metrics=calibrated_metrics)
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
                        get_effective_weights, load_weight_config, calibrate_dwell_time)
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

    from config import get_effective_locked_prompt
    locked_desc = get_effective_locked_prompt(room)
    reference_snippet = params.get("reference_snippet", "")

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
    dwell = calibrate_dwell_time(session.metrics.get("dwell_time", 0), session.timestamp)
    dwell_multiplier = params.get("dwell_multiplier", 1)
    dwell = dwell * dwell_multiplier
    dim_fail_counts: dict[str, int] = {}
    skip_dims: set[str] = set()
    calibrated_metrics = []
    for s in sessions:
        m = dict(s.metrics)
        m["dwell_time"] = calibrate_dwell_time(m.get("dwell_time", 0), s.timestamp)
        calibrated_metrics.append(m)

    _update(task_id, f"开始迭代，基线 {best_total:.1f}", best_total)

    r = 0
    while r < int(max_rounds):
        r += 1
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
                    original_prompt=room.original_prompt,
                    locked_description=locked_desc,
                    reference_snippet=reference_snippet)
                new_script = generate_script_from_prompt(new_content, gen, baseline_script=best_script,
                                                         locked_description=locked_desc)
            else:
                new_content = generate_improvement(best_script, dim_target, best_static, state.locked_constraints, opt,
                                                   locked_description=locked_desc,
                                                   reference_snippet=reference_snippet)
                new_script = new_content

            nr = score_script(new_script, scorer, state.locked_constraints, wc, dwell_seconds=dwell)
            new_static_total = nr["static_score"]
            new_eff, new_eff_scores = compute_effect_score(session.metrics, state.effect_baselines, wc, all_sessions_metrics=calibrated_metrics)
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
            max_rounds += 1
            _update(task_id, f"轮{r}: 出错（已补偿+1轮）", best_total, f"轮{r}: ⚠️ {str(e)[:100]}")
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

        # 自动链式触发跨脚本去重（1轮×50样本）
        if mode == "prompt" and not _check_stop(task_id) and params.get("generator"):
            try:
                from task_manager import create_task as _ct
                dedupe_params = {
                    "room_id": room.id,
                    "candidate_id": cand.id,
                    "sample_size": 50,
                    "max_rounds": 1,
                    "optimizer": params["optimizer"],
                    "generator": params["generator"],
                }
                dt = _ct(room.id, "dedupe_optimize", dedupe_params,
                         desc=f"「{room.name}」方案{cand.id[:8]}去重 1轮×50样本（自动）")
                cand_result["dedupe_task_id"] = dt.id
                _update(task_id, f"已完成，自动去重已启动", best_total, f"自动去重任务 {dt.id}")
            except Exception:
                pass

    _finish(task_id, "stopped" if _check_stop(task_id) else "completed", cand_result)


def run_dedupe_optimize(task_id, params):
    """跨脚本去重优化：对一个 prompt 方案，迭代降低多次生成的脚本之间重复率。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from room import load_room, save_candidate, load_candidate
    from llm import get_provider
    from rubric import compute_cross_script_repetition
    from hill_climb import generate_script_from_prompt, generate_dedupe_improvement
    from models import RatchetState, Candidate
    import uuid

    room = load_room(params["room_id"])
    source_cand = load_candidate(room, params["candidate_id"])
    if not source_cand:
        _finish(task_id, "failed", {"error": f"Candidate {params['candidate_id']} not found"})
        return

    sample_size = int(params.get("sample_size", 50))
    max_rounds = int(params.get("max_rounds", 5))
    state = RatchetState.load(room.ratchet_state_path())

    from config import get_effective_locked_prompt
    locked_desc = get_effective_locked_prompt(room)

    best_prompt = source_cand.content
    baseline_script = source_cand.generated_script or ""

    def _gen_scripts(prompt_text: str, gen_provider_cfg: dict) -> list[str]:
        """并发生成 N 个脚本，限制并发数 3 避免触发限流。"""
        scripts = []
        errors = []
        def _call():
            gen = get_provider(gen_provider_cfg["provider"], gen_provider_cfg["key"], gen_provider_cfg["model"])
            return generate_script_from_prompt(prompt_text, gen, baseline_script=baseline_script,
                                               locked_description=locked_desc)

        with ThreadPoolExecutor(max_workers=3) as exe:
            futures = [exe.submit(_call) for _ in range(sample_size)]
            for i, fut in enumerate(as_completed(futures)):
                if _check_stop(task_id):
                    break
                try:
                    scripts.append(fut.result())
                    _update(task_id, f"生成 {len(scripts)}/{sample_size}", None)
                except Exception as e:
                    errors.append(str(e)[:150])
        if errors and len(scripts) < sample_size // 2:
            # 记录最常见的错误前3条
            from collections import Counter
            top = Counter(errors).most_common(3)
            _update(task_id, f"生成 {len(scripts)}/{sample_size}（失败 {len(errors)}）", None,
                    f"⚠️ 主要错误: {top[0][0]}")
        return scripts

    # 初始评估
    _update(task_id, f"初始评估：生成 {sample_size} 个脚本", 0, f"基线方案 {source_cand.id}")
    initial_scripts = _gen_scripts(best_prompt, params["generator"])
    if _check_stop(task_id) or len(initial_scripts) < 2:
        _finish(task_id, "stopped" if _check_stop(task_id) else "failed",
                {"error": "样本不足，无法评估"})
        return
    rep = compute_cross_script_repetition(initial_scripts)
    best_rep_ratio = rep["avg_ratio"]
    best_max_ratio = rep["max_ratio"]
    best_top_pairs = rep["top_pairs"]
    _update(task_id, f"初始重复率 {best_rep_ratio*100:.1f}%", (1 - best_rep_ratio) * 100,
            f"初始 avg={best_rep_ratio*100:.1f}% max={best_max_ratio*100:.1f}%")

    initial_rep_ratio = best_rep_ratio
    initial_max_ratio = best_max_ratio
    completed_rounds = 0
    r = 0
    while r < max_rounds:
        r += 1
        if _check_stop(task_id):
            _update(task_id, f"已停止于轮{r}", (1 - best_rep_ratio) * 100, "用户停止")
            break
        try:
            opt = get_provider(params["optimizer"]["provider"], params["optimizer"]["key"], params["optimizer"]["model"])
            _update(task_id, f"轮{r}/{max_rounds}: 优化 prompt",
                    (1 - best_rep_ratio) * 100, f"轮{r}: 生成新版提示词")

            new_prompt = generate_dedupe_improvement(
                best_prompt, best_rep_ratio, best_top_pairs,
                state.locked_constraints, opt, locked_description=locked_desc)

            _update(task_id, f"轮{r}/{max_rounds}: 评估 {sample_size} 个新脚本",
                    (1 - best_rep_ratio) * 100)
            new_scripts = _gen_scripts(new_prompt, params["generator"])
            if _check_stop(task_id):
                break
            if len(new_scripts) < 2:
                max_rounds += 1
                _update(task_id, f"轮{r}: 样本不足（已补偿+1轮）",
                        (1 - best_rep_ratio) * 100, f"轮{r}: ⚠️ 生成失败过多")
                continue

            new_rep = compute_cross_script_repetition(new_scripts)
            new_ratio = new_rep["avg_ratio"]
            new_max = new_rep["max_ratio"]

            # 优先比较均值，均值相同时比较最大值
            improved = (new_ratio < best_rep_ratio) or (new_ratio == best_rep_ratio and new_max < best_max_ratio)
            if improved:
                old_avg, old_max = best_rep_ratio, best_max_ratio
                best_prompt = new_prompt
                best_rep_ratio = new_ratio
                best_max_ratio = new_max
                best_top_pairs = new_rep["top_pairs"]
                completed_rounds += 1
                tag = "✅" if new_ratio < old_avg else "✅(max优化)"
                _update(task_id, f"轮{r}: avg {old_avg*100:.1f}%→{new_ratio*100:.1f}% max {old_max*100:.1f}%→{new_max*100:.1f}% {tag}",
                        (1 - best_rep_ratio) * 100,
                        f"轮{r}: avg {old_avg*100:.1f}%→{new_ratio*100:.1f}% max {old_max*100:.1f}%→{new_max*100:.1f}% {tag}")
            else:
                _update(task_id, f"轮{r}: avg {new_ratio*100:.1f}% max {new_max*100:.1f}% ❌（保留原版）",
                        (1 - best_rep_ratio) * 100,
                        f"轮{r}: 新版 avg {new_ratio*100:.1f}% max {new_max*100:.1f}% 未优于当前 avg {best_rep_ratio*100:.1f}% max {best_max_ratio*100:.1f}% ❌")
        except Exception as e:
            max_rounds += 1
            _update(task_id, f"轮{r}: 出错（已补偿+1轮）",
                    (1 - best_rep_ratio) * 100, f"轮{r}: ⚠️ {str(e)[:100]}")
            continue

    cand_result = {
        "initial_rep_ratio": initial_rep_ratio,
        "final_rep_ratio": best_rep_ratio,
        "initial_max_ratio": initial_max_ratio,
        "final_max_ratio": best_max_ratio,
    }
    improved_overall = (best_rep_ratio < initial_rep_ratio) or \
                       (best_rep_ratio == initial_rep_ratio and best_max_ratio < initial_max_ratio)
    if improved_overall:
        new_cand = Candidate(
            id=uuid.uuid4().hex[:8],
            session_id=source_cand.session_id,
            mode=source_cand.mode,
            content=best_prompt,
            generated_script=baseline_script,
            total_score=source_cand.total_score,
            static_scores=source_cand.static_scores,
            effect_scores=source_cand.effect_scores,
            created_at=datetime.now().isoformat(),
            rounds=completed_rounds,
        )
        save_candidate(room, new_cand)
        cand_result["candidate_id"] = new_cand.id

    _finish(task_id, "stopped" if _check_stop(task_id) else "completed", cand_result)


def run_translate(task_id, params):
    """翻译候选方案的提示词到指定语言。"""
    from room import load_room, load_candidate
    from llm import get_provider
    from prompts import TRANSLATION_SYSTEM_PROMPT, build_translation_prompt

    room = load_room(params["room_id"])
    cand = load_candidate(room, params["candidate_id"])
    if not cand:
        _finish(task_id, "failed", {"error": f"Candidate {params['candidate_id']} not found"})
        return

    target_language = params["target_language"]
    target_label = params.get("target_label", target_language)

    if _check_stop(task_id):
        _finish(task_id, "stopped", {})
        return

    _update(task_id, f"翻译为 {target_label} 中…", None, f"调用 {params['optimizer']['provider']}/{params['optimizer']['model']}")

    try:
        translator = get_provider(params["optimizer"]["provider"], params["optimizer"]["key"], params["optimizer"]["model"])
        output = translator.generate(
            build_translation_prompt(cand.content, target_language),
            system=TRANSLATION_SYSTEM_PROMPT,
        )
    except Exception as e:
        _finish(task_id, "failed", {"error": str(e)[:500]})
        return

    if _check_stop(task_id):
        _finish(task_id, "stopped", {})
        return

    _finish(task_id, "completed", {
        "translation": output,
        "target_language": target_language,
        "target_label": target_label,
        "candidate_id": cand.id,
        "chars": len(output),
    })


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
        elif task.op == "dedupe_optimize":
            run_dedupe_optimize(task_id, task.params)
        elif task.op == "translate":
            run_translate(task_id, task.params)
        else:
            _finish(task_id, "failed", {"error": f"Unknown op: {task.op}"})
    except Exception as e:
        _finish(task_id, "failed", {"error": str(e), "traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
