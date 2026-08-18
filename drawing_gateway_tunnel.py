from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent
SSH_ENVIRONMENT_KEYS = (
    "DRAWING_GATEWAY_BASE_URL",
    "DRAWING_GATEWAY_SSH_HOST",
    "DRAWING_GATEWAY_SSH_PORT",
    "DRAWING_GATEWAY_SSH_USER",
    "DRAWING_GATEWAY_SSH_KEY_PATH",
    "DRAWING_GATEWAY_SSH_ADDRESS_FAMILY",
    "DRAWING_GATEWAY_SSH_REMOTE_HOST",
    "DRAWING_GATEWAY_SSH_REMOTE_PORT",
    "DRAWING_GATEWAY_SSH_KNOWN_HOSTS_PATH",
    "DRAWING_GATEWAY_SSH_BIN",
    "DRAWING_GATEWAY_SSH_CONNECT_TIMEOUT_SECONDS",
)
PASSTHROUGH_ENVIRONMENT_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "USERNAME",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "PROGRAMDATA",
)
HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:%-]+$")
USER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class DrawingGatewayTunnelConfig:
    ssh_executable: Path
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_key_path: Path
    address_family: str
    local_port: int
    remote_host: str
    remote_port: int
    known_hosts_path: Path | None
    connect_timeout_seconds: int


class TunnelConfigurationError(RuntimeError):
    pass


