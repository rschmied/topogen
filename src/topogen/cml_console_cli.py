# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# - Called by: cml_ci_finalize.py when runner pyATS is unavailable
# - Reads from: CML terminal server SSH, node console ports
# - Writes to: device running-config via console CLI
# - Calls into: paramiko SSH
"""Push IOS config through the CML console terminal server (no local pyATS)."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import yaml

from virl2_client.exceptions import PyatsNotInstalled

_CONSOLE_PROMPT = re.compile(r"[>#]\s*$")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _cml_credentials() -> tuple[str, str]:
    user = (
        os.environ.get("TF_VAR_username")
        or os.environ.get("VIRL2_USERNAME")
        or os.environ.get("CML_USERNAME")
        or "admin"
    )
    password = (
        os.environ.get("TF_VAR_password")
        or os.environ.get("VIRL2_PASSWORD")
        or os.environ.get("CML_PASSWORD")
        or ""
    )
    return user, password


def _ios_credentials() -> tuple[str, str, str]:
    user = os.environ.get("IOSXE_USERNAME", "cisco")
    password = os.environ.get("IOSXE_PASSWORD", "cisco")
    enable = os.environ.get("IOSXE_ENABLE_PASSWORD", password)
    return user, password, enable


def _read_channel(channel, idle: float = 0.35) -> str:
    time.sleep(idle)
    chunks: list[bytes] = []
    while channel.recv_ready():
        chunks.append(channel.recv(65535))
        time.sleep(0.05)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _console_connection(testbed: dict[str, Any], node_label: str) -> tuple[dict[str, Any], str]:
    devices = testbed.get("devices") or {}
    terminal = devices.get("terminal_server")
    node = devices.get(node_label)
    if not terminal or not node:
        raise KeyError(f"testbed missing terminal_server or {node_label}")
    ts_conn = (terminal.get("connections") or {}).get("cli")
    node_conn = (node.get("connections") or {}).get("a")
    if not ts_conn or not node_conn:
        raise KeyError(f"testbed missing console connection for {node_label}")
    command = str(node_conn.get("command") or "").strip()
    if not command:
        raise KeyError(f"empty console open command for {node_label}")
    return ts_conn, command


def _last_clean_line(text: str) -> str:
    lines = [_ANSI_ESCAPE.sub("", line).strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _has_console_prompt(text: str) -> bool:
    line = _last_clean_line(text)
    return bool(line and _CONSOLE_PROMPT.search(line))


def _wake_console(channel) -> str:
    """Send RETURN until IOS presents an exec/config prompt."""
    buf = ""
    for attempt in range(24):
        if _has_console_prompt(buf):
            return buf
        tail = buf.lower()
        if "press return" in tail or "return to get started" in tail:
            _send_line(channel, "", pause=0.25)
        elif "username:" in tail or "login:" in tail:
            user, password, _ = _ios_credentials()
            _send_line(channel, user, pause=0.35)
            buf += _read_channel(channel)
            if "password" in buf.lower():
                _send_line(channel, password, pause=0.35)
        else:
            _send_line(channel, "", pause=0.25)
        buf += _read_channel(channel, idle=0.35)
    if not _has_console_prompt(buf):
        raise TimeoutError("IOS console prompt not seen after wake")
    return buf


def _open_console_session(ts_conn: dict[str, Any], open_command: str):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko required for CML console CLI") from exc

    user, password = _cml_credentials()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        str(ts_conn["ip"]),
        port=int(ts_conn.get("port") or 22),
        username=user,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    channel = client.invoke_shell()
    _read_channel(channel, idle=0.8)
    channel.send(open_command + "\n")
    buf = ""
    deadline = time.time() + 60
    while time.time() < deadline:
        buf += _read_channel(channel, idle=0.45)
        if "connected to cml terminalserver" in buf.lower():
            break
    _wake_console(channel)
    return client, channel


def _send_line(channel, line: str, pause: float = 0.2, *, eol: str = "\r") -> None:
    channel.send(line + eol)
    time.sleep(pause)


def _ssh_push_config(host: str, config_block: str) -> None:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko required for SSH fallback") from exc

    _, password, enable_password = _ios_credentials()
    user = os.environ.get("IOSXE_USERNAME", "cisco")
    bracketed = host
    if ":" in host and not host.startswith("["):
        bracketed = f"[{host}]"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        bracketed,
        username=user,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    try:
        shell = client.invoke_shell()
        time.sleep(0.5)
        shell.send("enable\n")
        time.sleep(0.3)
        shell.send(f"{enable_password}\n")
        time.sleep(0.3)
        shell.send("configure terminal\n")
        time.sleep(0.3)
        for line in config_block.splitlines():
            shell.send(line + "\n")
            time.sleep(0.15)
        shell.send("end\n")
        time.sleep(0.3)
        shell.send("write memory\n")
        time.sleep(0.3)
        shell.send("\n")
        time.sleep(2.0)
    finally:
        client.close()


def _close_console(channel, client) -> None:
    try:
        channel.send("\x1d")
        time.sleep(0.2)
        channel.send("close\n")
        time.sleep(0.3)
        _read_channel(channel, idle=0.2)
        channel.close()
    finally:
        client.close()


def exec_commands_via_cml_console(lab, node_label: str, *commands: str) -> str:
    """Run exec-mode show commands on a BOOTED router via CML console server."""
    testbed = yaml.safe_load(lab.get_pyats_testbed()) or {}
    ts_conn, open_command = _console_connection(testbed, node_label)
    _, _, enable_password = _ios_credentials()
    client, channel = _open_console_session(ts_conn, open_command)
    chunks: list[str] = []
    try:
        _send_line(channel, "enable", pause=0.3)
        out = _read_channel(channel)
        if "assword" in out.lower():
            _send_line(channel, enable_password, pause=0.3)
            _read_channel(channel)
        for command in commands:
            _send_line(channel, command, pause=0.35)
            chunks.append(_read_channel(channel, idle=0.5))
    finally:
        _close_console(channel, client)
    return "\n".join(chunks)


def push_config_via_cml_console(lab, node_label: str, config_block: str) -> None:
    """Configure a BOOTED router through CML's SSH console server."""
    testbed = yaml.safe_load(lab.get_pyats_testbed()) or {}
    ts_conn, open_command = _console_connection(testbed, node_label)
    ios_user, ios_password, enable_password = _ios_credentials()
    client, channel = _open_console_session(ts_conn, open_command)
    try:
        _send_line(channel, "enable", pause=0.3)
        out = _read_channel(channel)
        if "assword" in out.lower():
            _send_line(channel, enable_password, pause=0.3)
            _read_channel(channel)
        _send_line(channel, "configure terminal", pause=0.4)
        _read_channel(channel)
        for line in config_block.splitlines():
            if not line.strip():
                continue
            _send_line(channel, line, pause=0.18)
            _read_channel(channel, idle=0.12)
        _send_line(channel, "end", pause=0.35)
        _read_channel(channel)
        _send_line(channel, "write memory", pause=0.35)
        _read_channel(channel, idle=1.5)
    finally:
        _close_console(channel, client)


def push_router_config(
    lab,
    node,
    config_block: str,
    mgmt_ipv6: str | None,
) -> str:
    """Push config via pyATS, CML console, or SSH to mgmt IPv6. Returns transport label."""
    label = str(getattr(node, "label", ""))
    try:
        node.run_pyats_config_command(config_block)
        node.run_pyats_command("write memory", config=False)
        return "pyats"
    except PyatsNotInstalled:
        push_config_via_cml_console(lab, label, config_block)
        return "cml-console"
    except Exception as pyats_exc:
        try:
            push_config_via_cml_console(lab, label, config_block)
            return "cml-console"
        except Exception:
            if mgmt_ipv6 is None:
                raise pyats_exc
            _ssh_push_config(mgmt_ipv6, config_block)
            return "ssh-mgmt"
