from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import aiohttp


DEFAULT_SERVER_URL = "http://127.0.0.1:8787"
MAX_CONTENT_CHARS = 50000
MAX_TOOL_RESULTS = 30


def server_url() -> str:
    return (os.getenv("VNDB_JSON_SERVER_URL") or os.getenv("VNDB_JSON_SERVER") or DEFAULT_SERVER_URL).rstrip("/")


async def call_vndb(payload: dict[str, Any]) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(server_url(), json=payload, headers={"content-type": "application/json"}) as resp:
            text = await resp.text(errors="replace")
            if resp.status >= 400:
                raise RuntimeError(f"VNDB JSON Server HTTP {resp.status}: {text[:500]}")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"VNDB JSON Server 返回内容不是 JSON: {text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("VNDB JSON Server 返回的根对象不是 JSON object")
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or data))
    return data


def limited_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def compact_json(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + "\n...内容过长已截断。请基于已有内容回答；如信息不足，请让用户缩小范围或明确需要的字段。"


def scalar_fields(item: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: item[name] for name in names if name in item and item[name] is not None}


def short_aliases(value: Any, limit: int = 5) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value[:limit]


def short_developers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:3]:
        if isinstance(item, dict):
            result.append(scalar_fields(item, ("id", "name", "original")))
    return result


def short_vns(value: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:limit]:
        if isinstance(item, dict):
            result.append(scalar_fields(item, ("id", "vndbid", "title", "role", "spoiler")))
    return result


def short_tags(value: Any, limit: int = 30) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:limit]:
        if isinstance(item, dict):
            result.append(scalar_fields(item, ("id", "vndbid", "name", "rating", "spoiler", "lie")))
    return result


def short_text(value: Any, limit: int = 2000) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit] + "..."


