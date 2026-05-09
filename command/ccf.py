from __future__ import annotations

import asyncio
import json
import os
import random
import re
import uuid
from pathlib import Path
from typing import Any

import aiohttp

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "新建 文本文档.txt"
ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "outputs"
HOST_DIR = ROOT_DIR / "tools" / "browser_automation_host"
HOST_PROJECT = HOST_DIR / "browser_automation_host.csproj"
HOST_DLL = HOST_DIR / "bin" / "Release" / "net9.0-windows" / "browser_automation_host.dll"
DYNAMIC_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
FOLLOWING_API = "https://api.bilibili.com/x/relation/followings"
REPLY_API = "https://api.aicu.cc/api/v3/search/getreply"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

_checker_cache: tuple[float, list[dict[str, Any]]] | None = None
_webview2_cookie_cache: tuple[float, str] | None = None


def ccf_log(ctx: dict[str, Any] | None, message: str) -> None:
    if ctx and callable(ctx.get("log")):
        ctx["log"](message)


async def ensure_host_built(ctx: dict[str, Any] | None = None) -> None:
    if HOST_DLL.exists():
        return
    if not HOST_PROJECT.exists():
        raise RuntimeError("WebView2 宿主项目不存在")
    ccf_log(ctx, "CCF WebView2 host build start")
    proc = await asyncio.create_subprocess_exec(
        "dotnet",
        "build",
        str(HOST_PROJECT),
        "-c",
        "Release",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stdout_text:
        ccf_log(ctx, f"CCF WebView2 host build stdout:\n{stdout_text[:6000]}")
    if stderr_text:
        ccf_log(ctx, f"CCF WebView2 host build stderr:\n{stderr_text[:6000]}")
    if proc.returncode != 0 or not HOST_DLL.exists():
        raise RuntimeError(f"WebView2 宿主编译失败：{(stderr_text or stdout_text or proc.returncode)!s}")


async def read_cookie_from_webview2(ctx: dict[str, Any] | None = None) -> str:
    global _webview2_cookie_cache
    if os.getenv("CCF_WEBVIEW2_COOKIE", "1") == "0":
        return ""
    now = asyncio.get_running_loop().time()
    ttl = int(os.getenv("CCF_WEBVIEW2_COOKIE_TTL", "300"))
    if _webview2_cookie_cache and now - _webview2_cookie_cache[0] < ttl:
        return _webview2_cookie_cache[1]
    await ensure_host_built(ctx)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUTPUT_DIR / f"ccf_cookie_{uuid.uuid4().hex}.json"
    command = [
        "dotnet",
        str(HOST_DLL),
        "--task",
        "bilibili-cookie",
        "--wait-ms",
        os.getenv("CCF_WEBVIEW2_WAIT_MS", "1000"),
        "--output-json",
        str(result_path),
        "--cookie-url",
        os.getenv("CCF_COOKIE_URL", "https://www.bilibili.com/"),
        "--cookie-source",
        os.getenv("CCF_COOKIE_SOURCE", "webview2"),
        "--profile-directory",
        os.getenv("CCF_PROFILE_DIRECTORY", "Default"),
    ]
    user_data_folder = os.getenv("CCF_WEBVIEW2_USER_DATA_FOLDER", "").strip()
    browser_user_data_folder = os.getenv("CCF_BROWSER_USER_DATA_FOLDER", "").strip()
    if user_data_folder:
        command.extend(["--user-data-folder", user_data_folder])
    if browser_user_data_folder:
        command.extend(["--browser-user-data-folder", browser_user_data_folder])
    env = os.environ.copy()
    env["DOTNET_CLI_UI_LANGUAGE"] = "zh-CN"
    ccf_log(ctx, f"CCF WebView2 cookie host start: {' '.join(command)}")
    proc = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return ""
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stdout_text:
        ccf_log(ctx, f"CCF WebView2 cookie host stdout:\n{stdout_text[:1000]}")
    if stderr_text:
        ccf_log(ctx, f"CCF WebView2 cookie host stderr:\n{stderr_text[:1000]}")
    if proc.returncode != 0 or not result_path.exists():
        result_path.unlink(missing_ok=True)
        return ""
    try:
        with result_path.open("r", encoding="utf-8") as f:
            result = json.load(f)
        if not isinstance(result, dict) or result.get("error"):
            return ""
        cookie = str(result.get("cookie") or "").strip()
        if cookie:
            _webview2_cookie_cache = (now, cookie)
        return cookie
    finally:
        result_path.unlink(missing_ok=True)


def random_buvid3() -> str:
    chars = "0123456789ABCDEF"
    prefix = "".join(random.choice(chars) for _ in range(32))
    suffix = str(random.randint(1, 99999)).zfill(5)
    return f"{prefix}{suffix}infoc"


def bilibili_headers(referer: str = "https://www.bilibili.com", cookie: str | None = None) -> dict[str, str]:
    cookie_value = (cookie or os.getenv("BILIBILI_COOKIE", "")).strip()
    if not cookie_value:
        cookie_value = f"buvid3={random_buvid3()}; b_nut={random.randint(1700000000, 1900000000)}"
    return {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "Cookie": cookie_value,
        "Accept": "application/json, text/plain, */*",
    }


def strip_js_comments(text: str) -> str:
    result: list[str] = []
    i = 0
    quote = ""
    escaped = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            result.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            result.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def extract_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str:
    depth = 0
    quote = ""
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    raise ValueError("未找到完整的 JS 数组或对象")


def split_top_level_items(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "," and depth == 0:
            item = text[start:i].strip()
            if item:
                items.append(item)
            start = i + 1
    item = text[start:].strip()
    if item:
        items.append(item)
    return items


def js_string_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"', "`"} and value[-1] == value[0]:
        return value[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\`", "`").replace("\\n", "\n")
    return value


def extract_property(body: str, name: str) -> str | None:
    match = re.search(rf"(?:^|[,\s]){re.escape(name)}\s*:", body)
    if not match:
        return None
    colon = body.find(":", match.start())
    pos = colon + 1
    while pos < len(body) and body[pos].isspace():
        pos += 1
    if pos >= len(body):
        return None
    if body[pos] == "[":
        return extract_balanced(body, pos, "[", "]")
    if body[pos] == "{":
        return extract_balanced(body, pos, "{", "}")
    quote = body[pos] if body[pos] in {"'", '"', "`"} else ""
    escaped = False
    start = pos + 1 if quote else pos
    for i in range(start, len(body)):
        ch = body[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                return body[pos:i + 1]
            continue
        if ch == ",":
            return body[pos:i].strip()
    return body[pos:].strip()


def parse_string_array(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    for item in split_top_level_items(value):
        item = item.strip()
        if item and item[0] in {"'", '"', "`"}:
            result.append(js_string_value(item))
    return result


def parse_number_array(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(item) for item in re.findall(r"\d+", value)]


def load_checkers() -> list[dict[str, Any]]:
    global _checker_cache
    stat = SCRIPT_PATH.stat()
    if _checker_cache and _checker_cache[0] == stat.st_mtime:
        return _checker_cache[1]
    source = strip_js_comments(SCRIPT_PATH.read_text(encoding="utf-8", errors="ignore"))
    marker = "const checkers"
    marker_pos = source.find(marker)
    if marker_pos < 0:
        raise ValueError("油猴脚本中未找到 checkers 配置")
    array_start = source.find("[", marker_pos)
    checkers_body = extract_balanced(source, array_start, "[", "]")
    checkers: list[dict[str, Any]] = []
    for item in split_top_level_items(checkers_body):
        item = item.strip()
        if not item.startswith("{"):
            continue
        body = extract_balanced(item, 0, "{", "}")
        display_name = js_string_value(extract_property(body, "displayName") or "")
        if not display_name:
            continue
        checkers.append({
            "displayName": display_name,
            "keywords": parse_string_array(extract_property(body, "keywords")),
            "keywordsReverse": parse_string_array(extract_property(body, "keywordsReverse")),
            "followings": parse_number_array(extract_property(body, "followings")),
            "blacklist": parse_number_array(extract_property(body, "blacklist")),
        })
    _checker_cache = (stat.st_mtime, checkers)
    return checkers


async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any] | None:
    async with session.get(url, params=params, headers=headers, timeout=20) as resp:
        if resp.status >= 400:
            return None
        try:
            return await resp.json(content_type=None)
        except Exception:
            return None


async def fetch_followings(session: aiohttp.ClientSession, uid: int, cookie: str = "") -> tuple[list[int], list[str]]:
    errors: list[str] = []
    result: list[int] = []
    for page in range(1, 3):
        data = await fetch_json(session, FOLLOWING_API, {"vmid": uid, "pn": page}, bilibili_headers(f"https://space.bilibili.com/{uid}/", cookie))
        if not isinstance(data, dict):
            errors.append(f"关注列表第 {page} 页获取失败")
            break
        code = data.get("code")
        if code == 22115:
            break
        if code != 0:
            errors.append(f"关注列表第 {page} 页错误码 {code}")
            break
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        rows = payload.get("list") if isinstance(payload.get("list"), list) else []
        result.extend(int(row["mid"]) for row in rows if isinstance(row, dict) and str(row.get("mid", "")).isdigit())
        total = int(payload.get("total") or 0)
        if not rows or total <= len(result):
            break
    return result, errors


async def fetch_dynamics(session: aiohttp.ClientSession, uid: int, cookie: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    result: list[dict[str, Any]] = []
    offset = ""
    for page in range(1, 3):
        params = {"host_mid": uid}
        if offset:
            params["offset"] = offset
        data = await fetch_json(session, DYNAMIC_API, params, bilibili_headers(f"https://space.bilibili.com/{uid}/dynamic", cookie))
        if not isinstance(data, dict):
            errors.append(f"空间动态第 {page} 页获取失败")
            break
        if data.get("code") != 0:
            errors.append(f"空间动态第 {page} 页错误码 {data.get('code')}")
            break
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        result.extend(item for item in items if isinstance(item, dict))
        offset = str(payload.get("offset") or "")
        if not payload.get("has_more") or not offset:
            break
    return result, errors


async def fetch_replies(session: aiohttp.ClientSession, uid: int) -> tuple[list[dict[str, Any]], list[str]]:
    data = await fetch_json(session, REPLY_API, {"uid": uid, "pn": 1, "ps": 50, "mode": 0}, {"User-Agent": USER_AGENT, "Referer": "https://www.aicu.cc", "Origin": "https://www.aicu.cc"})
    if not isinstance(data, dict):
        return [], ["历史评论获取失败"]
    if data.get("code") != 0:
        return [], [f"历史评论错误码 {data.get('code')}"]
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    replies = payload.get("replies") if isinstance(payload.get("replies"), list) else []
    return [item for item in replies if isinstance(item, dict)], []


def first_matching_keyword(text: str, keywords: list[str]) -> str | None:
    return next((keyword for keyword in keywords if keyword and keyword in text), None)


def has_reverse_keyword(text: str, keywords: list[str]) -> bool:
    return any(keyword and keyword in text for keyword in keywords)


def push_found(found: list[dict[str, Any]], checker: dict[str, Any], reason: str, sure: bool, matched: str, content: str = "") -> None:
    found.append({"name": checker["displayName"], "reason": reason, "sure": sure, "matched": matched, "content": content})


def detect_from_static(uid: int, checkers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for checker in checkers:
        if uid in checker.get("blacklist", []):
            push_found(found, checker, "黑名单", True, f"uid{uid}")
    return found


def detect_from_followings(followings: list[int], checkers: list[dict[str, Any]], found: list[dict[str, Any]]) -> None:
    following_set = set(followings)
    for checker in checkers:
        for mid in checker.get("followings", []):
            if mid in following_set:
                push_found(found, checker, "关注列表", True, f"uid{mid}")


def dynamic_texts(item: dict[str, Any]) -> list[tuple[str, str, bool]]:
    module_dynamic = (((item.get("modules") or {}).get("module_dynamic") or {}) if isinstance(item.get("modules"), dict) else {})
    major = module_dynamic.get("major") if isinstance(module_dynamic.get("major"), dict) else {}
    archive = major.get("archive") if isinstance(major.get("archive"), dict) else {}
    orig = item.get("orig") if isinstance(item.get("orig"), dict) else {}
    orig_modules = orig.get("modules") if isinstance(orig.get("modules"), dict) else {}
    orig_dynamic = orig_modules.get("module_dynamic") if isinstance(orig_modules.get("module_dynamic"), dict) else {}
    orig_author = orig_modules.get("module_author") if isinstance(orig_modules.get("module_author"), dict) else {}
    rows: list[tuple[str, str, bool]] = []
    text = ((module_dynamic.get("desc") or {}).get("text") if isinstance(module_dynamic.get("desc"), dict) else "") or ""
    if text:
        rows.append(("空间动态内容", str(text), True))
    orig_text = ((orig_dynamic.get("desc") or {}).get("text") if isinstance(orig_dynamic.get("desc"), dict) else "") or ""
    if orig_text:
        orig_name = str(orig_author.get("name") or "")
        rows.append(("空间动态转发", f"{orig_name} - {orig_text}" if orig_name else str(orig_text), False))
    for reason, value in (("空间动态视频标题", archive.get("title")), ("空间动态视频简介", archive.get("desc"))):
        if value:
            rows.append((reason, str(value), True))
    return rows


def detect_from_dynamics(dynamics: list[dict[str, Any]], checkers: list[dict[str, Any]], found: list[dict[str, Any]]) -> None:
    dynamic_found: list[dict[str, Any]] = []
    for item in dynamics:
        rows = dynamic_texts(item)
        for checker in checkers:
            keywords = checker.get("keywords", [])
            if not keywords:
                continue
            reverse = checker.get("keywordsReverse", [])
            for reason, text, sure in rows:
                keyword = first_matching_keyword(text, keywords)
                if keyword and not has_reverse_keyword(text, reverse):
                    push_found(dynamic_found, checker, reason, sure, keyword, text)
    count_map: dict[str, int] = {}
    for item in dynamic_found:
        content = item.get("content") or ""
        count_map[content] = count_map.get(content, 0) + 1
    for item in dynamic_found:
        content = item.get("content") or ""
        if (count_map.get(content, 0) >= 5 and "、" in content) or count_map.get(content, 0) > 8:
            found.append({"name": "伪成分", "reason": "疑似批量话题/关键词刷屏", "sure": False, "matched": f"{item['name']} - {item['matched']}", "content": content})
        else:
            found.append(item)


def detect_from_replies(replies: list[dict[str, Any]], checkers: list[dict[str, Any]], found: list[dict[str, Any]]) -> None:
    for item in replies:
        text = str(item.get("message") or "")
        if not text:
            continue
        dyn = item.get("dyn") if isinstance(item.get("dyn"), dict) else {}
        parent = item.get("parent") if isinstance(item.get("parent"), dict) else {}
        oid = dyn.get("oid") or "?"
        root = parent.get("rootid") or item.get("rpid") or "?"
        for checker in checkers:
            keywords = checker.get("keywords", [])
            keyword = first_matching_keyword(text, keywords)
            if keyword and not has_reverse_keyword(text, checker.get("keywordsReverse", [])):
                push_found(found, checker, f"视频(av{oid})中的历史评论(id#{root})", False, keyword, text)


def sort_and_dedupe(found: list[dict[str, Any]], checkers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {checker["displayName"]: index for index, checker in enumerate(checkers)}
    found.sort(key=lambda item: order.get(item["name"], 9999))
    non_reply = [item for item in found if "评论" not in item["reason"]]
    reply = [item for item in found if "评论" in item["reason"]]
    counts: dict[str, int] = {}
    for item in non_reply:
        counts[item["name"]] = counts.get(item["name"], 0) + 1
    non_reply.sort(key=lambda item: (-counts.get(item["name"], 0), order.get(item["name"], 9999)))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in non_reply + reply:
        key = f"{item['name']}\n{item['reason']}\n{item['matched']}\n{item.get('content', '')}"
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


async def detect_composition(uid: int, ctx: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str], int]:
    checkers = load_checkers()
    found = detect_from_static(uid, checkers)
    cookie = os.getenv("BILIBILI_COOKIE", "").strip()
    if not cookie:
        cookie = await read_cookie_from_webview2(ctx)
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        following_task = fetch_followings(session, uid, cookie)
        dynamic_task = fetch_dynamics(session, uid, cookie)
        reply_task = fetch_replies(session, uid)
        (followings, following_errors), (dynamics, dynamic_errors), (replies, reply_errors) = await asyncio.gather(following_task, dynamic_task, reply_task)
    detect_from_followings(followings, checkers, found)
    detect_from_dynamics(dynamics, checkers, found)
    detect_from_replies(replies, checkers, found)
    return sort_and_dedupe(found, checkers), following_errors + dynamic_errors + reply_errors, len(checkers)


def format_result(uid: int, found: list[dict[str, Any]], errors: list[str], checker_count: int) -> str:
    lines = [f"B站 UID {uid} 成分检测结果："]
    if found:
        names: list[str] = []
        for item in found:
            if item["name"] not in names:
                names.append(item["name"])
        lines.append("成分：" + "、".join(names))
        lines.append("")
        for index, item in enumerate(found[:12], 1):
            sure = "确定" if item.get("sure") else "可能误判"
            lines.append(f"{index}. {item['name']}（{sure}）")
            lines.append(f"原因：{item['reason']}")
            lines.append(f"匹配：{item['matched']}")
            content = str(item.get("content") or "").replace("\n", " ").strip()
            if content:
                lines.append(f"内容：{content[:80]}{'…' if len(content) > 80 else ''}")
        if len(found) > 12:
            lines.append(f"其余 {len(found) - 12} 条命中已省略。")
    else:
        lines.append("成分：无")
    if errors:
        lines.append("")
        lines.append("部分数据源查询异常：" + "；".join(errors[:3]))
        lines.append("如果 B站接口返回 -101/412，可在 .env 配置 BILIBILI_COOKIE，或先用 WebView2/Edge/Chrome Cookie 来源登录。")
    lines.append(f"规则数：{checker_count}，数据源：关注列表、空间动态、历史评论")
    return "\n".join(lines)


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    if not ctx["is_admin_event"](event):
        await ctx["reply"](event, "你没有权限使用这个指令。")
        return
    text = arg.strip()
    if not re.fullmatch(r"\d{1,20}", text):
        await ctx["reply"](event, "用法：/ccf [B站UID]")
        return
    uid = int(text)
    await ctx["reply"](event, f"正在检测 B站 UID {uid} 的成分，请稍等。")
    try:
        found, errors, checker_count = await detect_composition(uid, ctx)
    except Exception as exc:
        detail = ctx.get("sanitize_error_detail", str)(str(exc)) if callable(ctx.get("sanitize_error_detail")) else str(exc)
        await ctx["reply"](event, f"检测失败：{detail}")
        return
    await ctx["reply"](event, format_result(uid, found, errors, checker_count))


COMMAND = {
    "name": "/ccf",
    "usage": "/ccf [B站UID]",
    "description": "检测指定 B站 UID 的成分。",
    "handler": handler,
}
