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

# 复刻蒸馏：风格提示词库
STYLE_PROMPTS_DIR = DATA_DIR / "style_prompts"
STYLE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

MAX_HILL_CLIMB_ROUNDS = 3
STAGNATION_THRESHOLD = 2
SCRIPT_MAX_LENGTH_RATIO = 1.5

# ===== darwin-skill 2.0 升级 =====
# 多评委共识评分：评分次数
CONSENSUS_JUDGES = 3
# 连续边际增益早停：连续 N 轮增益低于阈值则停止
MARGINAL_GAIN_THRESHOLD = 1.5  # 单轮增益低于此视为"边际"
MARGINAL_GAIN_CONSECUTIVE = 2  # 连续几轮边际增益则停止
# 自动重写触发：第1轮增益低于此值则触发探索性重写
AUTO_REWRITE_THRESHOLD = 2.0
# 维度相关性集群
DIMENSION_CLUSTERS = {
    "attraction": ["hook", "pain_points", "reentry"],       # 吸引力簇
    "conversion": ["product_demo", "price_anchor", "closing"],  # 转化力簇
    "structure": ["golden_loop", "pacing"],                 # 结构力簇
}
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

# ===== 复刻蒸馏：音频转写 / Kalodata / Chrome =====
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
AUDIO_SEGMENT_MINUTES = 10

# Kalodata 需要代理访问（默认走本地 Clash 代理）
KALODATA_PROXY = os.getenv("KALODATA_PROXY", "http://127.0.0.1:7890")

# 复刻蒸馏用的独立 Chrome（系统真实 chrome.exe + 独立配置目录）
CHROME_PATH = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHROME_USER_DATA = os.getenv(
    "CHROME_USER_DATA",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"),
)
CHROME_PROFILE = os.getenv("CHROME_PROFILE", "Default")
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))

SUPPORTED_LANGUAGES = {
    "zh": "中文",
    "en": "English",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu",
    "tl": "Filipino",
    "ja": "日本語",
    "ko": "한국어",
}

SUPPORTED_COUNTRIES = {
    "MY": "马来西亚",
    "ID": "印尼",
    "TH": "泰国",
    "VN": "越南",
    "PH": "菲律宾",
    "US": "美国",
    "UK": "英国",
}



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
        # 复刻蒸馏与融合用重推理模型，复用 optimizer 配置
        "distill": _parse(cfg.get("DEFAULT_OPTIMIZER"), "anthropic", "claude-opus-4-7"),
    }


def api_key_for(provider_name: str) -> str:
    """按 provider 名返回对应 API key。"""
    if provider_name == "openai":
        return OPENAI_API_KEY
    if provider_name == "anthropic":
        return ANTHROPIC_API_KEY
    if provider_name.startswith("google"):
        return GOOGLE_API_KEY
    return ""


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
