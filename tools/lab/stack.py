"""Resolve the `components:` section of cluster.yml into an ordered, validated stack."""
from __future__ import annotations

from dataclasses import dataclass

from .common import LabError, suggest
from .components import Component, discover
from .env import Env


@dataclass
class Stack:
    order: list[Component]        # install order
    options: dict[str, dict]      # user options per enabled component (short names)
    library: dict[str, Component]  # every component available to this env

    def names(self) -> list[str]:
        return [c.name for c in self.order]

    def capabilities(self) -> list[str]:
        return sorted({cap for c in self.order for cap in c.capabilities})


def _enabled(env: Env, library: dict[str, Component]) -> dict[str, dict]:
    raw = env.cfg.get("components") or {}
    if isinstance(raw, list):  # a plain list of names is fine too
        raw = {n: {} for n in raw}
    if not isinstance(raw, dict):
        raise LabError(f"{env.file}: 'components' must be a mapping name -> options")
    enabled: dict[str, dict] = {}
    for name, opts in raw.items():
        if opts is False or (isinstance(opts, dict) and opts.get("enabled") is False):
            continue
        opts = {} if opts in (None, True) else opts
        if not isinstance(opts, dict):
            raise LabError(f"components.{name}: expected a mapping of options, got {opts!r}")
        if name not in library:
            raise LabError(f"components: unknown component '{name}'{suggest(name, library)}. "
                           f"Available: {', '.join(sorted(library))}")
        comp = library[name]
        where = f"components.{name}"
        enabled[name] = {k: comp.check_option(k, v, where) for k, v in opts.items() if k != "enabled"}
        for var, spec in comp.options.items():
            if spec.get("required") and comp.short(var) not in opts and var not in comp.defaults:
                raise LabError(f"{where}: option '{comp.short(var)}' is required")
    return enabled


def _check_relations(enabled: dict, library: dict[str, Component]) -> dict[str, list[str]]:
    providers: dict[str, list[str]] = {}
    for name in enabled:
        for cap in library[name].capabilities:
            providers.setdefault(cap, []).append(name)
    for cap, names in providers.items():
        if len(names) > 1:
            raise LabError(f"components {' and '.join(names)} both provide '{cap}': enable only one")
    for name in enabled:
        comp = library[name]
        for req in comp.requires:
            if req not in providers:
                who = sorted(n for n, c in library.items() if req in c.capabilities)
                raise LabError(f"component '{name}' requires '{req}', which is not enabled. "
                               f"Add one of: {', '.join(who) or '(no component provides it)'}")
        for con in comp.conflicts:
            if con in providers:
                raise LabError(f"component '{name}' conflicts with '{providers[con][0]}'")
    return providers


def _order(enabled: dict, library: dict[str, Component], providers: dict) -> list[str]:
    """Dependencies first; otherwise keep the order written in cluster.yml (stable Kahn)."""
    deps = {n: {p for cap in library[n].requires + library[n].after for p in providers.get(cap, [])} - {n}
            for n in enabled}
    order, pending = [], list(enabled)
    while pending:
        ready = [n for n in pending if deps[n] <= set(order)]
        if not ready:
            raise LabError(f"dependency cycle between components: {', '.join(pending)}")
        order.append(ready[0])
        pending.remove(ready[0])
    return order


def resolve(env: Env) -> Stack:
    library = discover(env.role_dirs())
    enabled = _enabled(env, library)
    providers = _check_relations(enabled, library)
    order = _order(enabled, library, providers)

    groups = set(env.infra["nodes"]) | {g for gs in env.pool_groups().values() for g in gs}
    for name in order:
        missing = [g for g in library[name].requires_groups if g not in groups]
        if missing:
            raise LabError(f"component '{name}' runs on group(s) {missing}, but no node pool declares them. "
                           f"Add `groups: [{missing[0]}]` to a pool in infra.nodes")
    return Stack(order=[library[n] for n in order], options=enabled, library=library)
