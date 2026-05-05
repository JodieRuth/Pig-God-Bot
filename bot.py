import asyncio
import base64
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, TextIO

from PIL import Image, ImageSequence

import aiohttp
import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CACHE_ROOT = ROOT / "cache"
CACHE_DIR = CACHE_ROOT / "images"
OUTPUT_DIR = ROOT / "outputs"
COMMAND_DIR = ROOT / "command"
TOOLS_DIR = ROOT / "tools"
PLUGIN_DIR = ROOT / "plugins"
LOG_DIR = ROOT / "logs"
COMMAND_NICKNAME_FILE = ROOT / "command_nickname.json"
RUNTIME_STATE_FILE = ROOT / "runtime_state.json"
PROMPTS_FILE = ROOT / "prompts.json"


def clear_cache_dir() -> None:
    if CACHE_ROOT.exists():
        shutil.rmtree(CACHE_ROOT)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


clear_cache_dir()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
COMMAND_DIR.mkdir(parents=True, exist_ok=True)
PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = Path(os.environ.get("LOCAL_ONEBOT_LOG_FILE", "") or LOG_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}.log")
if not LOG_FILE.is_absolute():
    LOG_FILE = ROOT / LOG_FILE
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
os.environ["LOCAL_ONEBOT_LOG_FILE"] = str(LOG_FILE)
ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr

class TeeStream:
    def __init__(self, stream: TextIO, log_path: Path) -> None:
        self.stream = stream
        self.log_path = log_path

    def write(self, value: str) -> int:
        written = self.stream.write(value)
        self.stream.flush()
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(value)
        except OSError:
            pass
        return written

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return self.stream.isatty()

    @property
    def encoding(self) -> str | None:
        return self.stream.encoding

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


if not isinstance(sys.stdout, TeeStream):
    sys.stdout = TeeStream(sys.stdout, LOG_FILE)
if not isinstance(sys.stderr, TeeStream):
    sys.stderr = TeeStream(sys.stderr, LOG_FILE)
print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Console log file: {LOG_FILE}", flush=True)


ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE, override=True)
_env_mtime = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else 0.0
_prompts_mtime = PROMPTS_FILE.stat().st_mtime if PROMPTS_FILE.exists() else 0.0

ONEBOT_HTTP = os.getenv("ONEBOT_HTTP", "http://127.0.0.1:3000").rstrip("/")
ONEBOT_WS = os.getenv("ONEBOT_WS", "ws://127.0.0.1:3001")
ONEBOT_TOKEN = os.getenv("ONEBOT_TOKEN", "local_onebot_token")
BOT_QQ = os.getenv("BOT_QQ", "3170056734")
BOT_NAME = os.getenv("BOT_NAME", "").strip()
ADMIN_USERS = {int(x) for x in os.getenv("ADMIN_USERS", "").split(",") if x.strip().isdigit()}
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")


def numbered_api_configs(prefix: str) -> list[dict[str, str]]:
    configs: list[dict[str, str]] = []
    legacy_url = os.getenv(f"{prefix}_API_URL", "")
    legacy_key = os.getenv(f"{prefix}_API_KEY", "")
    if legacy_url:
        configs.append({"index": "0", "url": legacy_url, "key": legacy_key})
    index = 1
    while True:
        url = os.getenv(f"{prefix}_API_URL_{index}", "")
        key = os.getenv(f"{prefix}_API_KEY_{index}", "")
        if not url and not key:
            if index > 20:
                break
            index += 1
            continue
        if url:
            configs.append({"index": str(index), "url": url, "key": key})
        index += 1
        if index > 20:
            break
    return configs


def env_active_runtime_state() -> dict[str, Any]:
    return {
        "llm": {"api_index": os.getenv("ACTIVE_LLM_API_INDEX", "0"), "model": os.getenv("ACTIVE_LLM_MODEL", OPENAI_MODEL)},
        "image": {"api_index": os.getenv("ACTIVE_IMAGE_API_INDEX", "0"), "model": os.getenv("ACTIVE_IMAGE_MODEL", IMAGE_MODEL)},
        "prompt": {"id": os.getenv("ACTIVE_PROMPT_ID", "1")},
        "photo": {"enabled": os.getenv("ACTIVE_PHOTO_ENABLED", "1") != "0"},
    }


def default_runtime_state() -> dict[str, Any]:
    return env_active_runtime_state()


def load_runtime_state() -> dict[str, Any]:
    if not RUNTIME_STATE_FILE.exists():
        return default_runtime_state()
    try:
        with RUNTIME_STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_runtime_state()
    if not isinstance(data, dict):
        return default_runtime_state()
    defaults = default_runtime_state()
    for key, value in defaults.items():
        if not isinstance(data.get(key), dict):
            data[key] = value
        else:
            for field, field_value in value.items():
                data[key].setdefault(field, field_value)
    return data


def save_runtime_state(data: dict[str, Any]) -> None:
    tmp = RUNTIME_STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(RUNTIME_STATE_FILE)


