import json
import re
from datetime import datetime
from pathlib import Path
from llm import LLMProvider
from distill_prompts import (
    DISTILL_SYSTEM_PROMPT, build_distill_prompt,
    MULTI_DISTILL_SYSTEM_PROMPT, build_multi_distill_prompt,
    GENERATE_FROM_PROMPT_SYSTEM, build_generate_prompt,
    EVALUATE_SYSTEM_PROMPT, build_evaluate_prompt,
    REFINE_SYSTEM_PROMPT, build_refine_prompt,
    FUSE_SYSTEM_PROMPT, build_fuse_prompt,
)
from config import STYLE_PROMPTS_DIR


def distill_single(script_text: str, llm: LLMProvider,
                   product_info: str = "", language: str = "") -> str:
    """从单份口播稿蒸馏出提示词"""
    prompt = build_distill_prompt(script_text, product_info, language)
    return llm.generate(prompt, system=DISTILL_SYSTEM_PROMPT)


def distill_multiple(scripts: list[str], llm: LLMProvider,
                     product_info: str = "", language: str = "") -> str:
    """从多份口播稿蒸馏出统一提示词"""
    prompt = build_multi_distill_prompt(scripts, product_info, language)
    return llm.generate(prompt, system=MULTI_DISTILL_SYSTEM_PROMPT)


def _parse_evaluation_json(response: str) -> dict:
    """从LLM响应中提取评估JSON"""
    match = re.search(r'\{[\s\S]*\}', response)
    if not match:
        raise ValueError("评估响应中未找到JSON")
    return json.loads(match.group())


def generate_with_prompt(distill_prompt: str, product_info: str,
                         llm: LLMProvider, language: str = "") -> str:
    """根据蒸馏提示词生成脚本（用于棘轮验证）"""
    prompt = build_generate_prompt(distill_prompt, product_info, language)
    return llm.generate(prompt, system=GENERATE_FROM_PROMPT_SYSTEM)


def evaluate_reproduction(original: str, reproduced: str, llm: LLMProvider) -> dict:
    """评估复现稿对原稿的还原程度"""
    prompt = build_evaluate_prompt(original, reproduced)
    response = llm.generate(prompt, system=EVALUATE_SYSTEM_PROMPT)
    return _parse_evaluation_json(response)


def refine_prompt(current_prompt: str, original: str, reproduced: str,
                  evaluation: dict, llm: LLMProvider) -> str:
    """根据评估反馈改进蒸馏提示词"""
    prompt = build_refine_prompt(current_prompt, original, reproduced, evaluation)
    return llm.generate(prompt, system=REFINE_SYSTEM_PROMPT)


def fuse_style_into_prompt(base_prompt: str, style_prompt: str, llm: LLMProvider) -> str:
    """把风格提示词 LLM 智能融合进运营/基线提示词，返回融合后的新提示词。"""
    if not style_prompt or not style_prompt.strip():
        return base_prompt
    if not base_prompt or not base_prompt.strip():
        return style_prompt
    prompt = build_fuse_prompt(base_prompt, style_prompt)
    return llm.generate(prompt, system=FUSE_SYSTEM_PROMPT)


# PLACEHOLDER_RATCHET