def meta_title(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    meta = item.get("meta")
    if isinstance(meta, dict):
        return str(meta.get("title") or meta.get("name") or item.get("name") or "").strip()
    return str(item.get("name") or item.get("title") or "").strip()


def meta_parent_ids(item: Any) -> list[int]:
    meta = item.get("meta") if isinstance(item, dict) else None
    parents = meta.get("parents") if isinstance(meta, dict) else None
    if not isinstance(parents, list):
        return []
    result = []
    for parent in parents:
        try:
            result.append(int(parent))
        except (TypeError, ValueError):
            pass
    return result


def collect_parent_ids(data: Any, field: str) -> set[int]:
    result: set[int] = set()
    if isinstance(data, dict):
        value = data.get(field)
        if isinstance(value, list):
            for item in value:
                result.update(meta_parent_ids(item))
        for value in data.values():
            result.update(collect_parent_ids(value, field))
    elif isinstance(data, list):
        for item in data:
            result.update(collect_parent_ids(item, field))
    return result


def grouped_titles(items: Any, parent_titles: dict[int, str], fallback_name: str) -> dict[str, list[str]]:
    if not isinstance(items, list):
        return {}
    groups: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    own_titles: dict[int, str] = {}
    for item in items:
        if isinstance(item, dict):
            try:
                own_titles[int(item.get("id"))] = meta_title(item)
            except (TypeError, ValueError):
                pass
    for item in items:
        if not isinstance(item, dict):
            continue
        title = meta_title(item)
        if not title:
            continue
        parents = meta_parent_ids(item)
        parent_title = ""
        for parent_id in parents:
            parent_title = parent_titles.get(parent_id) or own_titles.get(parent_id) or ""
            if parent_title:
                break
        group = parent_title or fallback_name
        if title == group:
            continue
        bucket = groups.setdefault(group, [])
        bucket_seen = seen.setdefault(group, set())
        if title not in bucket_seen:
            bucket.append(title)
            bucket_seen.add(title)
    return groups


def compact_vn_item(item: Any, parent_titles: dict[int, str] | None = None) -> Any:
    if not isinstance(item, dict):
        return item
    result = scalar_fields(item, (
        "id", "vndbid", "title", "original", "rating", "votes", "average", "searchRank", "exactRank",
        "similarity", "confidence", "priorityConfidence", "consensusBonus", "score",
    ))
    aliases = short_aliases(item.get("aliases"))
    if aliases:
        result["aliases"] = aliases
    developers = short_developers(item.get("developers"))
    if developers:
        result["developers"] = developers
    if isinstance(item.get("image"), (str, int)):
        result["image"] = item.get("image")
    tag_groups = grouped_titles(item.get("tags"), parent_titles or {}, "other")
    if tag_groups:
        result["tagGroups"] = tag_groups
    return result


def compact_character_item(item: Any, parent_titles: dict[int, str] | None = None) -> Any:
    if not isinstance(item, dict):
        return item
    result = scalar_fields(item, (
        "id", "vndbid", "name", "original", "sex", "gender", "birthday", "score", "searchRank", "exactRank",
        "similarity", "confidence", "priorityConfidence", "consensusBonus", "companyBoost",
    ))
    aliases = short_aliases(item.get("aliases"))
    if aliases:
        result["aliases"] = aliases
    vns = short_vns(item.get("vns"))
    if vns:
        result["relatedVns"] = vns
    if isinstance(item.get("image"), (str, int)):
        result["image"] = item.get("image")
    trait_groups = grouped_titles(item.get("traits"), parent_titles or {}, "other")
    if trait_groups:
        result["traitGroups"] = trait_groups
    return result


def compact_mixed_item(item: Any, tag_parent_titles: dict[int, str] | None = None, trait_parent_titles: dict[int, str] | None = None) -> Any:
    if not isinstance(item, dict):
        return item
    result = scalar_fields(item, ("vnId", "characterId", "score", "similarity", "confidence", "priorityConfidence"))
    if isinstance(item.get("vn"), dict):
        result["vn"] = compact_vn_item(item["vn"], tag_parent_titles)
    if isinstance(item.get("character"), dict):
        result["character"] = compact_character_item(item["character"], trait_parent_titles)
    return result


def compact_params(params: Any) -> Any:
    if not isinstance(params, dict):
        return params
    return scalar_fields(params, (
        "selectedVnIds", "selectedCharacterIds", "negativeSelectedVnIds", "negativeSelectedCharacterIds",
        "priorityTags", "priorityTraits", "negativePriorityTags", "negativePriorityTraits", "includeSpoiler",
        "minVotes", "sort", "direction", "preferCharacterAverage",
    ))


def compact_search_data(data: dict[str, Any]) -> dict[str, Any]:
    result = scalar_fields(data, ("ok", "action", "mode", "query", "fallbackFromVnSearch"))
    items = data.get("results")
    if isinstance(items, list):
        is_character = data.get("mode") == "character" or any(isinstance(item, dict) and str(item.get("vndbid", "")).startswith("c") for item in items)
        mapper = compact_character_item if is_character else compact_vn_item
        result["results"] = [mapper(item) for item in items[:MAX_TOOL_RESULTS]]
    return result


async def meta_titles_by_ids(ids: set[int], kind: str) -> dict[int, str]:
    if not ids:
        return {}
    try:
        data = await call_vndb({"action": "classify", "kind": kind, "ids": sorted(ids), "includeSpoiler": True})
    except Exception:
        return {}
    result: dict[int, str] = {}
    groups = data.get("groups")
    if not isinstance(groups, list):
        return result
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("selected"), dict):
            continue
        selected = group["selected"]
        try:
            selected_id = int(selected.get("id"))
        except (TypeError, ValueError):
            continue
        title = str(selected.get("title") or selected.get("name") or "").strip()
        if title:
            result[selected_id] = title
    return result