def set_env_value(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    target = f"{key}={value}"
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name == key:
            lines[index] = target
            replaced = True
            break
    if not replaced:
        lines.append(target)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def apply_env_active_state_to_runtime() -> None:
    env_state = env_active_runtime_state()
    for kind in ("llm", "image"):
        runtime_state.setdefault(kind, {})["api_index"] = str(env_state[kind]["api_index"])
        runtime_state[kind]["model"] = str(env_state[kind]["model"])
    runtime_state.setdefault("prompt", {})["id"] = str(env_state["prompt"]["id"])
    runtime_state.setdefault("photo", {})["enabled"] = bool(env_state["photo"]["enabled"])
    save_runtime_state(runtime_state)


API_CONFIGS = {
    "llm": numbered_api_configs("LLM"),
    "image": numbered_api_configs("IMAGE"),
}
runtime_state = load_runtime_state()
apply_env_active_state_to_runtime()


def active_api_config(kind: str) -> dict[str, str]:
    state = runtime_state.get(kind, {})
    stored_url = state.get("url", "") if isinstance(state, dict) else ""
    stored_key = state.get("key", "") if isinstance(state, dict) else ""
    configs = API_CONFIGS.get(kind, [])
    if not configs:
        return {"index": "", "url": stored_url, "key": stored_key}
    selected = str(state.get("api_index", configs[0]["index"]) if isinstance(state, dict) else configs[0]["index"])
    for config in configs:
        if config["index"] == selected:
            return {"index": config["index"], "url": stored_url or config["url"], "key": stored_key or config["key"]}
    runtime_state.setdefault(kind, {})["api_index"] = configs[0]["index"]
    save_runtime_state(runtime_state)
    return {"index": configs[0]["index"], "url": stored_url or configs[0]["url"], "key": stored_key or configs[0]["key"]}


def active_model(kind: str) -> str:
    fallback = OPENAI_MODEL if kind == "llm" else IMAGE_MODEL
    return str(runtime_state.get(kind, {}).get("model") or fallback)


def set_active_api_by_model(kind: str, model: str) -> bool:
    configs = API_CONFIGS.get(kind, [])
    if not configs:
        return False
    runtime_state.setdefault(kind, {})["model"] = model
    save_runtime_state(runtime_state)
    return True


def set_active_runtime(kind: str, api_index: str, model: str) -> bool:
    configs = API_CONFIGS.get(kind, [])
    matched = None
    for config in configs:
        if config["index"] == api_index:
            matched = config
            break
    if matched is None:
        return False
    runtime_state.setdefault(kind, {})["api_index"] = api_index
    runtime_state[kind]["model"] = model
    runtime_state[kind]["url"] = matched["url"]
    runtime_state[kind]["key"] = matched["key"]
    save_runtime_state(runtime_state)
    if kind == "llm":
        set_env_value("ACTIVE_LLM_API_INDEX", api_index)
        set_env_value("ACTIVE_LLM_MODEL", model)
    elif kind == "image":
        set_env_value("ACTIVE_IMAGE_API_INDEX", api_index)
        set_env_value("ACTIVE_IMAGE_MODEL", model)
    return True


def load_prompt_configs() -> dict[str, dict[str, Any]]:
    try:
        with PROMPTS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[str(key)] = value
    return result


PROMPT_CONFIGS = load_prompt_configs()


def reload_env_config(force: bool = False) -> bool:
    global _env_mtime, ONEBOT_HTTP, ONEBOT_WS, ONEBOT_TOKEN, BOT_QQ, BOT_NAME, ADMIN_USERS, OPENAI_MODEL, IMAGE_MODEL, API_CONFIGS, DEBUG_LOG
    current_mtime = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else 0.0
    if not force and current_mtime == _env_mtime:
        return False
    load_dotenv(ENV_FILE, override=True)
    _env_mtime = current_mtime
    ONEBOT_HTTP = os.getenv("ONEBOT_HTTP", "http://127.0.0.1:3000").rstrip("/")
    ONEBOT_WS = os.getenv("ONEBOT_WS", "ws://127.0.0.1:3001")
    ONEBOT_TOKEN = os.getenv("ONEBOT_TOKEN", "local_onebot_token")
    BOT_QQ = os.getenv("BOT_QQ", "2579744278")
    BOT_NAME = os.getenv("BOT_NAME", "").strip()
    ADMIN_USERS = {int(x) for x in os.getenv("ADMIN_USERS", "").split(",") if x.strip().isdigit()}
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
    API_CONFIGS = {
        "llm": numbered_api_configs("LLM"),
        "image": numbered_api_configs("IMAGE"),
    }
    apply_env_active_state_to_runtime()
    DEBUG_LOG = os.getenv("DEBUG_LOG", "1") != "0"
    return True


def reload_prompt_configs(force: bool = False) -> bool:
    global _prompts_mtime, PROMPT_CONFIGS
    current_mtime = PROMPTS_FILE.stat().st_mtime if PROMPTS_FILE.exists() else 0.0
    if not force and current_mtime == _prompts_mtime:
        return False
    PROMPT_CONFIGS = load_prompt_configs()
    _prompts_mtime = current_mtime
    active_prompt_id()
    return True


def reload_runtime_files(force: bool = False) -> None:
    env_changed = reload_env_config(force)
    prompts_changed = reload_prompt_configs(force)
    if env_changed:
        log("Reloaded .env runtime config")
    if prompts_changed:
        log("Reloaded prompts.json runtime config")


def active_prompt_id() -> str:
    prompt_state = runtime_state.get("prompt", {})
    prompt_id = str(prompt_state.get("id") or "1") if isinstance(prompt_state, dict) else "1"
    if prompt_id in PROMPT_CONFIGS:
        return prompt_id
    if "1" in PROMPT_CONFIGS:
        runtime_state.setdefault("prompt", {})["id"] = "1"
        save_runtime_state(runtime_state)
        return "1"
    return ""


def active_prompt_config() -> dict[str, Any]:
    prompt_id = active_prompt_id()
    return PROMPT_CONFIGS.get(prompt_id, {})


def set_active_prompt(prompt_id: str) -> bool:
    if prompt_id not in PROMPT_CONFIGS:
        return False
    runtime_state.setdefault("prompt", {})["id"] = prompt_id
    save_runtime_state(runtime_state)
    set_env_value("ACTIVE_PROMPT_ID", prompt_id)
    return True


def photo_enabled() -> bool:
    photo_state = runtime_state.get("photo", {})
    return bool(photo_state.get("enabled", True)) if isinstance(photo_state, dict) else True


def set_photo_enabled(enabled: bool) -> bool:
    runtime_state.setdefault("photo", {})["enabled"] = bool(enabled)
    save_runtime_state(runtime_state)
    set_env_value("ACTIVE_PHOTO_ENABLED", "1" if enabled else "0")
    return True


LLM_API_URL = active_api_config("llm")["url"]
LLM_API_KEY = active_api_config("llm")["key"]
IMAGE_API_URL = active_api_config("image")["url"]
IMAGE_API_KEY = active_api_config("image")["key"]

MAX_CONTEXT_MESSAGES = 30
MAX_CONTEXT_AGE_SECONDS = 30 * 60
MAX_CONTEXT_IMAGES = 10
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
DEBUG_LOG = os.getenv("DEBUG_LOG", "1") != "0"

def prompt_value(key: str) -> str:
    value = active_prompt_config().get(key, "")
    return str(value) if value else ""


def image_generation_tool(description: str, is_admin: bool) -> dict[str, Any]:
    prompt_description = "给图像生成模型的完整中文提示词。必须保留管理员对图1、图2、第一张、第二张等输入图片编号的引用和具体编辑目标，不要自行交换图片顺序，不要删减关键要求。" if is_admin else "给图像生成模型的完整中文提示词。必须保留用户对图1、图2等图片编号的引用和编辑目标。提示词不得包含政治敏感、中国大陆政治不正确、违法违规、色情低俗、隐私侵犯、攻击骚扰等不允许内容。"
    image_indexes_description = "要传给生图工具的图片编号列表，例如 [1,2]。编号来自输入图片顺序：图1 是第一张输入图片，图2 是第二张。管理员明确提到哪些图就传哪些图；若本次是纯文生图或没有明确引用图片，就不要填写任何图片编号。" if is_admin else "要传给生图工具的图片编号列表，例如 [1,2]。编号来自输入图片顺序：图1 是第一张输入图片，图2 是第二张。若本次是纯文生图，就不要填写任何图片编号。"
    notice_description = "发给 QQ 管理员的简短开始提示，例如：收到，开始处理这张图，完成后会带用时回复。" if is_admin else "发给 QQ 用户的简短开始提示，例如：已开始处理这张图，完成后会带用时回复。"
    return {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": prompt_description,
                    },
                    "image_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": image_indexes_description,
                    },
                    "notice": {
                        "type": "string",
                        "description": notice_description,
                    },
                },
                "required": ["prompt"],
            },
        },
    }


contexts: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=MAX_CONTEXT_MESSAGES))
jobs: dict[str, asyncio.Task] = {}
bot_state: dict[str, Any] = {"stopped": False}
group_member_name_cache: dict[tuple[int, int], str] = {}
last_images_by_sender: dict[tuple[str, int], deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=MAX_CONTEXT_IMAGES))

def console_log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)


