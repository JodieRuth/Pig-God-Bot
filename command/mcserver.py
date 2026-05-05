from __future__ import annotations

import asyncio
import json
import re
import socket
import struct
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).with_name("mcserver")
DATA_FILE = DATA_DIR / "data.json"
QUERY_TIMEOUT = 2.5
DNS_TIMEOUT = 1.5
PROTOCOL_VERSIONS = [767, 766, 765, 764, 763, 762, 761, 760, 759, 758, 757, 756, 755, 754, 47]
ENDPOINT_RE = re.compile(r"^[^:\s]+(?::\d{1,5})?$")


def load_data() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return {"groups": {}, "private_users": {}}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"groups": {}, "private_users": {}}
    if not isinstance(data, dict):
        return {"groups": {}, "private_users": {}}
    if not isinstance(data.get("groups"), dict):
        data["groups"] = {}
    if not isinstance(data.get("private_users"), dict):
        data["private_users"] = {}
    return data


def save_data(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DATA_FILE)


def normalize_endpoint(value: str) -> str | None:
    text = value.strip()
    if not ENDPOINT_RE.fullmatch(text):
        return None
    return text


def parse_endpoint(endpoint: str) -> tuple[str, int | None]:
    text = endpoint.strip()
    if ":" not in text:
        return text, None
    host, port_text = text.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError:
        return text, None
    if not (1 <= port <= 65535):
        return text, None
    return host, port


def scope_key(event: dict[str, Any]) -> tuple[str, str, str]:
    message_type = str(event.get("message_type") or "").lower()
    if message_type == "group":
        group_id = str(event.get("group_id", "")).strip()
        return "groups", group_id, "群聊"
    user_id = str(event.get("user_id", "")).strip()
    return "private_users", user_id, "私聊"


def legacy_entry(value: Any) -> dict[str, str] | None:
    endpoint = normalize_endpoint(str(value))
    if not endpoint:
        return None
    host, _ = endpoint.rsplit(":", 1)
    return {"name": host, "endpoint": endpoint}