def compact_recommend_data(data: dict[str, Any], tag_parent_titles: dict[int, str] | None = None, trait_parent_titles: dict[int, str] | None = None) -> dict[str, Any]:
    result = scalar_fields(data, ("ok", "action"))
    if "params" in data:
        result["params"] = compact_params(data.get("params"))
    tag_parent_titles = tag_parent_titles or {}
    trait_parent_titles = trait_parent_titles or {}
    mappings = {
        "vnRecommendations": lambda item: compact_vn_item(item, tag_parent_titles),
        "characterRecommendations": lambda item: compact_character_item(item, trait_parent_titles),
        "tagSearchVnResults": lambda item: compact_vn_item(item, tag_parent_titles),
        "tagSearchCharacterResults": lambda item: compact_character_item(item, trait_parent_titles),
        "mixedTagResults": lambda item: compact_mixed_item(item, tag_parent_titles, trait_parent_titles),
    }
    for name, mapper in mappings.items():
        value = data.get(name)
        if isinstance(value, list):
            result[name] = [mapper(item) for item in value[:MAX_TOOL_RESULTS]]
    return result


def compact_meta_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    return scalar_fields(item, ("id", "vndbid", "title", "name", "nameZh", "nameJa", "sexual", "defaultspoil", "group"))


def compact_meta_search_data(data: dict[str, Any]) -> dict[str, Any]:
    result = scalar_fields(data, ("ok", "action", "kind", "query"))
    items = data.get("results")
    if isinstance(items, list):
        result["results"] = [compact_meta_item(item) for item in items[:MAX_TOOL_RESULTS]]
    return result


def compact_vndb_api(api: Any, target_type: str) -> Any:
    if not isinstance(api, dict):
        return api
    common = ("id", "title", "alttitle", "name", "original", "aliases", "olang", "released", "languages", "platforms", "length", "length_minutes", "description", "rating", "votecount", "sex", "blood_type", "height", "weight", "bust", "waist", "hips", "birthday", "age")
    result = scalar_fields(api, common)
    if "description" in result:
        result["description"] = short_text(result["description"])
    if isinstance(api.get("image"), dict):
        result["image"] = scalar_fields(api["image"], ("url", "sexual", "violence", "votecount", "dims"))
    if target_type == "vn":
        if isinstance(api.get("tags"), list):
            result["tags"] = api.get("tags")
        if isinstance(api.get("developers"), list):
            result["developers"] = api.get("developers")
        if isinstance(api.get("relations"), list):
            result["relations"] = api.get("relations")
    else:
        if isinstance(api.get("traits"), list):
            result["traits"] = api.get("traits")
        if isinstance(api.get("vns"), list):
            result["vns"] = api.get("vns")
    return result


def compact_detail_data(data: dict[str, Any]) -> dict[str, Any]:
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    target_type = str(target.get("type") or "")
    result: dict[str, Any] = scalar_fields(data, ("ok", "action"))
    if target:
        result["target"] = scalar_fields(target, ("type", "id", "vndbid"))
    local = data.get("local")
    if isinstance(local, dict):
        result["local"] = compact_character_item(local) if target_type == "character" else compact_vn_item(local)
    if "vndbApi" in data:
        result["vndbApi"] = compact_vndb_api(data.get("vndbApi"), target_type)
    if isinstance(data.get("image"), dict):
        image = data["image"]
        result["image"] = {
            key: value for key, value in {
                "url": image.get("url"),
                "cache": scalar_fields(image.get("cache"), ("localPath", "cached")) if isinstance(image.get("cache"), dict) else None,
                "cacheError": image.get("cacheError"),
            }.items() if value is not None
        }
    return result


async def compact_tool_data(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action == "search":
        return compact_search_data(data)
    if action in {"recommend", "tagSearch"}:
        tag_parent_titles = await meta_titles_by_ids(collect_parent_ids(data, "tags"), "tag")
        trait_parent_titles = await meta_titles_by_ids(collect_parent_ids(data, "traits"), "trait")
        return compact_recommend_data(data, tag_parent_titles, trait_parent_titles)
    if action == "metaSearch":
        return compact_meta_search_data(data)
    if action == "detail":
        return compact_detail_data(data)
    return data


async def content_for(title: str, payload: dict[str, Any], data: dict[str, Any], action: str | None = None) -> str:
    display_data = await compact_tool_data(action or str(payload.get("action") or ""), data)
    return "\n".join([
        title,
        f"服务: {server_url()}",
        f"请求: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}",
        "结果 JSON:",
        compact_json(display_data),
    ])


def base_definition(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


def info_from_definition(definition: dict[str, Any]) -> dict[str, str]:
    function = definition.get("function", {})
    return {"name": str(function.get("name") or ""), "description": str(function.get("description") or "")}


def status_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_status",
        "查看本地 VNDB JSON Server 状态、数据版本、索引规模和最近更新时间。适合在不确定服务是否启动或数据是否可用时调用。",
        {},
    )


def update_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_update",
        "手动检查 VNDB JSON Server 远端数据更新。通常不需要调用；只有用户明确要求刷新/检查 VNDB 数据时使用。force=true 会强制重新下载，除非用户明确要求，否则不要使用。",
        {
            "force": {"type": "boolean", "description": "是否强制重新下载数据。默认 false；高成本参数，无必要不要启用。"},
        },
    )