def log(message: str) -> None:
    if DEBUG_LOG:
        console_log(message)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def compact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "api_key", "key"}:
                result[key] = mask_secret(str(item))
            elif key in {"image_url"} and isinstance(item, dict) and "url" in item and str(item["url"]).startswith("data:image"):
                result[key] = {"url": f"{str(item['url'])[:32]}...<base64 omitted>"}
            elif key in {"b64_json", "image_base64", "base64"}:
                result[key] = "<base64 omitted>"
            else:
                result[key] = compact_payload(item)
        return result
    if isinstance(value, list):
        return [compact_payload(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image"):
        return f"{value[:32]}...<base64 omitted>"
    return value


def log_json(title: str, value: Any) -> None:
    log(f"{title}: {json.dumps(compact_payload(value), ensure_ascii=False, indent=2)}")


def sanitize_error_detail(value: Any, limit: int = 800) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return "未知错误"
    text = re.sub(r'Traceback \(most recent call last\):.*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'File "[^"]+"', 'File "<path redacted>"', text)
    text = re.sub(r'[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+', '<path redacted>', text)
    text = re.sub(r'\\\\[^\\\s]+\\(?:[^\\\s]+\\)*[^\\\s]+', '<path redacted>', text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer ***", text, flags=re.IGNORECASE)
    text = re.sub(r"(Authorization\s*[:=]\s*)[^,;\s}]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"((?:api[_-]?key|key|token|secret)\s*[=:]\s*)[^,;&\s}]+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if "Traceback" in text:
        text = text.split("Traceback", 1)[0].strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def exception_detail(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "TimeoutError: 请求超时"
    if isinstance(exc, aiohttp.ClientResponseError):
        message = sanitize_error_detail(exc.message or "")
        return f"HTTP {exc.status}: {message}" if message and message != "未知错误" else f"HTTP {exc.status}"
    return sanitize_error_detail(f"{type(exc).__name__}: {exc}")


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ONEBOT_TOKEN}"} if ONEBOT_TOKEN else {}


def scope_key(event: dict[str, Any]) -> str:
    if event.get("message_type") == "group":
        return f"group:{event['group_id']}"
    return f"private:{event['user_id']}"


def plain_text(message: list[dict[str, Any]]) -> str:
    parts = []
    for seg in message:
        typ = seg.get("type")
        data = seg.get("data", {})
        if typ == "text":
            parts.append(data.get("text", ""))
        elif typ == "at":
            qq = data.get("qq")
            if qq:
                parts.append(f" @{qq} ")
    return "".join(parts).strip()


def format_at_text(qq: str, group_id: int | None = None) -> str:
    name = ""
    if group_id is not None:
        name = group_member_name_cache.get((group_id, int(qq))) if qq.isdigit() else ""
    return f"@{name}[{qq}]" if name else f"@{qq}"


def message_text(message: list[dict[str, Any]], group_id: int | None = None, strip_bot: bool = False) -> str:
    parts = []
    for seg in message:
        typ = seg.get("type")
        data = seg.get("data", {})
        if typ == "text":
            parts.append(data.get("text", ""))
        elif typ == "at":
            qq = str(data.get("qq") or "")
            if not qq:
                continue
            parts.append(" " if strip_bot and qq == BOT_QQ else f" {format_at_text(qq, group_id)} ")
    return "".join(parts).strip()


def bot_mention_candidates() -> list[str]:
    candidates = []
    for name in (BOT_NAME, "Pig god"):
        value = name.strip()
        if value and value.lower() not in {item.lower() for item in candidates}:
            candidates.append(value)
    return candidates


def strip_text_at_bot(text: str) -> str:
    value = text.strip()
    lower_value = value.lower()
    for name in bot_mention_candidates():
        for prefix in (f"@{name}", f"@ {name}"):
            if lower_value.startswith(prefix.lower()):
                return value[len(prefix):].strip()
    return text.strip()


def text_mentions_bot(text: str) -> bool:
    value = text.strip()
    lower_value = value.lower()
    return any(
        lower_value.startswith(f"@{name}".lower()) or lower_value.startswith(f"@ {name}".lower())
        for name in bot_mention_candidates()
    )


def strip_bot_at(message: list[dict[str, Any]], group_id: int | None = None) -> str:
    return strip_text_at_bot(message_text(message, group_id, strip_bot=True))


def is_at_bot(message: list[dict[str, Any]]) -> bool:
    if any(seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == BOT_QQ for seg in message):
        return True
    return text_mentions_bot(plain_text(message))


async def is_reply_to_bot(message: list[dict[str, Any]], replied: dict[str, Any] | None = None) -> bool:
    if not reply_message_id(message):
        return False
    data = replied if replied is not None else await get_replied_message(message)
    if not data:
        return False
    sender_id = message_sender_id(data)
    return str(sender_id) == BOT_QQ

def image_urls(message: list[dict[str, Any]]) -> list[str]:
    urls = []
    for seg in message:
        if seg.get("type") != "image":
            continue
        data = seg.get("data", {})
        value = data.get("url") or data.get("file")
        if value:
            urls.append(value)
    return urls


def is_controller(event: dict[str, Any]) -> bool:
    user_id = int(event.get("user_id", 0))
    role = event.get("sender", {}).get("role")
    return user_id in ADMIN_USERS or role in {"owner", "admin"}



def recent_context_label(item: dict[str, Any]) -> str:
    if item.get("is_bot"):
        return f"BOT {item['user_id']}"
    return f"QQ {item['user_id']}"


def context_message_records(key: str) -> list[dict[str, Any]]:
    now = time.time()
    records: list[dict[str, Any]] = []
    for item in reversed(contexts[key]):
        if now - item["time"] > MAX_CONTEXT_AGE_SECONDS:
            continue
        message_id = item.get("message_id")
        if message_id is None:
            continue
        text = str(item.get("text") or "").strip()
        records.append({
            "message_id": str(message_id),
            "sender_id": item.get("user_id"),
            "sender_name": item.get("sender_name"),
            "label": recent_context_label(item),
            "text": text[:200],
            "has_images": bool(item.get("images")),
            "is_bot": bool(item.get("is_bot")),
        })
        if len(records) >= MAX_CONTEXT_MESSAGES:
            break
    return list(reversed(records))


def recent_context(key: str) -> tuple[list[str], list[dict[str, Any]]]:
    now = time.time()
    texts: list[str] = []
    images: list[dict[str, Any]] = []
    for item in reversed(contexts[key]):
        if now - item["time"] > MAX_CONTEXT_AGE_SECONDS:
            continue
        if item.get("text"):
            message_id = item.get("message_id")
            prefix = f"消息ID {message_id} " if message_id is not None else ""
            texts.append(f"{prefix}{recent_context_label(item)}: {item['text']}")
        for record in reversed(item.get("images", [])):
            if len(images) < MAX_CONTEXT_IMAGES and image_path(record).exists():
                images.append(record)
    return list(reversed(texts[-MAX_CONTEXT_MESSAGES:])), list(reversed(images))


def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分{sec}秒"
    if minutes:
        return f"{minutes}分{sec}秒"
    return f"{sec}秒"


async def onebot_post(action: str, payload: dict[str, Any]) -> Any:
    log_json("OneBot request", {"action": action, "payload": payload})
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        async with session.post(f"{ONEBOT_HTTP}/{action}", json=payload, timeout=60) as resp:
            text = await resp.text()
            if resp.status >= 400:
                log(f"OneBot {action} failed: HTTP {resp.status} {text}")
                raise RuntimeError(f"OneBot {action} failed: HTTP {resp.status} {text}")
            log(f"OneBot {action} response: HTTP {resp.status} {text[:500]}")
            return json.loads(text) if text else None


def context_text_from_reply(message: str | list[dict[str, Any]]) -> str:
    if isinstance(message, str):
        return message.strip()
    return plain_text(message)


def reply_segments(message_id: Any, message: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if message_id is None:
        if isinstance(message, list):
            return [item for item in message if isinstance(item, dict)]
        return [{"type": "text", "data": {"text": str(message)}}]
    segments = [{"type": "reply", "data": {"id": str(message_id)}}]
    if isinstance(message, list):
        segments.extend([item for item in message if isinstance(item, dict)])
    else:
        segments.append({"type": "text", "data": {"text": str(message)}})
    return segments


async def reply_to_message(event: dict[str, Any], message_id: Any, message: str | list[dict[str, Any]]) -> None:
    await reply(event, reply_segments(message_id, message))


def append_bot_context(event: dict[str, Any], message: str | list[dict[str, Any]], message_id: Any = None) -> None:
    text = context_text_from_reply(message)
    if not text:
        return
    record: dict[str, Any] = {
        "time": time.time(),
        "user_id": int(BOT_QQ) if BOT_QQ.isdigit() else BOT_QQ,
        "sender_name": BOT_NAME or "bot",
        "text": text,
        "images": [],
        "is_bot": True,
    }
    if message_id is not None:
        record["message_id"] = message_id
    contexts[scope_key(event)].append(record)
    log(f"Cached bot reply for context: scope={scope_key(event)} text={text[:200]!r}")


async def reply(event: dict[str, Any], message: str | list[dict[str, Any]]) -> None:
    target = f"group:{event['group_id']}" if event.get("message_type") == "group" else f"private:{event['user_id']}"
    log_json("Reply", {"target": target, "message": message})
    if event.get("message_type") == "group":
        response = await onebot_post("send_group_msg", {"group_id": event["group_id"], "message": message})
    else:
        response = await onebot_post("send_private_msg", {"user_id": event["user_id"], "message": message})
    data = onebot_response_data(response)
    sent_message_id = data.get("message_id") if isinstance(data, dict) else None
    append_bot_context(event, message, sent_message_id)


async def reply_forward(event: dict[str, Any], lines: list[str]) -> None:
    non_empty = [line for line in lines if line]
    if not non_empty:
        return
    node_lines: list[list[str]] = []
    current: list[str] = []
    for line in non_empty:
        current.append(line)
        if len(current) >= 12:
            node_lines.append(current)
            current = []
    if current:
        node_lines.append(current)
    if len(node_lines) <= 1:
        await reply(event, "\n".join(non_empty))
        return
    bot_qq = os.getenv("BOT_QQ", "")
    bot_name = os.getenv("BOT_NAME", "") or "Bot"
    messages: list[dict[str, Any]] = []
    for chunk in node_lines:
        messages.append({
            "type": "node",
            "data": {
                "name": bot_name,
                "uin": bot_qq,
                "content": [{"type": "text", "data": {"text": "\n".join(chunk)}}],
            },
        })
    try:
        if event.get("message_type") == "group":
            await onebot_post("send_group_forward_msg", {"group_id": event["group_id"], "messages": messages})
        else:
            await onebot_post("send_private_forward_msg", {"user_id": event["user_id"], "messages": messages})
    except Exception as exc:
        log(f"Forward message failed, falling back to plain text: {exc}")
        await reply(event, "\n".join(non_empty))


async def download_image(session: aiohttp.ClientSession, url: str) -> Path | None:
    log(f"Image received for download: {url[:200]}")
    if url.startswith("file://"):
        path = Path(url.removeprefix("file:///").removeprefix("file://"))
        log(f"Image is local file: {path}")
        return path if path.exists() else None
    if not url.startswith(("http://", "https://")):
        log("Image skipped: unsupported URL/file format")
        return None

    name = f"{int(time.time())}_{uuid.uuid4().hex}.jpg"
    target = CACHE_DIR / name
    size = 0
    async with session.get(url, timeout=60) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            async for chunk in resp.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    raise RuntimeError("图片超过大小限制")
                f.write(chunk)
    log(f"Image downloaded: {target} ({size} bytes)")
    return target


def image_record(path: Path, sender_id: int, sender_name: str, message_id: Any = None) -> dict[str, Any]:
    record = {
        "path": str(path),
        "sender_id": sender_id,
        "sender_name": sender_name,
    }
    if message_id is not None:
        record["message_id"] = message_id
    return record


def image_path(record: dict[str, Any]) -> Path:
    return Path(record["path"])


def image_sender_label(record: dict[str, Any]) -> str:
    sender_name = str(record.get("sender_name") or "")
    sender_id = record.get("sender_id")
    return f"{sender_name}({sender_id})" if sender_name else str(sender_id)


def onebot_response_data(response: Any) -> Any:
    if isinstance(response, dict) and "data" in response and ("status" in response or "retcode" in response):
        return response.get("data")
    return response


def message_segments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, list):
            return [item for item in message if isinstance(item, dict)]
    return []


def reply_message_id(message: list[dict[str, Any]]) -> str:
    for seg in message:
        if seg.get("type") == "reply":
            value = seg.get("data", {}).get("id")
            if value:
                return str(value)
    return ""


def message_sender_id(data: dict[str, Any]) -> int:
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    value = data.get("user_id") or sender.get("user_id") or 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def message_sender_name(data: dict[str, Any], sender_id: int) -> str:
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    return str(sender.get("card") or sender.get("nickname") or sender_id)


def at_qqs(message: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for seg in message:
        if seg.get("type") != "at":
            continue
        qq = str(seg.get("data", {}).get("qq") or "")
        if qq.isdigit():
            values.append(int(qq))
    return values


async def cache_group_member_names(group_id: int, user_ids: list[int]) -> None:
    for user_id in user_ids:
        key = (group_id, user_id)
        if key in group_member_name_cache:
            continue
        try:
            data = onebot_response_data(await onebot_post("get_group_member_info", {"group_id": group_id, "user_id": user_id, "no_cache": False}))
        except Exception as exc:
            log(f"get_group_member_info failed: group={group_id} user={user_id} error={exception_detail(exc)}")
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("card") or data.get("nickname") or user_id).strip()
        group_member_name_cache[key] = name


async def hydrate_at_names(event: dict[str, Any], *messages: list[dict[str, Any]]) -> None:
    if event.get("message_type") != "group":
        return
    group_id = int(event.get("group_id", 0))
    if not group_id:
        return
    user_ids: list[int] = []
    for message in messages:
        user_ids.extend(at_qqs(message))
    if user_ids:
        await cache_group_member_names(group_id, sorted(set(user_ids)))


async def get_replied_message(message: list[dict[str, Any]]) -> dict[str, Any] | None:
    message_id = reply_message_id(message)
    if not message_id:
        return None
    payload: dict[str, Any] = {"message_id": int(message_id) if message_id.isdigit() else message_id}
    try:
        data = onebot_response_data(await onebot_post("get_msg", payload))
    except Exception as exc:
        log(f"get_msg for reply {message_id} failed: {exception_detail(exc)}")
        return None
    if not isinstance(data, dict):
        log(f"get_msg for reply {message_id} returned non-dict data: {data!r}")
        return None
    log_json("Replied message", data)
    return data


async def cache_image_urls(urls: list[str], sender_id: int, sender_name: str, message_id: Any = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        for url in urls:
            path = await download_image(session, url)
            if path:
                record = image_record(path, sender_id, sender_name, message_id)
                records.append(record)
                log(f"Cached image for context: {path} sender={image_sender_label(record)}")
    return records


async def parse_and_cache(event: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    message = event.get("message", [])
    group_id = int(event.get("group_id", 0)) if event.get("message_type") == "group" else None
    text = strip_bot_at(message, group_id)
    urls = image_urls(message)
    sender_id = int(event.get("user_id", 0))
    sender_name = str(event.get("sender", {}).get("card") or event.get("sender", {}).get("nickname") or sender_id)
    raw_text = message_text(message, group_id)
    log(f"Received message: scope={scope_key(event)} user={sender_id} type={event.get('message_type')} text={raw_text!r} parsed_text={text!r} images={len(urls)}")
    records = await cache_image_urls(urls, sender_id, sender_name, event.get("message_id"))
    cache_sender_images(scope_key(event), sender_id, records)

    contexts[scope_key(event)].append({
        "time": time.time(),
        "message_id": event.get("message_id"),
        "user_id": sender_id,
        "sender_name": sender_name,
        "text": raw_text,
        "images": records,
        "is_bot": str(sender_id) == BOT_QQ,
    })
    return text, records


async def cache_replied_message_context(event: dict[str, Any], replied: dict[str, Any]) -> list[dict[str, Any]]:
    segments = message_segments(replied)
    if not segments:
        return []
    sender_id = message_sender_id(replied)
    sender_name = message_sender_name(replied, sender_id)
    group_id = int(event.get("group_id", 0)) if event.get("message_type") == "group" else None
    text = message_text(segments, group_id)
    urls = image_urls(segments)
    records = await cache_image_urls(urls, sender_id, sender_name, replied.get("message_id"))
    cache_sender_images(scope_key(event), sender_id, records)
    if text or records:
        contexts[scope_key(event)].append({
            "time": time.time(),
            "message_id": replied.get("message_id"),
            "user_id": sender_id,
            "sender_name": sender_name,
            "text": f"被回复消息：{text}" if text else "被回复消息包含图片",
            "images": records,
            "is_bot": str(sender_id) == BOT_QQ,
        })
        log(f"Cached replied message context: sender={sender_name}({sender_id}) text={text[:200]!r} images={len(records)}")
    return records


def read_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{read_image_b64(path)}"


def is_gif_file(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(6) in {b"GIF87a", b"GIF89a"}


def to_static_image(path: Path) -> Path:
    if path.suffix.lower() != ".gif" and not is_gif_file(path):
        return path
    target = path.with_suffix(".png")
    if target.exists():
        return target
    with Image.open(path) as img:
        frame = next(ImageSequence.Iterator(img)).convert("RGBA")
        frame.save(target)
    log(f"GIF converted to first frame: {target}")
    return target


def cache_sender_images(key: str, sender_id: int, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    bucket = last_images_by_sender[(key, sender_id)]
    for record in records:
        bucket.append(record)
    log(f"Cached last images for sender: scope={key} user={sender_id} count={len(bucket)}")


def visible_images_for_sender(key: str, sender_id: int) -> list[dict[str, Any]]:
    indexed = [record for record in last_images_by_sender.get((key, sender_id), []) if image_path(record).exists()]
    if indexed:
        return indexed[-MAX_CONTEXT_IMAGES:]
    images: list[dict[str, Any]] = []
    for item in reversed(contexts[key]):
        if time.time() - item["time"] > MAX_CONTEXT_AGE_SECONDS:
            continue
        for record in reversed(item.get("images", [])):
            if record.get("sender_id") == sender_id and image_path(record).exists() and len(images) < MAX_CONTEXT_IMAGES:
                images.append(record)
    return list(reversed(images))


def build_image_input_note(images: list[dict[str, Any]]) -> str:
    if not images:
        return "当前没有可用图片。"
    lines = ["输入图片按消息/上下文时间顺序编号如下："]
    for index, record in enumerate(images[:MAX_CONTEXT_IMAGES], start=1):
        path = image_path(record)
        lines.append(f"图{index} = 第 {index} 张输入图片，文件名 {path.name}，发送者 {image_sender_label(record)}")
    lines.append("当用户提到图1、图2、第一张、第二张时，必须按这个编号理解；不要自行交换图片顺序。")
    lines.append("如果需要直接回复某一条上下文消息，可以调用 reply_to_context_message，并使用最近上下文里标注的消息ID。该工具调用成功后代表已经完成回复，不要再输出普通文本。")
    lines.append("强制工具规则：只要用户问题涉及任何图片中的人物是谁、角色名、出处、作品来源、像谁、叫什么、人物身份判断，必须优先调用 animetrace_character 工具并传入对应图片编号；不得仅根据上下文、文件名、画风、模型视觉能力或聊天历史猜测后直接回答。")
    return "\n".join(lines)


def build_openai_messages(prompt: str, context_texts: list[str], context_notes: str, images: list[dict[str, Any]], trigger_sender_id: int, system_prompt: str) -> list[dict[str, Any]]:
    context = "\n".join(context_texts[-MAX_CONTEXT_MESSAGES:])
    image_note = build_image_input_note(images)
    policy_note = prompt_image_source_note(images)
    user_text = f"最近群聊上下文：\n{context}\n\n{context_notes}\n\n触发者QQ：{trigger_sender_id}\n\n当前请求：\n{prompt}\n\n{policy_note}\n\n{image_note}" if context else f"{context_notes}\n\n触发者QQ：{trigger_sender_id}\n\n当前请求：\n{prompt}\n\n{policy_note}\n\n{image_note}"
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for record in images[:MAX_CONTEXT_IMAGES]:
        content.append({"type": "image_url", "image_url": {"url": image_data_url(image_path(record))}})
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def build_context_message_note(records: list[dict[str, Any]]) -> str:
    if not records:
        return "最近可直接回复的上下文消息 ID 列表：\n无"
    lines = ["最近可直接回复的上下文消息 ID 列表："]
    for item in records[-MAX_CONTEXT_MESSAGES:]:
        message_id = item.get("message_id")
        label = item.get("label") or ""
        text = item.get("text") or ""
        lines.append(f"message_id={message_id} | {label} | {text}")
    return "\n".join(lines)


def prompt_image_source_note(images: list[dict[str, Any]]) -> str:
    if not images:
        return ""
    lines = ["可用图片及发送者如下："]
    for index, record in enumerate(images[:MAX_CONTEXT_IMAGES], start=1):
        lines.append(f"图{index}：{image_sender_label(record)}")
    lines.append("默认规则：如果触发者本人没有明确要求引用别人发的图，优先只使用触发者本人发送的图片；只有在明确回复他人消息、点名使用他人图片、或用户强烈要求跨发送者编辑时，才可以使用其他人的图片。")
    lines.append("如果用户要求你直接回复某个人或某条消息，优先调用 reply_to_context_message，并使用上下文中标注的消息ID。工具成功后不得再输出普通文本。")
    lines.append("人物识别强制规则：涉及图中角色/人物身份、出处、名字、像谁等问题时，必须先调用 animetrace_character，不能先自行推断。")
    return "\n".join(lines)


def is_group_mentioned_command(message: list[dict[str, Any]], text: str) -> bool:
    if not is_at_bot(message):
        return False
    stripped = text.lstrip()
    if stripped.startswith("/"):
        return True
    return stripped.lower().startswith(tuple(f"{name.lower()}/" for name in bot_mention_candidates())) or stripped.lower().startswith(tuple(f"{name.lower()} /" for name in bot_mention_candidates()))



def normalize_group_command_text(message: list[dict[str, Any]], text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("/"):
        return stripped
    lower_value = stripped.lower()
    for name in bot_mention_candidates():
        for prefix in (f"{name}/", f"{name} /"):
            if lower_value.startswith(prefix.lower()):
                remainder = stripped[len(prefix):].strip()
                if remainder.startswith("/"):
                    return remainder
                return f"/{remainder}" if remainder else ""
    return stripped

def is_admin_user(user_id: int) -> bool:
    return user_id in ADMIN_USERS


def format_admin_users() -> str:
    return ", ".join(str(user_id) for user_id in sorted(ADMIN_USERS)) or "无"


def select_system_prompt(user_id: int) -> str:
    reload_runtime_files()
    if is_admin_user(user_id):
        return prompt_value("admin_system_prompt").format(admin_users=format_admin_users())
    return prompt_value("system_prompt")


def select_tools(user_id: int) -> list[dict[str, Any]]:
    reload_runtime_files()
    return [tool.copy() for tool in TOOL_DEFINITIONS]


async def call_chat_model(event: dict[str, Any], prompt: str, context_texts: list[str], images: list[dict[str, Any]], trigger_sender_id: int, system_prompt: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    reload_runtime_files()
    llm_config = active_api_config("llm")
    llm_url = llm_config["url"]
    llm_key = llm_config["key"]
    llm_model = active_model("llm")
    if not llm_url:
        image_note = f"，并带有 {len(images)} 张上下文图片" if images else ""
        return {"type": "text", "text": f"已收到：{prompt}{image_note}\n\n请在 .env 里配置 OpenAI 兼容的 LLM_API_URL 后接入真实文本/多模态 API。"}

    messages = build_openai_messages(prompt, context_texts, build_context_message_note(context_message_records(scope_key(event))), images, trigger_sender_id, system_prompt)

    headers = {"Authorization": f"Bearer {llm_key}"} if llm_key else {}
    tool_runtime = {
        "event": event,
        "prompt": prompt,
        "context_texts": context_texts,
        "images": images,
        "context_messages": context_message_records(scope_key(event)),
        "trigger_sender_id": trigger_sender_id,
        "system_prompt": system_prompt,
    }
    tool_lookup = TOOL_EXECUTORS

    for _ in range(4):
        payload = {
            "model": llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        log_json("LLM request", {"url": llm_url, "payload": payload, "headers": headers})
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(llm_url, json=payload, timeout=600) as resp:
                text = await resp.text()
                log(f"LLM response status={resp.status} body={text[:1000]}")
                if resp.status >= 400:
                    raise RuntimeError(f"LLM HTTP {resp.status}: {sanitize_error_detail(text[:1000])}")
                data = json.loads(text)
                message = data["choices"][0]["message"]
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    log_json("LLM tool calls", tool_calls)
                    assistant_message = {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls}
                    messages.append(assistant_message)
                    for tool_call in tool_calls:
                        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                        tool_name = str(function.get("name") or "").strip().lower()
                        raw_args = function.get("arguments") or "{}"
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        executor = tool_lookup.get(tool_name)
                        if not executor:
                            result = {"ok": False, "content": f"工具调用失败：未找到工具 {tool_name or 'unknown'}"}
                        else:
                            try:
                                result = await executor(args if isinstance(args, dict) else {}, tool_runtime, command_context())
                            except Exception as exc:
                                result = {"ok": False, "content": f"工具调用失败：{exception_detail(exc)}"}
                        tool_result_text = str(result.get("content") or "")
                        tool_call_id = str(tool_call.get("id") or uuid.uuid4().hex)
                        if tool_result_text:
                            if tool_name == "reply_to_context_message" and result.get("ok"):
                                return {"type": "answered_by_tool", "text": ""}
                            messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_text})
                        log_json("Tool execution result", {"tool": tool_name, "result": result})
                reply_text = message.get("content") or ""
                log(f"LLM reply parsed: {reply_text[:500]}")
                return {"type": "text", "text": reply_text}
    raise RuntimeError("LLM 工具调用循环超过上限")


async def call_text_llm(event: dict[str, Any], prompt: str, context_texts: list[str], images: list[dict[str, Any]], trigger_sender_id: int, system_prompt: str, tools: list[dict[str, Any]]) -> str:
    result = await call_chat_model(event, prompt, context_texts, images, trigger_sender_id, system_prompt, tools)
    return result.get("text") or ""


async def call_chat_with_tools(event: dict[str, Any], prompt: str, context_texts: list[str], images: list[dict[str, Any]], trigger_sender_id: int, system_prompt: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    return await call_chat_model(event, prompt, context_texts, images, trigger_sender_id, system_prompt, tools)



def build_image_order_note(images: list[dict[str, Any]]) -> str:
    if not images:
        return ""
    lines = ["输入图片按时间顺序编号如下，图1 最早，编号越大越新："]
    for index, record in enumerate(images[:MAX_CONTEXT_IMAGES], start=1):
        image = image_path(record)
        lines.append(f"图{index} = 第 {index} 张输入图片，文件名 {image.name}，发送者 {image_sender_label(record)}")
    lines.append("用户提到图1、图2、第一张、第二张时，必须按这个编号理解；不要自行交换图片顺序。")
    lines.append("如果本次传入了多张参考图，而用户没有明确指定编号，请结合最近聊天上下文、用户当前请求、图片时间顺序和发送者信息，甄别真正应该用于生图的参考图片，通常优先使用与当前请求最相关、时间上最接近、由触发者本人发送或被明确点名的两张图片。")
    lines.append("不要把无关的旧图强行混入画面；如果用户要求替换、合成或把图A内容应用到图B，要明确区分哪张是待编辑底图，哪张是参考主体/风格图。")
    return "\n".join(lines)


def image_api_url_for_request(has_images: bool) -> str:
    reload_runtime_files()
    image_url = active_api_config("image")["url"]
    if has_images:
        return image_url
    if image_url.endswith("/images/edits"):
        return image_url.removesuffix("/images/edits") + "/images/generations"
    return image_url


async def call_image_api(prompt: str, context_texts: list[str], images: list[dict[str, Any]]) -> Path:
    reload_runtime_files()
    image_config = active_api_config("image")
    image_url = image_config["url"]
    image_key = image_config["key"]
    image_model = active_model("image")
    if not image_url:
        raise RuntimeError("未配置生图接口地址")

    context = "\n".join(context_texts[-MAX_CONTEXT_MESSAGES:])
    image_order_note = build_image_order_note(images)
    prompt_parts = []
    if context:
        prompt_parts.append(f"最近聊天上下文，仅用于理解用户意图、图片指代、发送者和时间顺序，不要当作必须出现在图片里的内容：\n{context}")
    if image_order_note:
        prompt_parts.append(image_order_note)
    prompt_parts.append(f"当前生图请求：\n{prompt}")
    full_prompt = "\n\n".join(prompt_parts)
    headers = {"Authorization": f"Bearer {image_key}"} if image_key else {}

    image_paths = [image_path(record) for record in images[:MAX_CONTEXT_IMAGES]]
    request_url = image_api_url_for_request(bool(image_paths))
    if image_paths:
        form = aiohttp.FormData()
        form.add_field("model", image_model)
        form.add_field("prompt", full_prompt)
        for image in image_paths:
            form.add_field("image", image.open("rb"), filename=image.name, content_type="image/png" if image.suffix.lower() == ".png" else "image/jpeg")
        payload: Any = form
    else:
        payload = {"model": image_model, "prompt": full_prompt}

    log_json("Image request", {"url": request_url, "prompt": full_prompt, "images": [str(p) for p in image_paths], "headers": headers})
    async with aiohttp.ClientSession(headers=headers) as session:
        if image_paths:
            request = session.post(request_url, data=payload, timeout=60 * 30)
        else:
            request = session.post(request_url, json=payload, timeout=60 * 30)
        async with request as resp:
            body = await resp.read()
            body_text = body[:1000].decode("utf-8", errors="replace")
            log(f"Image response status={resp.status} content_type={resp.headers.get('content-type', '')} body_preview={body[:300]!r}")
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {sanitize_error_detail(body_text)}")
            content_type = resp.headers.get("content-type", "")
            if content_type.startswith("image/"):
                suffix = ".png" if "png" in content_type else ".jpg"
                target = OUTPUT_DIR / f"{uuid.uuid4().hex}{suffix}"
                target.write_bytes(body)
                log(f"Image saved: {target}")
                return target

            data = json.loads(body.decode("utf-8"))
            first = data.get("data", [{}])[0]
            image_b64 = first.get("b64_json") or data.get("image_base64")
            if image_b64:
                target = OUTPUT_DIR / f"{uuid.uuid4().hex}.png"
                target.write_bytes(base64.b64decode(image_b64))
                log(f"Image decoded from base64: {target}")
                return target
            image_url = first.get("url") or data.get("image_url")
            if image_url:
                log(f"Image URL received: {image_url}")
                path = await download_image(session, image_url)
                if path:
                    return path
            raise RuntimeError(f"生图接口没有返回可用图片字段，响应：{sanitize_error_detail(data)}")


def select_llm_images(key: str, sender_id: int, current_images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if current_images:
        return current_images[:MAX_CONTEXT_IMAGES]
    sender_images = visible_images_for_sender(key, sender_id)
    if sender_images:
        return sender_images[:MAX_CONTEXT_IMAGES]
    _, recent_images = recent_context(key)
    return recent_images[:MAX_CONTEXT_IMAGES]


def select_tool_images(images: list[dict[str, Any]], image_indexes: list[Any]) -> list[dict[str, Any]]:
    if not image_indexes:
        return []
    selected: list[dict[str, Any]] = []
    for value in image_indexes:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(images):
            record = images[index - 1]
            if record not in selected:
                selected.append(record)
    return selected


async def image_job(event: dict[str, Any], job_id: str, prompt: str, context_texts: list[str], images: list[dict[str, Any]]) -> None:
    start = time.monotonic()
    log(f"Image job started: {job_id} prompt={prompt!r} images={[image_path(record).name for record in images]}")
    try:
        output = await call_image_api(prompt, context_texts, images)
        elapsed = format_elapsed(time.monotonic() - start)
        log(f"Image job finished: {job_id} elapsed={elapsed} output={output}")
        await reply(event, [
            {"type": "text", "data": {"text": f"任务 {job_id} 完成，用时 {elapsed}。\n"}},
            {"type": "image", "data": {"file": output.as_uri()}},
        ])
    except asyncio.CancelledError:
        elapsed = format_elapsed(time.monotonic() - start)
        log(f"Image job cancelled: {job_id} elapsed={elapsed}")
        await reply(event, f"任务 {job_id} 已取消，已用时 {elapsed}。")
        raise
    except Exception as exc:
        elapsed = format_elapsed(time.monotonic() - start)
        detail = exception_detail(exc)
        log(f"Image job failed: {job_id} elapsed={elapsed} error={detail}")
        await reply(event, f"任务 {job_id} 失败，用时 {elapsed}：{detail}")
    finally:
        jobs.pop(job_id, None)


def command_help_text() -> str:
    lines = ["可用指令："]
    for usage, description in sorted(COMMAND_HELP.items()):
        lines.append(f"{usage} - {description}")
    lines.append("/plugins - 查看和管理群插件。")
    lines.append("\n群聊中所有指令和对话都必须先 @ 我，再接命令或触发词。")
    lines.append("支持 @QQ号、@当前群名片或 @Pig god 等机器人识别到的艾特形式。")
    return "\n".join(lines)


def clear_current_context(event: dict[str, Any]) -> int:
    key = scope_key(event)
    count = len(contexts.get(key, []))
    contexts.pop(key, None)
    return count


def reboot_process() -> None:
    log("Reboot requested, replacing current process")
    os.environ["LOCAL_ONEBOT_LOG_FILE"] = str(LOG_FILE)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])


def command_context() -> dict[str, Any]:
    reload_runtime_files()
    return {
        "reply": reply,
        "reply_forward": reply_forward,
        "is_controller": is_controller,
        "is_admin_event": lambda event: is_admin_user(int(event.get("user_id", 0))),
        "jobs": jobs,
        "bot_state": bot_state,
        "command_help_text": command_help_text,
        "plugin_help_text": plugin_help_text,
        "plugin_enabled_for_event": plugin_enabled_for_event,
        "plugins": PLUGINS,
        "log": log,
        "api_configs": API_CONFIGS,
        "runtime_state": runtime_state,
        "set_active_runtime": set_active_runtime,
        "active_api_config": active_api_config,
        "active_model": active_model,
        "prompt_configs": PROMPT_CONFIGS,
        "get_prompt_configs": lambda: PROMPT_CONFIGS,
        "active_prompt_id": active_prompt_id,
        "set_active_prompt": set_active_prompt,
        "set_photo_enabled": set_photo_enabled,
        "photo_enabled": photo_enabled,
        "admin_users": ADMIN_USERS,
        "clear_contexts": contexts.clear,
        "clear_current_context": clear_current_context,
        "reboot_process": reboot_process,
        "reload_runtime_files": reload_runtime_files,
        "tool_infos": [item.copy() for item in TOOL_INFOS],
        "tool_definitions": [tool.copy() for tool in TOOL_DEFINITIONS],
        "output_dir": OUTPUT_DIR,
        "max_context_images": MAX_CONTEXT_IMAGES,
        "max_context_messages": MAX_CONTEXT_MESSAGES,
        "image_path": image_path,
        "image_sender_label": image_sender_label,
        "download_image": download_image,
        "sanitize_error_detail": sanitize_error_detail,
        "exception_detail": exception_detail,
        "log_json": log_json,
        "console_log": console_log,
        "original_stdout": ORIGINAL_STDOUT,
        "original_stderr": ORIGINAL_STDERR,
        "create_task": asyncio.create_task,
        "image_job": image_job,
        "format_elapsed": format_elapsed,
        "reply_to_message": reply_to_message,
        "reply_segments": reply_segments,
        "scope_key": scope_key,
        "visible_images_for_sender": visible_images_for_sender,
        "recent_context": recent_context,
        "select_llm_images": select_llm_images,
    }




def load_command_module(path: Path) -> dict[str, Any] | None:
    module_name = f"local_onebot_command_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        log(f"Command skipped: {path.name} cannot create module spec")
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = getattr(module, "COMMAND", None)
    if not isinstance(command, dict):
        log(f"Command skipped: {path.name} missing COMMAND dict")
        return None
    name = str(command.get("name") or "").strip().lower()
    handler = command.get("handler")
    if not name.startswith("/") or not callable(handler):
        log(f"Command skipped: {path.name} invalid name or handler")
        return None
    return command


def load_command_nicknames() -> dict[str, list[str]]:
    if not COMMAND_NICKNAME_FILE.exists():
        return {}
    try:
        with COMMAND_NICKNAME_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Command nickname load failed: {exception_detail(exc)}")
        return {}
    if not isinstance(data, dict):
        log("Command nickname load failed: root value is not object")
        return {}
    result: dict[str, list[str]] = {}
    for key, value in data.items():
        command = str(key).strip().lower()
        if not command.startswith("/"):
            continue
        aliases: list[str] = []
        raw_aliases = value if isinstance(value, list) else [value]
        for item in raw_aliases:
            alias = str(item).strip().lower()
            if alias and alias not in aliases:
                aliases.append(alias)
        if aliases:
            result[command] = aliases
        else:
            result.setdefault(command, [])
    return result


def save_command_nicknames(data: dict[str, list[str]]) -> None:
    with COMMAND_NICKNAME_FILE.open("w", encoding="utf-8") as f:
        json.dump(dict(sorted(data.items())), f, ensure_ascii=False, indent=2)


def load_commands() -> tuple[dict[str, str], dict[str, Any], dict[str, list[str]]]:
    help_items: dict[str, str] = {}
    handlers: dict[str, Any] = {}
    command_aliases = load_command_nicknames()
    changed_aliases = False
    for path in sorted(COMMAND_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            command = load_command_module(path)
        except Exception as exc:
            log(f"Command load failed: {path.name} error={exc}")
            continue
        if not command:
            continue
        name = str(command["name"]).strip().lower()
        usage = str(command.get("usage") or name).strip()
        description = str(command.get("description") or "无说明").strip()
        if name not in command_aliases:
            command_aliases[name] = []
            changed_aliases = True
        handlers[name] = command["handler"]
        aliases = [alias for alias in command_aliases.get(name, []) if not alias.startswith("/") or alias not in handlers]
        for alias in aliases:
            if alias.startswith("/"):
                handlers[alias] = command["handler"]
        if aliases:
            help_items[f"{usage}（别名：{', '.join(aliases)}）"] = description
        else:
            help_items[usage] = description
        log(f"Command loaded: {name} from {path.name} aliases={aliases}")
    if changed_aliases or not COMMAND_NICKNAME_FILE.exists():
        save_command_nicknames(command_aliases)
    return help_items, handlers, command_aliases


COMMAND_HELP, COMMAND_HANDLERS, COMMAND_ALIASES = load_commands()


def tool_definition_context() -> dict[str, Any]:
    return {
        "prompt_value": prompt_value,
    }


def load_tool_module(path: Path) -> dict[str, Any] | None:
    module_name = f"local_onebot_tool_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        log(f"Tool skipped: {path.name} cannot create module spec")
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definition = getattr(module, "definition", None)
    execute = getattr(module, "execute", None)
    info = getattr(module, "info", None)
    if not callable(definition) or not callable(execute):
        log(f"Tool skipped: {path.name} missing definition or execute")
        return None
    tool_def = definition(tool_definition_context())
    if not isinstance(tool_def, dict):
        log(f"Tool skipped: {path.name} invalid definition")
        return None
    function = tool_def.get("function") if isinstance(tool_def.get("function"), dict) else {}
    name = str(function.get("name") or "").strip().lower()
    if not name:
        log(f"Tool skipped: {path.name} missing tool name")
        return None
    tool_info = info(tool_definition_context()) if callable(info) else {}
    if not isinstance(tool_info, dict):
        tool_info = {}
    tool_info = {
        "name": name,
        "description": str(tool_info.get("description") or function.get("description") or "").strip(),
    }
    return {"name": name, "definition": tool_def, "execute": execute, "info": tool_info}


def load_tools() -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    definitions: list[dict[str, Any]] = []
    executors: dict[str, Any] = {}
    infos: list[dict[str, str]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            tool = load_tool_module(path)
        except Exception as exc:
            log(f"Tool load failed: {path.name} error={exc}")
            continue
        if not tool:
            continue
        definitions.append(tool["definition"])
        executors[tool["name"]] = tool["execute"]
        infos.append(tool["info"])
        log(f"Tool loaded: {tool['name']} from {path.name}")
    return definitions, executors, infos


TOOL_DEFINITIONS, TOOL_EXECUTORS, TOOL_INFOS = load_tools()


def plugin_config_path(name: str) -> Path:
    return PLUGIN_DIR / f"{name}.json"


def load_plugin_subscriptions(name: str) -> dict[str, set[int]]:
    path = plugin_config_path(name)
    result: dict[str, set[int]] = {"groups": set(), "private_users": set()}
    if not path.exists():
        return result
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Plugin config load failed: {path.name} error={exception_detail(exc)}")
        return result
    if not isinstance(data, dict):
        return result
    for source_key, target_key in (("groups", "groups"), ("private_users", "private_users"), ("users", "private_users")):
        values = data.get(source_key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            try:
                result[target_key].add(int(value))
            except (TypeError, ValueError):
                continue
    return result


def save_plugin_subscriptions(name: str, subscriptions: dict[str, set[int]]) -> None:
    path = plugin_config_path(name)
    tmp = path.with_suffix(".json.tmp")
    data = {
        "groups": sorted(subscriptions.get("groups", set())),
        "private_users": sorted(subscriptions.get("private_users", set())),
    }
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def chat_subscription_key(event: dict[str, Any]) -> tuple[str, int]:
    if event.get("message_type") == "group":
        return "groups", int(event.get("group_id", 0))
    return "private_users", int(event.get("user_id", 0))


def plugin_enabled_for_event(plugin: dict[str, Any], event: dict[str, Any]) -> bool:
    scope, value = chat_subscription_key(event)
    return value in plugin.get("subscriptions", {}).get(scope, set())


def plugin_context(plugin_name: str) -> dict[str, Any]:
    return {
        "name": plugin_name,
        "reply": reply,
        "onebot_post": onebot_post,
        "log": log,
        "bot_qq": BOT_QQ,
        "bot_name": BOT_NAME,
        "plain_text": plain_text,
        "message_text": message_text,
        "scope_key": scope_key,
        "create_task": asyncio.create_task,
    }


def load_plugin_module(path: Path) -> dict[str, Any] | None:
    module_name = f"local_onebot_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        log(f"Plugin skipped: {path.name} cannot create module spec")
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, dict):
        log(f"Plugin skipped: {path.name} missing PLUGIN dict")
        return None
    name = str(plugin.get("name") or path.stem).strip().lower()
    handler = plugin.get("handler")
    if not name or not re.fullmatch(r"[a-z0-9_][a-z0-9_-]*", name) or not callable(handler):
        log(f"Plugin skipped: {path.name} invalid name or handler")
        return None
    plugin["name"] = name
    plugin.setdefault("description", "无说明")
    plugin["subscriptions"] = load_plugin_subscriptions(name)
    return plugin


def load_plugins() -> dict[str, dict[str, Any]]:
    plugins: dict[str, dict[str, Any]] = {}
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            plugin = load_plugin_module(path)
        except Exception as exc:
            log(f"Plugin load failed: {path.name} error={exception_detail(exc)}")
            continue
        if not plugin:
            continue
        plugins[plugin["name"]] = plugin
        subscriptions = plugin["subscriptions"]
        log(f"Plugin loaded: {plugin['name']} from {path.name} groups={sorted(subscriptions['groups'])} private_users={sorted(subscriptions['private_users'])}")
    return plugins


PLUGINS = load_plugins()


def plugin_help_text(event: dict[str, Any] | None = None, include_description: bool = True) -> str:
    lines = ["插件指令：", "/plugins - 查看插件列表", "/plugins enable 插件名 - 在当前聊天开启插件", "/plugins disable 插件名 - 在当前聊天关闭插件"]
    if PLUGINS:
        lines.append("\n可用插件：")
        for name, plugin in sorted(PLUGINS.items()):
            state = ""
            if event is not None:
                state = "已启用" if plugin_enabled_for_event(plugin, event) else "已关闭"
                state = f" [{state}]"
            description = str(plugin.get("description") or "无说明")
            suffix = f" - {description}" if include_description else ""
            lines.append(f"{name}{state}{suffix}")
    else:
        lines.append("\n当前没有已加载插件。")
    return "\n".join(lines)


async def handle_plugin_command(event: dict[str, Any], arg: str) -> None:
    parts = arg.split()
    if not parts:
        await reply(event, plugin_help_text(event))
        return
    action = parts[0].lower()
    plugin_name = parts[1].lower() if len(parts) > 1 else ""
    if action not in {"enable", "disable"} or not plugin_name:
        await reply(event, "用法：/plugins enable 插件名 或 /plugins disable 插件名")
        return
    if event.get("message_type") == "group" and not is_controller(event):
        await reply(event, "你没有权限管理本群插件。")
        return
    plugin = PLUGINS.get(plugin_name)
    if not plugin:
        await reply(event, f"未找到插件 {plugin_name}，发送 /plugins 查看可用插件。")
        return
    scope, chat_id = chat_subscription_key(event)
    subscriptions = plugin.get("subscriptions", {"groups": set(), "private_users": set()})
    subscriptions.setdefault("groups", set())
    subscriptions.setdefault("private_users", set())
    if action == "enable":
        subscriptions[scope].add(chat_id)
        message = f"已在当前聊天开启插件 {plugin_name}。"
    else:
        subscriptions[scope].discard(chat_id)
        message = f"已在当前聊天关闭插件 {plugin_name}。"
    plugin["subscriptions"] = subscriptions
    save_plugin_subscriptions(plugin_name, subscriptions)
    await reply(event, message)


async def dispatch_plugins(event: dict[str, Any], text: str) -> bool:
    handled = False
    for name, plugin in PLUGINS.items():
        if not plugin_enabled_for_event(plugin, event):
            continue
        try:
            result = plugin["handler"](event, text, plugin_context(name))
            if asyncio.iscoroutine(result):
                result = await result
            handled = bool(result) or handled
        except Exception as exc:
            log(f"Plugin {name} handle failed: {exception_detail(exc)}")
    return handled


async def handle_command(event: dict[str, Any], text: str) -> bool:
    reload_runtime_files()
    if not text.startswith("/"):
        return False
    if bot_state.get("stopped") and not is_stopped_allowed_command_text(text):
        log(f"Command ignored while stopped: {text[:100]!r}")
        return True
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    log(f"Command received: {command} arg={arg!r} from user={event.get('user_id')}")

    if command == "/plugins":
        await handle_plugin_command(event, arg)
        return True

    handler = COMMAND_HANDLERS.get(command)
    if not handler:
        await reply(event, "未知指令，发送 /help 查看可用指令。")
        return True
    await handler(event, arg, command_context())
    return True


def plain_alias_command_text(text: str) -> str:
    normalized = text.strip().lower()
    if not normalized:
        return ""
    for command, aliases in COMMAND_ALIASES.items():
        for alias in aliases:
            if not alias.startswith("/") and normalized == alias:
                return command
    return ""


def is_stopped_allowed_command_text(text: str) -> bool:
    if not text.strip().startswith("/"):
        return False
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    return command in {"/restart", "/reboot"} or (command == "/stop" and arg == "/reboot")


async def handle_event(event: dict[str, Any]) -> None:
    try:
        reload_runtime_files()
        if event.get("post_type") != "message":
            return

        message = event.get("message", [])
        replied_message = await get_replied_message(message)
        if replied_message:
            event["reply"] = replied_message
        replied_segments = message_segments(replied_message) if replied_message else []
        await hydrate_at_names(event, message, replied_segments)
        replied_images = await cache_replied_message_context(event, replied_message) if replied_message else []
        text, current_images = await parse_and_cache(event)
        if bot_state.get("stopped") and not is_stopped_allowed_command_text(text):
            log("Bot is stopped; ignoring message")
            return
        event["current_images"] = list(current_images)
        event["replied_images"] = list(replied_images)
        current_images.extend(replied_images)
        key = scope_key(event)
        log(f"After parse_and_cache: key={key} text_len={len(text)} current_images={len(current_images)} message_type={event.get('message_type')}")

        if str(event.get("user_id")) == BOT_QQ:
            log("Ignored bot self message after caching context")
            return

        if event.get("message_type") == "group":
            at_bot = is_at_bot(message)
            reply_to_bot = await is_reply_to_bot(message, replied_message)
            if (at_bot or reply_to_bot) and not text.strip() and (current_images or replied_images):
                log("Dispatching group animetrace shortcut for image-only mention/reply")
                await handle_command(event, "/animetrace")
                return

        if not text:
            log("Ignored image/media-only message after caching context")
            return

        if bot_state.get("stopped"):
            if is_stopped_allowed_command_text(text):
                log("Stopped mode allowing recovery command")
            else:
                log("Bot is stopped; ignoring message")
                return

        if await dispatch_plugins(event, text):
            return

        if event.get("message_type") == "group":
            at_bot = is_at_bot(message)
            reply_to_bot = await is_reply_to_bot(message, replied_message)
            log(f"Group trigger check: at_bot={at_bot} reply_to_bot={reply_to_bot} raw_text={text[:200]!r}")
            normalized_text = normalize_group_command_text(message, text)
            log(f"Group normalized text: {normalized_text[:300]!r}")
            if bot_state.get("stopped") and not is_stopped_allowed_command_text(normalized_text):
                log("Ignored group message while bot is stopped")
                return
            if (at_bot or reply_to_bot) and normalized_text.startswith("/plugins"):
                log(f"Dispatching group plugin command: {normalized_text[:100]!r}")
                await handle_command(event, normalized_text)
                return
            if (at_bot or reply_to_bot) and normalized_text.startswith("/help"):
                log(f"Dispatching group help command: {normalized_text[:100]!r}")
                await handle_command(event, normalized_text)
                return
            admin_slash_command = is_admin_user(int(event.get("user_id", 0))) and normalized_text.startswith("/")
            if admin_slash_command:
                log(f"Dispatching group admin command without mention: {normalized_text[:100]!r}")
                await handle_command(event, normalized_text)
                return
            if not at_bot and not reply_to_bot:
                log("Ignored group message without @ or bot reply")
                return
            if normalized_text.startswith("/"):
                log(f"Dispatching group command: {normalized_text[:100]!r}")
                await handle_command(event, normalized_text)
                return
            alias_command = plain_alias_command_text(normalized_text)
            if alias_command:
                if bot_state.get("stopped") and not is_stopped_allowed_command_text(alias_command):
                    log("Ignored group plain alias command while bot is stopped")
                    return
                log(f"Dispatching group plain alias command: {alias_command} from {normalized_text[:100]!r}")
                await handle_command(event, alias_command)
                return
            text = normalized_text
        elif text.startswith("/"):
            if bot_state.get("stopped") and not is_stopped_allowed_command_text(text):
                log("Ignored private command while bot is stopped")
                return
            log(f"Dispatching private command: {text[:100]!r}")
            await handle_command(event, text)
            return
        else:
            alias_command = plain_alias_command_text(text)
            if alias_command:
                if bot_state.get("stopped") and not is_stopped_allowed_command_text(alias_command):
                    log("Ignored private plain alias command while bot is stopped")
                    return
                log(f"Dispatching private plain alias command: {alias_command} from {text[:100]!r}")
                await handle_command(event, alias_command)
                return

        if bot_state.get("stopped"):
            log("Ignored conversation while bot is stopped")
            return

        log("Preparing context before LLM request")
        context_texts, recent_images = recent_context(key)
        allow_photos = photo_enabled()
        prompt = text.strip()
        log(f"Prompt resolved before LLM: prompt_len={len(prompt)} prompt_preview={prompt[:300]!r}")
        if not prompt:
            log("No prompt after normalization")
            return
        images = select_llm_images(key, int(event.get("user_id", 0)), current_images) if allow_photos else []
        system_prompt = select_system_prompt(int(event.get("user_id", 0)))
        tools = select_tools(int(event.get("user_id", 0)))
        log(f"Context resolved: texts={len(context_texts)} recent_images={len(recent_images)} current_images={len(current_images)} selected_images={len(images)} selected_image_files={[image_path(record).name for record in images]} admin={is_admin_user(int(event.get('user_id', 0)))}")
        log("Calling LLM now")

        result = await call_chat_with_tools(event, prompt, context_texts, images, int(event.get("user_id", 0)), system_prompt, tools)
        response = result.get("text") or ""
        log(f"Sending text reply: {response[:500]!r}")
        if response:
            await reply(event, response)
    except Exception as exc:
        detail = exception_detail(exc)
        log(f"handle_event error: {detail}")
        try:
            await reply(event, f"处理失败：{detail}")
        except Exception as reply_exc:
            log(f"handle_event failed to send error reply: {exception_detail(reply_exc)}")
        raise


async def connect_onebot_ws(headers: dict[str, str]):
    reload_runtime_files()
    try:
        return await websockets.connect(ONEBOT_WS, additional_headers=headers)
    except TypeError as exc:
        if "additional_headers" not in str(exc):
            raise
        return await websockets.connect(ONEBOT_WS, extra_headers=headers)


async def main() -> None:
    log(f"Connecting to {ONEBOT_WS}")
    while True:
        try:
            headers = auth_headers()
            async with await connect_onebot_ws(headers) as ws:
                log("Connected. Waiting for QQ events.")
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                        if event.get("post_type") == "meta_event" and event.get("meta_event_type") == "heartbeat":
                            continue
                        log(f"WS raw event: {raw[:1000]}")
                        task = asyncio.create_task(handle_event(event))
                        task.add_done_callback(lambda t: log(f"Event task done: cancelled={t.cancelled()} exception={t.exception() if not t.cancelled() else None}"))
                    except Exception as exc:
                        log(f"event error: {exc}")
        except Exception as exc:
            log(f"ws disconnected: {exc}; reconnecting in 5s")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())

