from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
import re
import time
from pathlib import Path


def reset_console_title() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("AnimeTrace")
    except Exception:
        pass


reset_console_title()

from playwright.async_api import async_playwright

DEFAULT_URL = os.getenv("ANIMETRACE_URL", "https://ai.animedb.cn/en/")
COMMON_BROWSER_PATHS = [
    Path(value.strip())
    for value in os.getenv(
        "ANIMETRACE_BROWSER_PATHS",
        ";".join([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]),
    ).split(";")
    if value.strip()
]
DEFAULT_WAIT_MS = int(os.getenv("ANIMETRACE_WAIT_MS", "20000"))
DEFAULT_CAPTURE_JSON = os.getenv("ANIMETRACE_CAPTURE_JSON", "0") == "1"
DEFAULT_BROWSER_PATH = os.getenv("ANIMETRACE_BROWSER_PATH", "").strip() or None


def pick_browser_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for path in COMMON_BROWSER_PATHS:
        if path.exists():
            return str(path)
    return None


async def run(image_path: Path, url: str, wait_ms: int, browser_path: str | None, capture_json: bool) -> dict[str, object]:
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    captured: list[tuple[str, str, str | None]] = []
    search_response = {"status": None, "content_type": None, "text": None, "url": None, "elapsed": None}
    search_response_obj = None
    search_response_at = None
    browser_executable = pick_browser_path(browser_path)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=browser_executable)
        page = await browser.new_page(viewport={"width": 1440, "height": 1200})
        page.on(
            "request",
            lambda req: captured.append((req.method, req.url, req.post_data))
            if ("animetrace" in req.url.lower() or "animedb" in req.url.lower())
            else None,
        )

        def handle_response(resp):
            nonlocal search_response_obj, search_response_at
            if "animetrace" in resp.url.lower() or "animedb" in resp.url.lower():
                captured.append((f"RESP {resp.status}", resp.url, None))
            if resp.request.method == "POST" and resp.url.rstrip("/").endswith("/v1/search") and search_response_obj is None:
                search_response_obj = resp
                search_response_at = time.perf_counter()

        page.on("response", handle_response)

        await page.goto(url, wait_until="networkidle")

        file_inputs = page.locator('input[type="file"]')
        if await file_inputs.count() == 0:
            raise RuntimeError("页面里没有找到文件上传控件")
        await file_inputs.first.set_input_files(str(image_path))

        clicked = False
        for label in ["识别", "Search", "识别图片", "提交", "Recognize"]:
            button = page.get_by_role("button", name=label)
            try:
                if await button.count():
                    await button.first.click()
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            try:
                await page.mouse.click(10, 10)
            except Exception:
                pass

        start = time.perf_counter()
        minimum_wait = min(max(wait_ms / 1000, 1), 3)
        deadline = start + max(wait_ms / 1000, 1)
        while time.perf_counter() < deadline:
            body_text = await page.locator("body").inner_text()
            lines = [re.sub(r"\s+", " ", raw).strip() for raw in body_text.splitlines()]
            lines = [line for line in lines if line]
            try:
                result_start = lines.index("Search result") + 1
            except ValueError:
                result_start = -1
            useful = []
            if result_start >= 0:
                for line in lines[result_start:]:
                    if line in {"New Notice!", "Notice Board", "Got it"} or "File Upload" in line:
                        break
                    if line not in {"Click the character name to view related images", "Results will appear here after uploading an image"}:
                        useful.append(line)
            if time.perf_counter() - start >= minimum_wait and (search_response_obj is not None or useful):
                break
            await page.wait_for_timeout(500)
        elapsed = time.perf_counter() - start
        body_text = await page.locator("body").inner_text()

        if search_response_obj is not None:
            search_response["status"] = search_response_obj.status
            search_response["content_type"] = search_response_obj.headers.get("content-type")
            search_response["url"] = search_response_obj.url
            search_response["elapsed"] = (search_response_at - start) if search_response_at is not None else None
            try:
                search_response["text"] = await search_response_obj.text()
            except Exception as exc:
                search_response["text"] = f"<failed to read response text: {type(exc).__name__}: {exc}>"

        print("TITLE:", await page.title())
        print("URL:", page.url)
        print("IMAGE:", str(image_path))
        print(f"WAITED_SECONDS: {elapsed:.2f}")
        print("SEARCH_RESPONSE_ELAPSED:", f"{search_response['elapsed']:.2f}" if search_response["elapsed"] is not None else "None")
        print("\nBODY_PREVIEW:\n")
        print(body_text[:6000])
        print("\nCAPTURED_NETWORK:\n")
        for method, req_url, post_data in captured:
            print(method, req_url)
            if post_data:
                print(post_data[:1200])
        if capture_json:
            print("\nSEARCH_JSON:\n")
            print(f"STATUS: {search_response['status']}")
            print(f"CONTENT_TYPE: {search_response['content_type']}")
            print(f"URL: {search_response['url']}")
            if search_response["text"] is not None:
                print(search_response["text"][:12000])
        print("\nRESULT_SNIPPET:\n")
        print(body_text[:6000])

        title = await page.title()
        current_url = page.url
        result = {
            "title": title,
            "url": current_url,
            "image": str(image_path),
            "waited_seconds": elapsed,
            "body_text": body_text,
            "captured_network": captured,
            "search_response": search_response,
        }
        await browser.close()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open AnimeTrace official website in a headless browser and upload an image.")
    parser.add_argument("image", help="Path to the image file")
    parser.add_argument("--url", default=DEFAULT_URL, help="Website URL")
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS, help="How long to wait for results after upload")
    parser.add_argument("--browser-path", default=DEFAULT_BROWSER_PATH, help="Optional browser executable path")
    parser.add_argument("--capture-json", action="store_true", default=DEFAULT_CAPTURE_JSON, help="Print the /v1/search JSON response if the page does not finish in time")
    parser.add_argument("--output-json", default="", help="Optional path to write the structured result JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_path = Path(args.image)
    result = asyncio.run(run(image_path, args.url, args.wait_ms, args.browser_path, args.capture_json))
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