def search_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_search",
        "搜索本地 VNDB 索引中的视觉小说或角色。实际逻辑：mode=vn/game 时搜索 VN 标题、原名、别名、v{id}；mode=character 时搜索角色名、原名、别名、c{id}，若角色没有直接命中，会把输入当 VN 名搜索并返回该 VN 里的角色。搜索结果只返回前十条精简候选，不携带 tags/traits 元数据或描述；不要根据单次搜索结果总结多个候选的共同画像信息。需要作品/角色精确信息时，拿 vndbid 调 vndb_detail。若搜索无结果或结果不确定，不要反复换词重试；直接告诉用户未命中或让用户提供更准确名称/ID。",
        {
            "mode": {"type": "string", "enum": ["vn", "game", "character"], "description": "搜索目标类型：vn/game 表示视觉小说，character 表示角色。"},
            "name": {"type": "string", "description": "名称、别名、原名或 VNDB ID，例如 白色相簿、冬馬かずさ、v2920、c35176。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "返回数量，默认 10，最多 30。"},
            "detail": {"type": "boolean", "description": "兼容参数。搜索结果会被清洗为精简候选，不返回 tags/traits 元数据或描述。"},
            "birthMonth": {"type": "array", "items": {"type": "integer"}, "description": "角色生日月份过滤，1-12。可传单个值或数组。例如 [9] 只返回9月出生的角色。仅对 mode=character 生效。"},
            "birthDay": {"type": "array", "items": {"type": "integer"}, "description": "角色生日日期过滤，1-31。可传单个值或数组。若与 birthMonth 同时指定，则角色必须同时满足月份和日期。仅对 mode=character 生效。"},
        },
        ["mode", "name"],
    )


def meta_search_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_meta_search",
        "搜索本地 VNDB 的元信息 ID。kind=tag 只对应 VN 标签，kind=trait 只对应角色特征；两者是两套完全不同的体系，不能混用。实际逻辑会在 name/nameZh/nameJa/alias/description/descriptionZh/descriptionJa 和数字 ID 中做包含匹配，并按名称排序。用于先查 Tag/Trait ID，再给 vndb_tag_search 或 vndb_recommend 的 priorityTags/priorityTraits 使用。",
        {
            "kind": {"type": "string", "enum": ["tag", "trait"], "description": "tag 表示 VN 标签，trait 表示角色特征。"},
            "name": {"type": "string", "description": "Tag/Trait 名称、别名或关键词，例如 学園、青髪。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "返回数量，默认 10。"},
        },
        ["kind", "name"],
    )


