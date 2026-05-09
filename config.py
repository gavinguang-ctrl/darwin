from pathlib import Path
from dotenv import load_dotenv
import os, json

load_dotenv(Path(__file__).parent / ".env")

BASE_DIR = Path(__file__).parent

# config.json 覆盖 .env（首页保存的配置优先）
_config_json = BASE_DIR / "config.json"
if _config_json.exists():
    for k, v in json.loads(_config_json.read_text(encoding="utf-8")).items():
        if v and isinstance(v, str):
            os.environ[k] = v
DATA_DIR = BASE_DIR / "data"
ROOMS_DIR = DATA_DIR / "rooms"

ROOMS_DIR.mkdir(parents=True, exist_ok=True)
TASKS_DIR = DATA_DIR / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)

MAX_HILL_CLIMB_ROUNDS = 3
STAGNATION_THRESHOLD = 2
SCRIPT_MAX_LENGTH_RATIO = 1.5

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_PROXY_URL = os.getenv("OPENAI_PROXY_URL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_PROXY_URL = os.getenv("ANTHROPIC_PROXY_URL", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_PROXY_KEY = os.getenv("GOOGLE_PROXY_KEY", "")
GOOGLE_PROXY_URL = os.getenv("GOOGLE_PROXY_URL", "")
ZMENG_AUTH_TOKEN = os.getenv("ZMENG_AUTH_TOKEN", "")
ZMENG_COOKIE = os.getenv("ZMENG_COOKIE", "")


def get_default_models() -> dict:
    """返回全局默认模型配置 {scorer: {provider, model}, optimizer: {...}, generator: {...}}"""
    _cfg_file = BASE_DIR / "config.json"
    cfg = {}
    if _cfg_file.exists():
        cfg = json.loads(_cfg_file.read_text(encoding="utf-8"))

    def _parse(val, fallback_prov, fallback_model):
        if val and "/" in val:
            p, m = val.split("/", 1)
            return {"provider": p, "model": m}
        return {"provider": fallback_prov, "model": fallback_model}

    return {
        "scorer": _parse(cfg.get("DEFAULT_SCORER"), "google（代理）", "gemini-3.1-pro-preview"),
        "optimizer": _parse(cfg.get("DEFAULT_OPTIMIZER"), "anthropic", "claude-opus-4-7"),
        "generator": _parse(cfg.get("DEFAULT_GENERATOR"), "google（代理）", "gemini-3-flash-preview"),
    }

DEFAULT_METRICS = [
    {"name": "GMV", "key": "gmv", "direction": "higher", "weight": 1.0},
    {"name": "直播单量", "key": "order_volume", "direction": "higher", "weight": 1.0},
    {"name": "ROI", "key": "roi", "direction": "higher", "weight": 1.0},
    {"name": "商品点击率", "key": "ctr", "direction": "higher", "weight": 1.0},
    {"name": "用户停留时长", "key": "dwell_time", "direction": "higher", "weight": 1.0},
    {"name": "转粉率", "key": "follow_rate", "direction": "higher", "weight": 1.0},
]


def get_global_locked_prompt() -> str:
    """读取全局锁定提示词描述，取不到返回空串。"""
    _cfg_file = BASE_DIR / "config.json"
    if not _cfg_file.exists():
        return ""
    try:
        return json.loads(_cfg_file.read_text(encoding="utf-8")).get("GLOBAL_LOCKED_PROMPT", "") or ""
    except Exception:
        return ""


def get_effective_locked_prompt(room) -> str:
    """直播间覆盖优先；勾选使用全局时回退到全局；都空则空串。"""
    if not getattr(room, "use_global_locked_prompt", True):
        return (getattr(room, "locked_prompt_description", "") or "").strip()
    return get_global_locked_prompt().strip()