def ratchet_distill(scripts: list[str], llm: LLMProvider,
                    target_score: int = 85, max_iterations: int = 5,
                    product_info: str = "", language: str = "",
                    progress_callback=None,
                    gen_llm: LLMProvider | None = None,
                    eval_llm: LLMProvider | None = None) -> dict:
    """棘轮迭代蒸馏：蒸馏→生成→评估→改进，直到达标或达到最大迭代次数。

    llm       — 蒸馏与改进提示词所用模型（重推理，建议 optimizer）
    gen_llm   — 生成复现稿所用模型（默认复用 llm，可传 generator）
    eval_llm  — 评估打分所用模型（默认复用 llm，可传 scorer）
    progress_callback(iteration, status, data) — status: 'distill'|'generate'|'evaluate'|'refine'|'done'
    返回: {"final_prompt", "iterations": [...], "stopped_reason"}
    """
    gen_llm = gen_llm or llm
    eval_llm = eval_llm or llm

    # 用第一份原稿作为评估基准（多份时取最长的，信息最丰富）
    reference = max(scripts, key=len) if scripts else ""

    iterations = []

    # 第0轮：初始蒸馏
    if progress_callback:
        progress_callback(0, "distill", {"msg": "初始蒸馏..."})
    if len(scripts) == 1:
        current_prompt = distill_single(scripts[0], llm, product_info, language)
    else:
        current_prompt = distill_multiple(scripts, llm, product_info, language)

    best_prompt = current_prompt
    best_score = -1
    best_evaluation = None
    stopped_reason = "max_iterations"

    for i in range(max_iterations):
        # 用当前提示词生成复现稿
        if progress_callback:
            progress_callback(i + 1, "generate", {"msg": f"第{i+1}轮：生成复现稿..."})
        reproduced = generate_with_prompt(current_prompt, product_info, gen_llm, language)

        # 评估
        if progress_callback:
            progress_callback(i + 1, "evaluate", {"msg": f"第{i+1}轮：评估..."})
        try:
            evaluation = evaluate_reproduction(reference, reproduced, eval_llm)
        except Exception as e:
            evaluation = {"scores": {}, "overall_score": 0, "gaps": [f"评估失败: {e}"], "specific_examples": []}

        score = evaluation.get("overall_score", 0)

        iterations.append({
            "iteration": i + 1,
            "prompt": current_prompt,
            "reproduced": reproduced,
            "evaluation": evaluation,
        })

        # 跟踪最佳
        if score > best_score:
            best_score = score
            best_prompt = current_prompt
            best_evaluation = evaluation

        # 达标则停止
        if score >= target_score:
            stopped_reason = f"reached_target ({score} >= {target_score})"
            if progress_callback:
                progress_callback(i + 1, "done", {"msg": f"达标：{score}/{target_score}", "score": score})
            break

        # 未到最后一轮，继续改进
        if i < max_iterations - 1:
            if progress_callback:
                progress_callback(i + 1, "refine", {"msg": f"第{i+1}轮：得分{score}，改进提示词..."})
            try:
                current_prompt = refine_prompt(current_prompt, reference, reproduced, evaluation, llm)
            except Exception as e:
                stopped_reason = f"refine_error: {e}"
                break

    if progress_callback:
        progress_callback(len(iterations), "done", {
            "msg": f"完成。最佳得分：{best_score}",
            "score": best_score,
        })

    return {
        "final_prompt": best_prompt,
        "final_score": best_score,
        "final_evaluation": best_evaluation,
        "iterations": iterations,
        "stopped_reason": stopped_reason,
    }


# PLACEHOLDER_LIBRARY


def abbreviate_product_name(product_info: str) -> str:
    """从商品信息里取一个简短的默认命名（商品名缩写）。"""
    if not product_info:
        return "风格"
    # 取第一行/第一句
    first = product_info.strip().splitlines()[0].strip()
    # 去掉常见分隔后的描述，保留主体
    first = re.split(r"[|｜,，:：\-—]", first)[0].strip()
    words = first.split()
    if words and all(re.match(r"^[A-Za-z0-9.]+$", w) for w in words[:3]):
        # 英文名取前两个词
        return " ".join(words[:2])[:24] or "风格"
    return first[:16] or "风格"


def save_style_prompt(name: str, distill_prompt: str, source_info: dict) -> Path:
    """保存风格提示词到风格库。"""
    STYLE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w]", "_", name)[:30]
    path = STYLE_PROMPTS_DIR / f"{ts}_{slug}.json"
    data = {
        "name": name,
        "created_at": datetime.now().isoformat(),
        "distill_prompt": distill_prompt,
        "source_info": source_info,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_style_prompts() -> list[dict]:
    """列出风格库中所有风格提示词（按时间倒序）。"""
    STYLE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    prompts = []
    for f in sorted(STYLE_PROMPTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["file_path"] = str(f)
        prompts.append(data)
    return prompts


def rename_style_prompt(file_path: str, new_name: str) -> None:
    """重命名风格提示词（只改 name 字段，文件名保持稳定）。"""
    p = Path(file_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["name"] = new_name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_style_prompt(file_path: str) -> None:
    """删除风格提示词文件。"""
    Path(file_path).unlink(missing_ok=True)