def recommend_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_recommend",
        "根据样本画像推荐相似 VN 或相似角色。强约束：一次调用只能传 VN 样本或角色样本，绝不能同时传 selectedVnIds 和 selectedCharacterIds，也不要同时混用 negativeSelectedVnIds 与 negativeSelectedCharacterIds；VN 样本只产出 VN 推荐，应配 VN 的 priorityTags/negativePriorityTags；角色样本只产出角色推荐，应配角色的 priorityTraits/negativePriorityTraits。VN 的 tags 和角色的 traits 是两套完全不同的 ID，绝不能把 tag 当 trait 或把 trait 当 tag。返回结果只保留前十条候选，包括标题/名称、相关作品、VNDB 编号、评分/票数、相似度/置信度等，并携带轻量 tagGroups/traitGroups：只按父级标题分组列出子标签标题，不含描述和其它元数据。",
        {
            "selectedVnIds": {"type": "array", "items": {"type": "string"}, "description": "正向参考 VN ID，如 [\"v2920\"]。只能用于 VN 推荐；使用它时不要传 selectedCharacterIds/negativeSelectedCharacterIds/priorityTraits。"},
            "selectedCharacterIds": {"type": "array", "items": {"type": "string"}, "description": "正向参考角色 ID，如 [\"c35176\"]。只能用于角色推荐；使用它时不要传 selectedVnIds/negativeSelectedVnIds/priorityTags。"},
            "negativeSelectedVnIds": {"type": "array", "items": {"type": "string"}, "description": "负向 VN 样本。只在 VN 推荐中使用；不想要类似某些 VN 时使用。"},
            "negativeSelectedCharacterIds": {"type": "array", "items": {"type": "string"}, "description": "负向角色样本。只在角色推荐中使用；不想要类似某些角色时使用。"},
            "sampleWeights": {"type": "array", "items": {"type": "number"}, "description": "正向样本权重，顺序对应正向 ID。高阶参数，无必要省略。"},
            "negativeSampleWeights": {"type": "array", "items": {"type": "number"}, "description": "负向样本权重，顺序对应负向 ID。高阶参数，无必要省略。"},
            "priorityTags": {"type": "array", "items": {"type": "integer"}, "description": "重点 VN Tag 数字 ID，只能和 selectedVnIds 一起用。需先用 vndb_meta_search(kind=tag) 查 ID；无必要省略。"},
            "priorityTraits": {"type": "array", "items": {"type": "integer"}, "description": "重点角色 Trait 数字 ID，只能和 selectedCharacterIds 一起用。需先用 vndb_meta_search(kind=trait) 查 ID；无必要省略。"},
            "negativePriorityTags": {"type": "array", "items": {"type": "integer"}, "description": "排除/负向 VN Tag 数字 ID，只能用于 VN 推荐；无必要省略。"},
            "negativePriorityTraits": {"type": "array", "items": {"type": "integer"}, "description": "排除/负向角色 Trait 数字 ID，只能用于角色推荐；无必要省略。"},
            "includeSpoiler": {"type": "boolean", "description": "是否允许剧透 Tag/Trait 参与推荐。默认 false；除非用户接受剧透，否则不要开启。"},
            "minVotes": {"type": "integer", "description": "VN 最低投票数过滤，默认 50。想要冷门作品可降低。"},
            "tagLimit": {"type": "integer", "description": "VN 画像抽取 Tag 数，默认 60。高阶参数，无必要省略。"},
            "traitLimit": {"type": "integer", "description": "角色画像抽取 Trait 数，默认 60。高阶参数，无必要省略。"},
            "profileSampleRounds": {"type": "integer", "description": "画像随机化轮数，默认 6。高阶参数，无必要省略。"},
            "preferCharacterAverage": {"type": "boolean", "description": "角色推荐排序是否参考关联 VN 平均分，默认 true。"},
            "sort": {"type": "string", "enum": ["relevance", "rating", "votes", "title", "confidence"], "description": "排序字段，默认 relevance。"},
            "direction": {"type": "string", "enum": ["desc", "asc"], "description": "排序方向，默认 desc。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "返回数量，默认 10，最多 30。"},
            "detail": {"type": "boolean", "description": "兼容参数。推荐结果会被清洗为前十条候选，tag/trait 仅以父级标题分组列出标题，不返回描述。"},
            "birthMonth": {"type": "array", "items": {"type": "integer"}, "description": "角色生日月份过滤，1-12。可传单个值或数组。例如 [9] 只返回9月出生的角色。仅对角色推荐生效；VN 推荐忽略此参数。"},
            "birthDay": {"type": "array", "items": {"type": "integer"}, "description": "角色生日日期过滤，1-31。可传单个值或数组。若与 birthMonth 同时指定，则角色必须同时满足月份和日期。仅对角色推荐生效；VN 推荐忽略此参数。"},
        },
    )