def clean_error(value: object, limit: int = 400) -> str:
    text = " ".join(str(value).replace("\x00", "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


def environment_file_path(explicit: str = "") -> Path:
    configured = explicit.strip() or os.getenv(
        "DRAWING_GATEWAY_ENV_FILE", ""
    ).strip()
    if not configured:
        return ROOT / ".env"
    path = Path(os.path.expandvars(configured)).expanduser()
    return path if path.is_absolute() else ROOT / path


def read_tunnel_environment(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if env_file.is_file():
        file_values = dotenv_values(env_file)
        for key in SSH_ENVIRONMENT_KEYS:
            value = file_values.get(key)
            if value is not None:
                values[key] = str(value)
    for key in SSH_ENVIRONMENT_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def required_value(values: Mapping[str, str], key: str) -> str:
    value = str(values.get(key) or "").strip()
    if not value:
        raise TunnelConfigurationError(f"缺少 {key}。")
    return value


def port_value(
    values: Mapping[str, str],
    key: str,
    default: int | None = None,
) -> int:
    raw = str(values.get(key) or "").strip()
    if not raw:
        if default is None:
            raise TunnelConfigurationError(f"缺少 {key}。")
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise TunnelConfigurationError(f"{key} 必须是整数。") from exc
    if not 1 <= value <= 65535:
        raise TunnelConfigurationError(f"{key} 必须在 1 到 65535 之间。")
    return value


def duration_seconds_value(
    values: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    raw = str(values.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise TunnelConfigurationError(f"{key} 必须是整数。") from exc
    if not 1 <= value <= 600:
        raise TunnelConfigurationError(f"{key} 必须在 1 到 600 之间。")
    return value


def safe_host(value: str, key: str) -> str:
    host = value.strip()
    if not host or host.startswith("-") or not HOST_PATTERN.fullmatch(host):
        raise TunnelConfigurationError(f"{key} 格式无效。")
    return host


def safe_user(value: str) -> str:
    user = value.strip()
    if not USER_PATTERN.fullmatch(user):
        raise TunnelConfigurationError(
            "DRAWING_GATEWAY_SSH_USER 格式无效。"
        )
    return user


def resolved_file(
    value: str,
    key: str,
    *,
    required: bool,
) -> Path | None:
    raw = value.strip()
    if not raw:
        if required:
            raise TunnelConfigurationError(f"缺少 {key}。")
        return None
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise TunnelConfigurationError(f"{key} 指向的文件不存在。")
    return path


def ssh_executable(value: str) -> Path:
    raw = value.strip() or "ssh"
    path = Path(os.path.expandvars(raw)).expanduser()
    if path.is_file():
        return path.resolve()
    located = shutil.which(raw)
    if not located:
        raise TunnelConfigurationError(
            "找不到 OpenSSH 客户端，请检查 DRAWING_GATEWAY_SSH_BIN。"
        )
    return Path(located).resolve()


def local_port_from_base_url(value: str) -> int:
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise TunnelConfigurationError(
            "DRAWING_GATEWAY_BASE_URL 格式无效。"
        ) from exc
    if (
        parsed.scheme.casefold() != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port is None
    ):
        raise TunnelConfigurationError(
            "SSH 隧道模式要求 DRAWING_GATEWAY_BASE_URL 使用 http://127.0.0.1:<端口>。"
        )
    return port


def tunnel_config(
    values: Mapping[str, str],
) -> DrawingGatewayTunnelConfig:
    family = str(
        values.get("DRAWING_GATEWAY_SSH_ADDRESS_FAMILY") or "inet6"
    ).strip().casefold()
    if family not in {"auto", "inet", "inet6"}:
        raise TunnelConfigurationError(
            "DRAWING_GATEWAY_SSH_ADDRESS_FAMILY 只允许 auto、inet 或 inet6。"
        )
    key_path = resolved_file(
        required_value(values, "DRAWING_GATEWAY_SSH_KEY_PATH"),
        "DRAWING_GATEWAY_SSH_KEY_PATH",
        required=True,
    )
    if key_path is None:
        raise TunnelConfigurationError(
            "DRAWING_GATEWAY_SSH_KEY_PATH 无效。"
        )
    known_hosts_path = resolved_file(
        str(values.get("DRAWING_GATEWAY_SSH_KNOWN_HOSTS_PATH") or ""),
        "DRAWING_GATEWAY_SSH_KNOWN_HOSTS_PATH",
        required=False,
    )
    return DrawingGatewayTunnelConfig(
        ssh_executable=ssh_executable(
            str(values.get("DRAWING_GATEWAY_SSH_BIN") or "ssh")
        ),
        ssh_host=safe_host(
            required_value(values, "DRAWING_GATEWAY_SSH_HOST"),
            "DRAWING_GATEWAY_SSH_HOST",
        ),
        ssh_port=port_value(
            values,
            "DRAWING_GATEWAY_SSH_PORT",
            22,
        ),
        ssh_user=safe_user(
            required_value(values, "DRAWING_GATEWAY_SSH_USER")
        ),
        ssh_key_path=key_path,
        address_family=family,
        local_port=local_port_from_base_url(
            required_value(values, "DRAWING_GATEWAY_BASE_URL")
        ),
        remote_host=safe_host(
            str(
                values.get("DRAWING_GATEWAY_SSH_REMOTE_HOST")
                or "127.0.0.1"
            ),
            "DRAWING_GATEWAY_SSH_REMOTE_HOST",
        ),
        remote_port=port_value(
            values,
            "DRAWING_GATEWAY_SSH_REMOTE_PORT",
            8890,
        ),
        known_hosts_path=known_hosts_path,
        connect_timeout_seconds=duration_seconds_value(
            values,
            "DRAWING_GATEWAY_SSH_CONNECT_TIMEOUT_SECONDS",
            15,
        ),
    )


def forward_host(value: str) -> str:
    if ":" in value and not value.startswith("["):
        return f"[{value}]"
    return value


def ssh_command(config: DrawingGatewayTunnelConfig) -> list[str]:
    command = [str(config.ssh_executable)]
    if config.address_family == "inet":
        command.append("-4")
    elif config.address_family == "inet6":
        command.append("-6")
    command.extend(
        [
            "-N",
            "-T",
            "-p",
            str(config.ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            f"ConnectTimeout={config.connect_timeout_seconds}",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=yes",
        ]
    )
    if config.known_hosts_path is not None:
        command.extend(
            [
                "-o",
                f"UserKnownHostsFile={config.known_hosts_path}",
            ]
        )
    command.extend(
        [
            "-i",
            str(config.ssh_key_path),
            "-L",
            (
                f"127.0.0.1:{config.local_port}:"
                f"{forward_host(config.remote_host)}:{config.remote_port}"
            ),
            f"{config.ssh_user}@{config.ssh_host}",
        ]
    )
    return command


def ssh_process_environment() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in PASSTHROUGH_ENVIRONMENT_KEYS
        if key in os.environ
    }


def launch_ssh(
    command: list[str],
    environment: Mapping[str, str],
) -> int:
    child_environment = dict(environment)
    if os.name == "nt":
        return subprocess.call(command, env=child_environment)
    os.execve(command[0], command, child_environment)
    return 0


def safe_summary(config: DrawingGatewayTunnelConfig) -> dict[str, object]:
    return {
        "ok": True,
        "target": f"{config.ssh_user}@{config.ssh_host}",
        "ssh_port": config.ssh_port,
        "address_family": config.address_family,
        "local_forward": (
            f"127.0.0.1:{config.local_port} -> "
            f"{config.remote_host}:{config.remote_port}"
        ),
        "key_file": config.ssh_key_path.name,
        "known_hosts": (
            config.known_hosts_path.name
            if config.known_hosts_path is not None
            else "OpenSSH default"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--env-file", default="")
    args = parser.parse_args()
    try:
        env_file = environment_file_path(args.env_file)
        values = read_tunnel_environment(env_file)
        config = tunnel_config(values)
    except TunnelConfigurationError as exc:
        print(
            json.dumps(
                {"ok": False, "error": clean_error(exc)},
                ensure_ascii=False,
            ),
            file=os.sys.stderr,
        )
        return 2
    if args.check:
        print(json.dumps(safe_summary(config), ensure_ascii=False))
        return 0
    command = ssh_command(config)
    try:
        return launch_ssh(command, ssh_process_environment())
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "无法启动 OpenSSH 客户端："
                        f"{clean_error(exc)}"
                    ),
                },
                ensure_ascii=False,
            ),
            file=os.sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