def normalize_entries(entries: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(entries, list):
        return result
    for item in entries:
        if isinstance(item, dict):
            endpoint = normalize_endpoint(str(item.get("endpoint") or item.get("ip") or item.get("host") or ""))
            if not endpoint:
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                name = endpoint.rsplit(":", 1)[0]
            result.append({"name": name, "endpoint": endpoint})
        else:
            entry = legacy_entry(item)
            if entry:
                result.append(entry)
    cleaned: list[dict[str, str]] = []
    seen = set()
    for entry in result:
        key = (entry["name"], entry["endpoint"])
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(entry)
    return cleaned


def scope_entries(data: dict[str, Any], scope: str, scope_id: str) -> list[dict[str, str]]:
    buckets = data.setdefault(scope, {})
    if not isinstance(buckets, dict):
        data[scope] = {}
        buckets = data[scope]
    entries = normalize_entries(buckets.get(scope_id, []))
    buckets[scope_id] = entries
    return entries


def save_scope_entries(data: dict[str, Any], scope: str, scope_id: str, entries: list[dict[str, str]]) -> None:
    buckets = data.setdefault(scope, {})
    if not isinstance(buckets, dict):
        data[scope] = {}
        buckets = data[scope]
    buckets[scope_id] = entries
    save_data(data)


def split_endpoint(endpoint: str) -> tuple[str, int | None]:
    text = endpoint.strip()
    if ":" not in text:
        return text, None
    host, port_text = text.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError:
        return text, None
    if not (1 <= port <= 65535):
        return text, None
    return host, port


def write_varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        temp = value & 0x7F
        value >>= 7
        if value:
            out.append(temp | 0x80)
        else:
            out.append(temp)
            break
    return bytes(out)


def read_varint_from_bytes(data: bytes, offset: int = 0) -> tuple[int, int]:
    num_read = 0
    result = 0
    while True:
        if offset + num_read >= len(data):
            raise ValueError("VarInt 截断")
        value = data[offset + num_read]
        result |= (value & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt 太长")
        if not (value & 0x80):
            break
    if result & (1 << 31):
        result -= 1 << 32
    return result, offset + num_read


def pack_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return write_varint(len(raw)) + raw


def unpack_string_from_bytes(data: bytes, offset: int = 0) -> tuple[str, int]:
    length, offset = read_varint_from_bytes(data, offset)
    if length < 0 or offset + length > len(data):
        raise ValueError("字符串长度非法")
    return data[offset:offset + length].decode("utf-8", errors="replace"), offset + length


def pack_packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = write_varint(packet_id) + payload
    return write_varint(len(body)) + body


async def read_varint_async(reader: asyncio.StreamReader) -> int:
    num_read = 0
    result = 0
    while True:
        byte = await reader.readexactly(1)
        value = byte[0]
        result |= (value & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt 太长")
        if not (value & 0x80):
            break
    if result & (1 << 31):
        result -= 1 << 32
    return result


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    length = await read_varint_async(reader)
    payload = await reader.readexactly(length)
    packet_id, offset = read_varint_from_bytes(payload, 0)
    return packet_id, payload[offset:]


async def resolve_minecraft_host(host: str, timeout: float = DNS_TIMEOUT) -> str:
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
    except socket.gaierror as exc:
        raise RuntimeError(f"DNS 解析失败：{exc.strerror or exc}") from exc
    except TimeoutError as exc:
        raise RuntimeError("DNS 解析超时") from exc
    except OSError as exc:
        raise RuntimeError(f"DNS 解析失败：{exc.strerror or exc}") from exc
    if not infos:
        raise RuntimeError("DNS 解析失败：没有可用地址")
    sockaddr = infos[0][4]
    return str(sockaddr[0])


async def query_minecraft_status(host: str, port: int | None, timeout: float = QUERY_TIMEOUT) -> dict[str, Any]:
    resolved_host = await resolve_minecraft_host(host)
    ports = [port] if port is not None else [25565]
    tasks = [
        asyncio.create_task(query_minecraft_status_once(host, resolved_host, target_port, protocol_version, timeout))
        for target_port in ports
        for protocol_version in PROTOCOL_VERSIONS
    ]
    failures: list[Exception] = []
    try:
        for finished in asyncio.as_completed(tasks):
            try:
                result = await finished
            except Exception as exc:
                failures.append(exc)
                continue
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            return result
        raise RuntimeError(str(failures[-1]) if failures else "无法获取服务器状态")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def query_minecraft_status_once(host: str, resolved_host: str, port: int, protocol_version: int, timeout: float) -> dict[str, Any]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(resolved_host, port), timeout=timeout)
    try:
        handshake_payload = b"".join([
            write_varint(protocol_version),
            pack_string(host),
            struct.pack(">H", port),
            write_varint(1),
        ])
        writer.write(pack_packet(0x00, handshake_payload))
        writer.write(pack_packet(0x00))
        await writer.drain()
        packet_id, payload = await asyncio.wait_for(read_packet(reader), timeout=timeout)
        if packet_id != 0x00:
            raise RuntimeError("服务器返回了非预期响应")
        response_text, _ = unpack_string_from_bytes(payload, 0)
        data = json.loads(response_text)
        if not isinstance(data, dict):
            raise RuntimeError("服务器响应不是对象")
        return data
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def text_from_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = str(value.get("text") or "") if isinstance(value.get("text"), str) else ""
        extra = value.get("extra")
        if isinstance(extra, list):
            text += "".join(text_from_json(item) for item in extra)
        return text
    if isinstance(value, list):
        return "".join(text_from_json(item) for item in value)
    return str(value) if value is not None else ""


def format_status(entry: dict[str, str], result: dict[str, Any] | None, error: str | None = None) -> str:
    label = entry.get("name") or entry["endpoint"]
    header = f"{label} ({entry['endpoint']})" if label != entry["endpoint"] else entry["endpoint"]
    if error:
        return f"{header}\n状态: 获取失败\n原因: {error}"
    if not result:
        return f"{header}\n状态: 获取失败\n原因: 未知错误"
    description = text_from_json(result.get("description"))
    version = result.get("version") if isinstance(result.get("version"), dict) else {}
    players = result.get("players") if isinstance(result.get("players"), dict) else {}
    player_online = players.get("online") if isinstance(players, dict) else None
    player_max = players.get("max") if isinstance(players, dict) else None
    sample = players.get("sample") if isinstance(players, dict) else None
    sample_names: list[str] = []
    if isinstance(sample, list):
        for item in sample:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    sample_names.append(str(name))
    lines = [header]
    lines.append(f"简介: {description or '无'}")
    if isinstance(version, dict):
        version_name = version.get("name")
        if version_name:
            lines.append(f"版本: {version_name}")
    if player_online is not None and player_max is not None:
        lines.append(f"在线人数: {player_online}/{player_max}")
    elif player_online is not None:
        lines.append(f"在线人数: {player_online}")
    if sample_names:
        if isinstance(player_online, int) and len(sample_names) < player_online:
            lines.append(f"玩家列表: {', '.join(sample_names)} 等")
        else:
            lines.append(f"玩家列表: {', '.join(sample_names)}")
    elif isinstance(player_online, int) and player_online > 0:
        lines.append("玩家列表: 有玩家在线，但未返回列表")
    else:
        lines.append("玩家列表: 无")
    return "\n".join(lines)


async def render_scope_status(entries: list[dict[str, str]]) -> list[str]:
    tasks = []
    for entry in entries:
        host, port = split_endpoint(entry["endpoint"])
        tasks.append(query_minecraft_status(host, port))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rendered: list[str] = []
    for entry, result in zip(entries, results, strict=False):
        if isinstance(result, Exception):
            rendered.append(format_status(entry, None, error=str(result)))
        else:
            rendered.append(format_status(entry, result))
    return rendered


def find_entry_by_name(entries: list[dict[str, str]], name: str) -> dict[str, str] | None:
    target = name.strip()
    if not target:
        return None
    for entry in entries:
        if entry.get("name") == target:
            return entry
    return None


def parse_add_args(arg: str) -> tuple[str | None, str]:
    parts = arg.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    action = parts[0].lower()
    if action not in {"add", "remove"}:
        return None, ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    return action, rest


def parse_add_target(rest: str) -> tuple[str | None, str]:
    parts = rest.split(maxsplit=1)
    endpoint = normalize_endpoint(parts[0]) if parts else None
    name = parts[1].strip() if len(parts) > 1 else ""
    return endpoint, name


def find_entry_index(entries: list[dict[str, str]], value: str) -> int | None:
    normalized = normalize_endpoint(value)
    target = value.strip()
    for index, entry in enumerate(entries):
        if normalized and entry["endpoint"] == normalized:
            return index
        if target and (entry.get("name") == target or entry["endpoint"] == target):
            return index
    return None


async def handler(event: dict[str, Any], arg: str, ctx: dict[str, Any]) -> None:
    scope, scope_id, scope_label = scope_key(event)
    if not scope_id:
        await ctx["reply"](event, "无法识别当前聊天。")
        return
    data = load_data()
    entries = scope_entries(data, scope, scope_id)
    action, rest = parse_add_args(arg)
    if action in {"add", "remove"}:
        if scope == "groups" and not ctx["is_controller"](event):
            await ctx["reply"](event, f"你没有权限管理本群的 Minecraft 服务器订阅。")
            return
        if not rest:
            await ctx["reply"](event, "用法：/mcserver add ip[:端口号] [显示名称]、/mcserver remove 名称或ip[:端口号]、/mcserver rename 旧名称 新名称")
            return
        if action == "add":
            endpoint, name = parse_add_target(rest)
            if not endpoint:
                await ctx["reply"](event, "用法：/mcserver add ip[:端口号] [显示名称]")
                return
            display_name = name or endpoint.rsplit(":", 1)[0]
            for item in entries:
                if item["endpoint"] == endpoint:
                    item["name"] = display_name
                    save_scope_entries(data, scope, scope_id, entries)
                    await ctx["reply"](event, f"已更新订阅：{display_name} ({endpoint})")
                    return
            entries.append({"name": display_name, "endpoint": endpoint})
            save_scope_entries(data, scope, scope_id, entries)
            await ctx["reply"](event, f"已添加订阅：{display_name} ({endpoint})")
            return
        remove_index = find_entry_index(entries, rest)
        if remove_index is None:
            await ctx["reply"](event, f"当前聊天没有找到要移除的服务器：{rest}")
            return
        removed = entries.pop(remove_index)
        save_scope_entries(data, scope, scope_id, entries)
        await ctx["reply"](event, f"已移除订阅：{removed.get('name') or removed['endpoint']} ({removed['endpoint']})")
        return
    if action == "rename":
        if scope == "groups" and not ctx["is_controller"](event):
            await ctx["reply"](event, "你没有权限管理本群的 Minecraft 服务器订阅。")
            return
        parts = rest.split(maxsplit=1)
        if len(parts) != 2:
            await ctx["reply"](event, "用法：/mcserver rename 旧名称 新名称")
            return
        old_name, new_name = parts[0].strip(), parts[1].strip()
        if not old_name or not new_name:
            await ctx["reply"](event, "用法：/mcserver rename 旧名称 新名称")
            return
        target = find_entry_by_name(entries, old_name)
        if target is None:
            await ctx["reply"](event, f"当前聊天没有找到名为 {old_name} 的服务器。")
            return
        target["name"] = new_name
        save_scope_entries(data, scope, scope_id, entries)
        await ctx["reply"](event, f"已重命名：{old_name} -> {new_name}")
        return
    if not entries:
        await ctx["reply"](event, f"当前{scope_label}还没有订阅任何 Minecraft 服务器。")
        return
    try:
        rendered = await render_scope_status(entries)
    except Exception as exc:
        await ctx["reply"](event, f"获取 Minecraft 服务器状态失败：{ctx['exception_detail'](exc)}")
        return
    await ctx["reply"](event, "\n\n".join(rendered))



COMMAND = {
    "name": "/mcserver",
    "usage": "/mcserver [add/remove/rename ip[:端口号] [显示名称]]",
    "description": "查看当前聊天订阅的 Minecraft 服务器；add、remove、rename 仅管理员可用。",
    "handler": handler,
}