def tag_search_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_tag_search",
        "按 VN Tag 和/或角色 Trait 做精确检索。实际逻辑：只传 tags/tagSearchTags 会返回 tagSearchVnResults；只传 traits/tagSearchTraits 会返回 tagSearchCharacterResults；同时传 tags+traits 会额外返回 mixedTagResults，即同时满足 VN 标签和角色特征、且角色在匹配 VN 中有合格出演关系的组合。tags 是 VN 标签 ID，traits 是角色特征 ID，两者不同且不可混用。返回结果只保留前十条候选，并携带轻量 tagGroups/traitGroups：只按父级标题分组列出子标签标题，不含描述和其它元数据。",
        {
            "tags": {"type": "array", "items": {"type": "integer"}, "description": "VN Tag ID 列表。"},
            "traits": {"type": "array", "items": {"type": "integer"}, "description": "角色 Trait ID 列表。"},
            "tagSearchTags": {"type": "array", "items": {"type": "integer"}, "description": "tags 的别名参数，兼容网页命名。"},
            "tagSearchTraits": {"type": "array", "items": {"type": "integer"}, "description": "traits 的别名参数，兼容网页命名。"},
            "excludeTags": {"type": "array", "items": {"type": "integer"}, "description": "排除 VN Tag ID。"},
            "excludeTraits": {"type": "array", "items": {"type": "integer"}, "description": "排除角色 Trait ID。"},
            "excludedTagSearchTags": {"type": "array", "items": {"type": "integer"}, "description": "excludeTags 的别名参数。"},
            "excludedTagSearchTraits": {"type": "array", "items": {"type": "integer"}, "description": "excludeTraits 的别名参数。"},
            "includeSpoiler": {"type": "boolean", "description": "是否包含剧透标签/特征。默认 false。"},
            "minVotes": {"type": "integer", "description": "VN 最低投票数，默认 50。"},
            "roleFilter": {"type": "object", "description": "混合检索中角色出现类型过滤，例如 {primary:true, main:true, side:true, appears:false}。高阶参数，无必要省略。"},
            "sort": {"type": "string", "enum": ["relevance", "rating", "votes", "title", "confidence"], "description": "排序字段，默认 relevance。"},
            "direction": {"type": "string", "enum": ["desc", "asc"], "description": "排序方向，默认 desc。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "返回数量，默认 10，最多 30。"},
            "detail": {"type": "boolean", "description": "兼容参数。检索结果会被清洗为前十条候选，tag/trait 仅以父级标题分组列出标题，不返回描述。"},
            "birthMonth": {"type": "array", "items": {"type": "integer"}, "description": "角色生日月份过滤，1-12。可传单个值或数组。例如 [9] 只返回9月出生的角色。仅对角色/混合检索结果生效。"},
            "birthDay": {"type": "array", "items": {"type": "integer"}, "description": "角色生日日期过滤，1-31。可传单个值或数组。若与 birthMonth 同时指定，则角色必须同时满足月份和日期。仅对角色/混合检索结果生效。"},
        },
    )


def classify_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_classify",
        "查看 Tag/Trait 父子分类展开结果。实际逻辑会把传入的父级/选中 ID 展开为 selected 和 alternatives；kind=tag 使用 VN 标签树，kind=trait 使用角色特征树，两者不能混用。通常在高阶 tagSearch/recommend 前，用来确认一个父级 ID 会覆盖哪些子项；includeSpoiler=false 默认排除剧透子项。",
        {
            "kind": {"type": "string", "enum": ["tag", "trait"], "description": "tag 或 trait。"},
            "ids": {"type": "array", "items": {"type": "integer"}, "description": "要展开的 Tag/Trait 数字 ID 列表。"},
            "includeSpoiler": {"type": "boolean", "description": "是否包含剧透项，默认 false。"},
        },
        ["kind", "ids"],
    )


