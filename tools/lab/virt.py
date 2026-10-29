"""libvirt / ssh helpers for VM lifecycle commands."""
from __future__ import annotations

import os
import socket

from .common import run
from .env import Env


def virsh(env: Env, *args: str, check: bool = False) -> str:
    out = run(["virsh", "-c", env.uri, *args], check=check, capture_output=True, text=True,
              env=dict(os.environ, LC_ALL="C"))  # C locale: stable state strings
    return out.stdout.strip()


def dom_state(env: Env, name: str) -> str:
    out = virsh(env, "domstate", name)
    return out.splitlines()[0] if out else "missing"


def net_active(env: Env, net: str) -> bool:
    for line in virsh(env, "net-info", net).splitlines():
        if line.startswith("Active:"):
            return line.split()[-1] == "yes"
    return False


def port_open(ip: str, port: int = 22) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=2):
            return True
    except OSError:
        return False


def ssh_cmd(env: Env, ip: str) -> list[str]:
    return ["ssh", "-i", str(env.ssh_priv), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", f"{env.user}@{ip}"]
