"""Library components: Ansible roles that carry meta/component.yml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .common import LabError, load_yaml, suggest

META_KEYS = {"description", "hosts", "become", "gather_facts", "connection", "environment",
             "requires", "after", "provides", "conflicts", "requires_groups"}
PY_TYPES = {"str": (str,), "path": (str,), "int": (int,), "float": (int, float), "bool": (bool,),
            "list": (list,), "dict": (dict,)}


@dataclass
class Component:
    name: str
    path: Path
    description: str = ""
    hosts: str = "all"                                   # play `hosts:` pattern
    become: bool = True
    gather_facts: bool = True
    connection: str | None = None
    environment: dict = field(default_factory=dict)
    requires: list = field(default_factory=list)          # capabilities that must be enabled
    after: list = field(default_factory=list)             # ordering only, when enabled
    provides: list = field(default_factory=list)          # capabilities besides its own name
    conflicts: list = field(default_factory=list)
    requires_groups: list = field(default_factory=list)   # inventory groups that must exist
    options: dict = field(default_factory=dict)           # meta/argument_specs.yml (main)
    defaults: dict = field(default_factory=dict)          # defaults/main.yml

    @property
    def capabilities(self) -> set:
        return {self.name, *self.provides}

    def short(self, var: str) -> str:
        """kubernetes_pod_cidr -> pod_cidr"""
        return var[len(self.name) + 1:] if var.startswith(self.name + "_") else var

    def check_option(self, key: str, value, where: str):
        """Validate one user option against argument_specs; returns the (coerced) value."""
        var = f"{self.name}_{key}"
        shorts = [self.short(v) for v in self.options]
        if self.options and var not in self.options:
            raise LabError(f"{where}: unknown option '{key}'{suggest(key, shorts)}\n"
                           f"  valid options: {', '.join(sorted(shorts))}")
        spec = self.options.get(var) or {}
        typ = spec.get("type", "str")
        if typ == "str" and isinstance(value, float):
            raise LabError(f"{where}: '{key}' was parsed as the number {value}: quote it, e.g. {key}: \"1.36\"")
        if typ == "str" and isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        if typ in PY_TYPES and value is not None:
            if not isinstance(value, PY_TYPES[typ]) or (typ == "int" and isinstance(value, bool)):
                raise LabError(f"{where}: option '{key}' must be a {typ}, got {type(value).__name__}")
        if "choices" in spec and value not in spec["choices"]:
            raise LabError(f"{where}: option '{key}' must be one of {spec['choices']}, got '{value}'")
        return value


def load_component(role: Path) -> Component:
    meta_file = role / "meta" / "component.yml"
    meta = load_yaml(meta_file, {})
    bad = sorted(set(meta) - META_KEYS)
    if bad:
        raise LabError(f"{meta_file}: unknown keys {bad}{suggest(bad[0], META_KEYS)}")
    specs = load_yaml(role / "meta" / "argument_specs.yml", {}).get("argument_specs") or {}
    return Component(
        name=role.name,
        path=role,
        options=(specs.get("main") or {}).get("options") or {},
        defaults=load_yaml(role / "defaults" / "main.yml", {}),
        **meta,
    )


def discover(role_dirs: list[Path]) -> dict[str, Component]:
    """All components found in role_dirs. Earlier dirs win, like Ansible's roles_path."""
    comps: dict[str, Component] = {}
    for rdir in role_dirs:
        if not rdir.is_dir():
            continue
        for role in sorted(rdir.iterdir()):
            if role.name not in comps and (role / "meta" / "component.yml").is_file():
                comps[role.name] = load_component(role)
    return comps