def detail_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_detail",
        "获取单个 VN 或角色的精确信息：本地索引信息和来自 VNDB API 的详情。只在已经通过 vndb_search 确定唯一 vndbid，或用户明确指定 v{id}/c{id} 并需要单个作品/角色的完整资料、描述、图片、标签/特征明细时使用；不要为了普通相似推荐、画像搜索或多候选比较调用本工具。若名称不确定，先搜索一次即可，不要反复用不同拼写调用。实际逻辑：可用 id/vndbid 精确定位 v{id}/c{id}，或用 name/query/q 先在本地索引搜索。返回内容会尽量携带 VNDB API 回传的完整精确信息，并由程序补充本地信息。downloadImage/image 默认 true，会把 VNDB 图片下载到本地 cache/images 并把该图片塞进当前上下文，使它临时成为后续 generate_image 可选择的图片编号。fields 是高阶参数，通常不要填写；只有用户明确要求特定 API 字段时使用。",
        {
            "mode": {"type": "string", "enum": ["vn", "game", "character"], "description": "目标类型。不传时服务会根据 id 推断；用名称查询时建议明确传 vn 或 character。"},
            "kind": {"type": "string", "enum": ["vn", "game", "character"], "description": "mode 的别名参数。"},
            "name": {"type": "string", "description": "名称、别名或搜索文本。"},
            "query": {"type": "string", "description": "name 的别名参数。"},
            "q": {"type": "string", "description": "name 的别名参数。"},
            "id": {"type": "string", "description": "VNDB ID，例如 v2920 或 c35176。"},
            "vndbid": {"type": "string", "description": "id 的别名参数，例如 v2920 或 c35176。"},
            "downloadImage": {"type": "boolean", "description": "是否让 VNDB JSON Server 下载图片到本地缓存。默认 true；若 /switch photo false，本工具会强制不下载且不加入 LLM 图片上下文。"},
            "image": {"type": "boolean", "description": "downloadImage 的别名参数。"},
            "fields": {"type": "string", "description": "自定义 VNDB API fields。高阶参数，通常不要填写，除非用户明确要求特定 API 字段。"},
        },
    )


def photo_is_enabled(ctx: dict[str, Any]) -> bool:
    checker = ctx.get("photo_enabled")
    return bool(checker()) if callable(checker) else True


def detail_image_path(data: dict[str, Any]) -> Path | None:
    image = data.get("image")
    if not isinstance(image, dict):
        return None
    cache = image.get("cache")
    if not isinstance(cache, dict):
        return None
    local_path = str(cache.get("localPath") or "").strip()
    if not local_path:
        return None
    path = Path(local_path)
    return path if path.exists() else None


async def execute_action(action: str, args: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    payload = dict(args)
    payload["action"] = action
    if action in {"search", "recommend", "tagSearch"}:
        payload["limit"] = limited_int(payload.get("limit"), 10, 1, MAX_TOOL_RESULTS)
    elif action == "metaSearch":
        payload["limit"] = limited_int(payload.get("limit"), 10, 1, 50)
    if action == "detail" and not photo_is_enabled(ctx):
        payload["downloadImage"] = False
        payload["image"] = False
    try:
        data = await call_vndb(payload)
    except Exception as exc:
        return {"ok": False, "content": f"VNDB 工具调用失败：{ctx['exception_detail'](exc)}"}
    content = await content_for(f"VNDB {action} 调用成功", payload, data, action)
    if action == "detail" and photo_is_enabled(ctx):
        path = detail_image_path(data)
        if path:
            add_image_context = ctx.get("add_tool_image_context")
            if callable(add_image_context):
                record = add_image_context(runtime["event"], path, f"VNDB 详情图片已加入上下文: {path.name}")
                images = runtime.setdefault("images", [])
                if isinstance(images, list) and record not in images:
                    images.append(record)
                    del images[ctx.get("max_context_images", 10):]
                index = images.index(record) + 1 if isinstance(images, list) and record in images else "?"
                content += f"\n\n图片已加入当前 LLM 图片上下文。后续如需生图，可在 generate_image 的 image_indexes 中选择图{index}。"
            else:
                content += f"\n\n图片已下载到本地缓存，但当前上下文不支持注入图片: {path}"
    elif action == "detail":
        content += "\n\n当前 /switch photo false，图片不会被下载。"
    return {"ok": True, "content": content, "raw_result": data}
