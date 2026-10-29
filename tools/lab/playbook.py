"""Ansible side: inventory and playbook generation, ansible runners."""
from __future__ import annotations

import ipaddress
import os
import sys
from pathlib import Path

import yaml

from .common import ANSIBLE_DIR, GENERATED_HEADER, VENV_BIN, LabError, run
from .env import Env
from .stack import Stack

PREFLIGHT = {
    "name": "preflight: wait for the VMs (ssh + cloud-init)",
    "hosts": "all",
    "gather_facts": False,
    "tags": ["always"],
    "tasks": [
        {"name": "Wait for ssh", "ansible.builtin.wait_for_connection": {"timeout": 600}},
        {"name": "Wait for cloud-init to finish",
         "ansible.builtin.shell": "command -v cloud-init >/dev/null || exit 0; cloud-init status --wait",
         "become": True, "changed_when": False, "register": "_ci", "failed_when": "_ci.rc not in [0, 2]"},
    ],
}


def lb_range(net: ipaddress.IPv4Network) -> str:
    """Default load-balancer range: the top ~20% of the subnet (.200-.250 on a /24)."""
    hosts = list(net.hosts())
    return f"{hosts[int(len(hosts) * 0.785)]}-{hosts[max(len(hosts) - 5, 0)]}"


def lab_vars(env: Env, stack: Stack) -> dict:
    """Variables every component can rely on."""
    return {
        "lab_env": env.name,
        "lab_env_dir": str(env.dir),
        "lab_state_dir": str(env.state),
        "lab_kubeconfig": str(env.kubeconfig),
        "lab_components": stack.names(),
        "lab_capabilities": stack.capabilities(),
        "lab_network_cidr": str(env.network),
        "lab_network_gateway": env.gateway,
        "lab_lb_range": lb_range(env.network),
    }


def write_inventory(env: Env, stack: Stack, nodes: dict) -> None:
    """Defaults of every enabled component go to `all`, so components can read each
    other's settings (e.g. cni reads kubernetes_pod_cidr); user options override them."""
    vars_ = {"ansible_user": env.user, "ansible_ssh_private_key_file": str(env.ssh_priv), **lab_vars(env, stack)}
    for comp in stack.order:
        vars_.update(comp.defaults)
        vars_.update({f"{comp.name}_{k}": v for k, v in stack.options[comp.name].items()})
    vars_.update(env.cfg.get("vars") or {})

    children: dict[str, dict] = {}
    pool_groups = env.pool_groups()
    for host, node in sorted(nodes.items()):
        pool = node["pool"]
        children.setdefault(pool, {"hosts": {}})["hosts"][host] = {"ansible_host": node["ip"]}
        for group in pool_groups.get(pool, []):
            children.setdefault(group, {"hosts": {}})["hosts"][host] = None
    inv = {"all": {"vars": vars_, "children": children}}
    env.state.mkdir(parents=True, exist_ok=True)
    env.inventory.write_text(GENERATED_HEADER.format(src=env.file) +
                             yaml.safe_dump(inv, sort_keys=False, width=1000))


def write_playbook(env: Env, stack: Stack, only: list[str] | None = None) -> list[str]:
    """One play per component, in stack order. Env playbooks run last on full installs."""
    selected = [c for c in stack.order if not only or c.name in only]
    plays: list = [PREFLIGHT]
    for c in selected:
        play = {"name": f"{c.name}: {c.description}", "hosts": c.hosts, "become": c.become,
                "gather_facts": c.gather_facts, "tags": [c.name], "roles": [c.name]}
        if c.connection:
            play["connection"] = c.connection
        if c.environment:
            play["environment"] = c.environment
        plays.append(play)
    if not only:
        for pb in env.cfg.get("playbooks") or []:
            path = (env.dir / pb).resolve()
            if not path.is_file():
                raise LabError(f"playbooks: {path} not found")
            plays.append({"import_playbook": str(path)})
    env.playbook.write_text(GENERATED_HEADER.format(src=env.file) +
                            yaml.safe_dump(plays, sort_keys=False, width=1000))
    return [c.name for c in selected]


def ansible_env(env: Env) -> dict:
    return dict(
        os.environ,
        ANSIBLE_CONFIG=str(ANSIBLE_DIR / "ansible.cfg"),
        ANSIBLE_ROLES_PATH=":".join(str(d) for d in env.role_dirs()),
        ANSIBLE_COLLECTIONS_PATH=str(Path(sys.prefix) / "collections"),
    )


def ansible(env: Env, tool: str, *args) -> None:
    exe = VENV_BIN / tool
    run([exe if exe.exists() else tool, "-i", env.inventory, *args], env=ansible_env(env), cwd=env.dir)
