"""Read-only / scaffolding commands: envs, components, new, check."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

from ..common import ENVS_DIR, LIBRARY_ROLES, TEMPLATES_DIR, LabError, load_yaml, log, run, suggest
from ..components import Component, discover
from ..env import Env, list_envs
from ..playbook import lb_range
from ..stack import resolve


def cmd_envs(_args) -> None:
    envs = list_envs()
    if not envs:
        print(f"no environments in {ENVS_DIR} - create one with: lab new <name>")
    for p in envs:
        state = "created" if (p / ".state" / "inventory.yml").exists() else "-"
        print(f"{p.name:20} {state}")


def _print_options(c: Component) -> None:
    for var, spec in c.options.items():
        desc = spec.get("description", "")
        desc = " ".join(desc) if isinstance(desc, list) else desc
        choices = f" One of: {', '.join(map(str, spec['choices']))}." if "choices" in spec else ""
        print(f"    {c.short(var):30} {spec.get('type', 'str'):5} {desc}{choices}")
        default = c.defaults.get(var)
        if default not in (None, "", [], {}):
            d = default if isinstance(default, str) else json.dumps(default)
            print(f"    {'':36} default: {d if len(d) < 100 else d[:97] + '...'}")


def cmd_components(args) -> None:
    lib = discover(Env(args.env).role_dirs() if args.env else [LIBRARY_ROLES])
    for name in args.names or sorted(lib):
        if name not in lib:
            raise LabError(f"unknown component '{name}'{suggest(name, lib)}")
        c = lib[name]
        rel = [f"{k}: {', '.join(v)}" for k, v in
               (("requires", c.requires), ("provides", c.provides), ("after", c.after)) if v]
        print(f"\033[1m{c.name}\033[0m - {c.description}")
        print(f"    runs on: {c.hosts}" + (f"   ({'; '.join(rel)})" if rel else ""))
        if args.names or args.verbose:
            _print_options(c)
            print()


def _suggest_cidr() -> str:
    """First 192.168.X.0/24 not routed on this host nor used by another env."""
    used = []
    try:
        for r in json.loads(run(["ip", "-j", "-4", "route"], capture_output=True, text=True).stdout):
            if r.get("dst") not in (None, "default"):
                used.append(ipaddress.ip_network(r["dst"], strict=False))
    except (LabError, ValueError):
        pass
    for p in list_envs():
        try:
            used.append(ipaddress.ip_network(load_yaml(p / "cluster.yml", {})["infra"]["network"]["cidr"]))
        except (KeyError, TypeError, ValueError):
            pass
    for third in range(150, 250):
        net = ipaddress.ip_network(f"192.168.{third}.0/24")
        if not any(net.overlaps(u) for u in used):
            return str(net)
    return "192.168.150.0/24"


def cmd_new(args) -> None:
    dest = (Path(args.path).expanduser() if args.path else ENVS_DIR / args.name).resolve()
    if (dest / "cluster.yml").exists():
        raise LabError(f"{dest / 'cluster.yml'} already exists")
    key = Path("~/.ssh/id_ed25519.pub")
    text = ((TEMPLATES_DIR / "cluster.yml").read_text()
            .replace("__NAME__", args.name)
            .replace("__CIDR__", _suggest_cidr())
            .replace("__SSH_KEY__", str(key)))
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "cluster.yml").write_text(text)
    ref = args.name if not args.path else str(dest)
    log(f"created {dest / 'cluster.yml'}")
    print(f"Edit it, then:  lab check {ref}  &&  lab up {ref}")


def cmd_check(args) -> None:
    env = Env(args.env)
    stack = resolve(env)
    print(f"\033[1m{env.name}\033[0m  {env.file}")
    print(f"  network {env.network}  host {env.gateway}  load-balancer range {lb_range(env.network)}")
    for pool, ips in env.planned_ips().items():
        s = env.infra["nodes"][pool]
        ip_txt = ips[0] + (f" .. {ips[-1]}" if len(ips) > 1 else "") if ips else "-"
        print(f"  pool {pool:10} x{len(ips)}  {s.get('cpu', 2)} vCPU  {s.get('memory', 2048)} MiB  "
              f"{s.get('disk', 20)} GiB  {ip_txt:32} groups: {', '.join(s.get('groups') or []) or '-'}")
    print("  components, in install order:")
    for i, c in enumerate(stack.order, 1):
        opts = ", ".join(f"{k}={v}" for k, v in stack.options[c.name].items() if not isinstance(v, (dict, list)))
        print(f"   {i}. {c.name:14} on {c.hosts:30} {opts}")
    print("\033[32mconfiguration OK\033[0m")
