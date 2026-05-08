from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import aiohttp


DEFAULT_SERVER_URL = "http://127.0.0.1:8787"
MAX_CONTENT_CHARS = 24000


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
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + "\n...内容过长已截断，请降低 limit 或关闭 detail 后重试。"


def content_for(title: str, payload: dict[str, Any], data: dict[str, Any]) -> str:
    return "\n".join([
        title,
        f"服务: {server_url()}",
        f"请求: {json.dumps(payload, ensure_ascii=False)}",
        "结果 JSON:",
        compact_json(data),
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
        "搜索本地 VNDB 索引中的视觉小说或角色。实际逻辑：mode=vn/game 时搜索 VN 标题、原名、别名、v{id}；mode=character 时搜索角色名、原名、别名、c{id}，若角色没有直接命中，会把输入当 VN 名搜索并返回该 VN 里的角色。返回 slimVn/slimCharacter，VN 含 tagIds/tagVndbIds/tags、评分、投票、开发商和封面 ID，角色含 traitIds/traitVndbIds/traits、出演 VN、性别与人气分。detail=false 即可；detail=true 会展开 Tag/Trait 多语言元信息，响应明显变大，无必要不要开启。",
        {
            "mode": {"type": "string", "enum": ["vn", "game", "character"], "description": "搜索目标类型：vn/game 表示视觉小说，character 表示角色。"},
            "name": {"type": "string", "description": "名称、别名、原名或 VNDB ID，例如 白色相簿、冬馬かずさ、v2920、c35176。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "返回数量，默认 10。普通问答建议 5-10。"},
            "detail": {"type": "boolean", "description": "是否返回 Tag/Trait 详细多语言元信息。默认 false；响应会变大，无必要不要开启。"},
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
        "根据样本画像推荐相似 VN 或相似角色。强约束：一次调用只能传 VN 样本或角色样本，绝不能同时传 selectedVnIds 和 selectedCharacterIds，也不要同时混用 negativeSelectedVnIds 与 negativeSelectedCharacterIds；VN 样本只产出 VN 推荐，应配 VN 的 priorityTags/negativePriorityTags；角色样本只产出角色推荐，应配角色的 priorityTraits/negativePriorityTraits。VN 的 tags 和角色的 traits 是两套完全不同的 ID，绝不能把 tag 当 trait 或把 trait 当 tag。实际逻辑会用 VN tags 构建 VN 画像、用角色 traits 构建角色画像，排除样本本身和负向样本，并按 relevance/rating/votes/title/confidence 排序。普通相似推荐只传一个 selectedVnIds 或 selectedCharacterIds 数组即可，高阶参数无必要省略。",
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
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "返回数量，默认 10。"},
            "detail": {"type": "boolean", "description": "是否返回详细 tags/traits。默认 false；响应会变大，无必要不要开启。"},
        },
    )


def tag_search_definition() -> dict[str, Any]:
    return base_definition(
        "vndb_tag_search",
        "按 VN Tag 和/或角色 Trait 做精确检索。实际逻辑：只传 tags/tagSearchTags 会返回 tagSearchVnResults；只传 traits/tagSearchTraits 会返回 tagSearchCharacterResults；同时传 tags+traits 会额外返回 mixedTagResults，即同时满足 VN 标签和角色特征、且角色在匹配 VN 中有合格出演关系的组合。tags 是 VN 标签 ID，traits 是角色特征 ID，两者不同且不可混用。excludeTags/excludeTraits 会排除命中项，includeSpoiler 控制剧透项，roleFilter 控制角色在 VN 中的 primary/main/side/appears 出演类型。高阶参数无必要省略。",
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
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "返回数量，默认 10。"},
            "detail": {"type": "boolean", "description": "是否返回详细 tags/traits。默认 false；响应会变大，无必要不要开启。"},
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
        "获取某个 VN 或角色的本地索引信息和 VNDB API 完整详情。实际逻辑：可用 id/vndbid 精确定位 v{id}/c{id}，或用 name/query/q 先在本地索引搜索；VN 默认 fields 包括标题、别名、语言、平台、图片、长度、描述、评分、tags、开发商和关系，角色默认 fields 包括姓名、别名、描述、图片、身体资料、traits 和出演 VN。downloadImage/image 默认 true，会把 VNDB 图片下载到本地 cache/images 并把该图片塞进当前 LLM 上下文，使它临时成为后续 generate_image 可选择的图片编号；不会直接发 QQ。若 /switch photo false，本工具会强制不下载也不加入图片上下文。fields 是高阶参数，通常不要填写。",
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
    if action in {"search", "metaSearch", "recommend", "tagSearch"}:
        payload["limit"] = limited_int(payload.get("limit"), 10, 1, 50)
    if action == "detail" and not photo_is_enabled(ctx):
        payload["downloadImage"] = False
        payload["image"] = False
    try:
        data = await call_vndb(payload)
    except Exception as exc:
        return {"ok": False, "content": f"VNDB 工具调用失败：{ctx['exception_detail'](exc)}"}
    content = content_for(f"VNDB {action} 调用成功", payload, data)
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
                content += f"\n\n图片已加入当前 LLM 图片上下文，不会直接发送 QQ。后续如需生图，可在 generate_image 的 image_indexes 中选择图{index}。"
            else:
                content += f"\n\n图片已下载到本地缓存，但当前上下文不支持注入图片: {path}"
    elif action == "detail":
        content += "\n\n当前 /switch photo false，已按要求不下载也不加入图片上下文。"
    return {"ok": True, "content": content, "raw_result": data}
