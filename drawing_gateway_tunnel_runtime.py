from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import aiohttp


@dataclass(frozen=True)
class DrawingGatewayTunnelLifecycleSettings:
    enabled: bool
    configured: bool
    base_url: str
    api_key: str
    start_timeout_seconds: float
    restart_delay_seconds: float
    probe_timeout_seconds: float


def clean_runtime_error(value: object, limit: int = 400) -> str:
    text = " ".join(str(value).replace("\x00", "").split())
    for key in (
        "DRAWING_GATEWAY_API_KEY",
        "DRAWING_GATEWAY_SSH_KEY_PATH",
    ):
        secret = os.getenv(key, "").strip()
        if not secret:
            continue
        text = text.replace(secret, "<redacted>")
        expanded = str(Path(os.path.expandvars(secret)).expanduser())
        text = text.replace(expanded, "<redacted>")
    if not text:
        return "未知错误"
    return text[:limit] + ("..." if len(text) > limit else "")


def configured_seconds(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字。") from exc
    if value < minimum or value > maximum:
        raise ValueError(
            f"{name} 必须在 {minimum:g} 到 {maximum:g} 之间。"
        )
    return value


def lifecycle_settings() -> DrawingGatewayTunnelLifecycleSettings:
    return DrawingGatewayTunnelLifecycleSettings(
        enabled=os.getenv(
            "DRAWING_GATEWAY_TUNNEL_AUTO_START",
            "1",
        ).strip() != "0",
        configured=bool(
            os.getenv("DRAWING_GATEWAY_SSH_HOST", "").strip()
        ),
        base_url=os.getenv(
            "DRAWING_GATEWAY_BASE_URL",
            "",
        ).strip().rstrip("/"),
        api_key=os.getenv(
            "DRAWING_GATEWAY_API_KEY",
            "",
        ).strip(),
        start_timeout_seconds=configured_seconds(
            "DRAWING_GATEWAY_TUNNEL_START_TIMEOUT_SECONDS",
            45.0,
            1.0,
            600.0,
        ),
        restart_delay_seconds=configured_seconds(
            "DRAWING_GATEWAY_TUNNEL_RESTART_DELAY_SECONDS",
            10.0,
            1.0,
            600.0,
        ),
        probe_timeout_seconds=configured_seconds(
            "DRAWING_GATEWAY_TUNNEL_PROBE_TIMEOUT_SECONDS",
            5.0,
            0.2,
            60.0,
        ),
    )


class DrawingGatewayTunnelLifecycle:
    def __init__(
        self,
        root: Path,
        env_file: Path,
        logger: Callable[[str], None],
    ) -> None:
        self.root = root
        self.env_file = env_file
        self.script = root / "drawing_gateway_tunnel.py"
        self.logger = logger
        self.process: asyncio.subprocess.Process | None = None
        self.supervisor_task: asyncio.Task[None] | None = None
        self.log_tasks: set[asyncio.Task[Any]] = set()
        self.recent_logs: deque[str] = deque(maxlen=16)
        self.last_exit_detail = ""
        self.external_forward_detail = ""
        self.stop_requested = False
        self.settings: DrawingGatewayTunnelLifecycleSettings | None = None

    async def pipe_log(
        self,
        stream: asyncio.StreamReader | None,
        name: str,
    ) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            detail = clean_runtime_error(
                line.decode(
                    "utf-8",
                    errors="replace",
                ).rstrip()
            )
            if detail != "未知错误":
                self.recent_logs.append(f"{name}: {detail}")
                self.logger(f"Drawing Gateway tunnel {name}: {detail}")

    async def spawn(self) -> asyncio.subprocess.Process:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        return await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.script),
            "--env-file",
            str(self.env_file),
            cwd=str(self.root),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )

    async def supervise(self) -> None:
        settings = self.settings
        if settings is None:
            return
        while not self.stop_requested:
            try:
                process = await self.spawn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_exit_detail = (
                    "无法启动隧道进程："
                    f"{clean_runtime_error(exc)}"
                )
                self.logger(
                    "Drawing Gateway tunnel start failed: "
                    f"{self.last_exit_detail}"
                )
                await asyncio.sleep(settings.restart_delay_seconds)
                continue
            self.process = process
            process_log_tasks: list[asyncio.Task[Any]] = []
            for stream, name in (
                (process.stdout, "stdout"),
                (process.stderr, "stderr"),
            ):
                task = asyncio.create_task(self.pipe_log(stream, name))
                process_log_tasks.append(task)
                self.log_tasks.add(task)
                task.add_done_callback(self.log_tasks.discard)
            returncode = await process.wait()
            await asyncio.gather(
                *process_log_tasks,
                return_exceptions=True,
            )
            if self.process is process:
                self.process = None
            if self.stop_requested:
                return
            recent = " | ".join(list(self.recent_logs)[-2:])
            self.last_exit_detail = f"进程退出码 {returncode}"
            if recent:
                self.last_exit_detail += f"：{recent}"
            self.logger(
                "Drawing Gateway tunnel exited: "
                f"{self.last_exit_detail}"
            )
            if returncode == 2:
                return
            reachable, detail = await self.probe()
            if reachable:
                self.external_forward_detail = detail
                self.logger(
                    "Drawing Gateway tunnel remains reachable through "
                    f"another process: {detail}"
                )
                while not self.stop_requested:
                    await asyncio.sleep(
                        settings.restart_delay_seconds
                    )
                    reachable, _ = await self.probe()
                    if not reachable:
                        self.external_forward_detail = ""
                        break
                continue
            await asyncio.sleep(settings.restart_delay_seconds)

    async def probe(self) -> tuple[bool, str]:
        settings = self.settings
        if settings is None or not settings.base_url:
            return False, "缺少 DRAWING_GATEWAY_BASE_URL"
        try:
            parsed = urlsplit(settings.base_url)
        except ValueError:
            return False, "DRAWING_GATEWAY_BASE_URL 格式无效"
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return False, "DRAWING_GATEWAY_BASE_URL 格式无效"
        headers = (
            {"X-API-Key": settings.api_key}
            if settings.api_key
            else {}
        )
        timeout = aiohttp.ClientTimeout(
            total=settings.probe_timeout_seconds
        )
        try:
            async with aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
            ) as session:
                async with session.get(
                    f"{settings.base_url}/health/ready",
                    allow_redirects=False,
                ) as response:
                    return True, (
                        "本地转发已连接，"
                        f"Drawing Gateway 返回 HTTP {response.status}"
                    )
        except asyncio.TimeoutError:
            return False, "Drawing Gateway 本地转发探测超时"
        except (aiohttp.ClientError, OSError) as exc:
            return False, (
                "Drawing Gateway 本地转发尚不可达："
                f"{type(exc).__name__}"
            )

    async def start(self) -> tuple[bool, str]:
        try:
            settings = lifecycle_settings()
        except ValueError as exc:
            return False, clean_runtime_error(exc)
        self.settings = settings
        if not settings.enabled:
            return True, "自动启动已关闭"
        if not settings.configured:
            return True, "未配置 SSH 隧道"
        if not self.script.is_file():
            return False, f"隧道脚本不存在：{self.script.name}"
        task = self.supervisor_task
        if task is None or task.done():
            self.stop_requested = False
            self.last_exit_detail = ""
            self.external_forward_detail = ""
            self.recent_logs.clear()
            task = asyncio.create_task(self.supervise())
            self.supervisor_task = task
        deadline = time.monotonic() + settings.start_timeout_seconds
        last_probe_detail = "等待隧道进程启动"
        while time.monotonic() < deadline:
            if task.done():
                results = await asyncio.gather(
                    task,
                    return_exceptions=True,
                )
                error = results[0] if results else None
                if isinstance(error, BaseException):
                    return False, (
                        "隧道监督任务失败："
                        f"{clean_runtime_error(error)}"
                    )
                return False, (
                    self.last_exit_detail
                    or "隧道进程未能保持运行"
                )
            if self.external_forward_detail:
                return True, (
                    "已有本地转发可用，失效后由 bot 接管："
                    f"{self.external_forward_detail}"
                )
            process = self.process
            if process is not None and process.returncode is None:
                ready, detail = await self.probe()
                last_probe_detail = detail
                if ready:
                    self.logger(
                        "Drawing Gateway tunnel started: "
                        f"{detail}"
                    )
                    return True, detail
            await asyncio.sleep(0.5)
        return False, f"启动超时：{last_probe_detail}"

    async def terminate_process(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            options: dict[str, Any] = {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "creationflags": subprocess.CREATE_NO_WINDOW,
            }
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    **options,
                )
                stdout, stderr = await asyncio.wait_for(
                    killer.communicate(),
                    timeout=10,
                )
                if killer.returncode != 0:
                    detail = clean_runtime_error(
                        stderr.decode(
                            "utf-8",
                            errors="replace",
                        )
                        or stdout.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )
                    self.logger(
                        "Drawing Gateway tunnel process tree stop "
                        f"failed: {detail}"
                    )
            except Exception as exc:
                self.logger(
                    "Drawing Gateway tunnel taskkill failed: "
                    f"{clean_runtime_error(exc)}"
                )
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def stop(self) -> None:
        self.stop_requested = True
        process = self.process
        if process is not None:
            await self.terminate_process(process)
        task = self.supervisor_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=3,
                )
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        elif task is not None:
            await asyncio.gather(task, return_exceptions=True)
        pending_logs = list(self.log_tasks)
        if pending_logs:
            _, pending = await asyncio.wait(
                pending_logs,
                timeout=2,
            )
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                await asyncio.gather(
                    *pending,
                    return_exceptions=True,
                )
        self.process = None
        self.supervisor_task = None
        self.settings = None
        self.external_forward_detail = ""
