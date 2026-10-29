"""An environment: a directory with cluster.yml and the generated .state/."""
from __future__ import annotations

import ipaddress
from pathlib import Path

from .common import ENVS_DIR, LIBRARY_ROLES, LabError, load_yaml, suggest

TOP_KEYS = {"name", "infra", "components", "vars", "libraries", "playbooks"}
INFRA_KEYS = {"libvirt_uri", "network", "pool_path", "image", "user", "password_hash", "password_file", "ssh_password_auth",
              "ssh_key", "ip_start", "nodes", "cloud_init", "console"}
NODE_KEYS = {"count", "cpu", "memory", "disk", "ip_offset", "autostart", "extra_disks", "groups"}


def list_envs() -> list[Path]:
    if not ENVS_DIR.is_dir():
        return []
    return sorted(p for p in ENVS_DIR.iterdir() if (p / "cluster.yml").is_file())


def _unknown(keys, allowed, where: str) -> None:
    bad = sorted(set(keys) - allowed)
    if bad:
        raise LabError(f"{where}: unknown keys {bad}{suggest(bad[0], allowed)}")


class Env:
    def __init__(self, ref: str):
        path = Path(ref).expanduser()
        if "/" not in ref and not path.exists():
            path = ENVS_DIR / ref
        self.dir = path.resolve()
        self.file = self.dir / "cluster.yml"
        if not self.file.is_file():
            known = ", ".join(e.name for e in list_envs()) or "none"
            raise LabError(f"no environment '{ref}' ({self.file} not found). Known: {known}. "
                           f"Create one with: lab new {ref}")
        self.cfg = load_yaml(self.file, {})
        if not isinstance(self.cfg, dict):
            raise LabError(f"{self.file}: expected a mapping at top level")
        _unknown(self.cfg, TOP_KEYS, str(self.file))
        self.name = self.cfg.get("name") or self.dir.name
        self.state = self.dir / ".state"
        self.infra = self._load_infra()

    def _load_infra(self) -> dict:
        inf = dict(self.cfg.get("infra") or {})
        if "password" in inf:
            raise LabError(f"{self.file}: infra.password (plaintext) is not supported: use password_hash "
                           f"(openssl passwd -6), password_file, or the LAB_PASSWORD environment variable")
        _unknown(inf, INFRA_KEYS, f"{self.file}: infra")
        cidr = (inf.get("network") or {}).get("cidr")
        if not cidr:
            raise LabError(f"{self.file}: infra.network.cidr is required (e.g. 192.168.150.0/24)")
        try:
            self.network = ipaddress.ip_network(cidr)
        except ValueError as e:
            raise LabError(f"{self.file}: infra.network.cidr: {e}")
        nodes = inf.get("nodes") or {}
        if not nodes:
            raise LabError(f"{self.file}: infra.nodes must define at least one node pool")
        for pool in nodes:
            nodes[pool] = dict(nodes[pool] or {})
            _unknown(nodes[pool], NODE_KEYS, f"{self.file}: infra.nodes.{pool}")
        inf["nodes"] = nodes
        return inf

    # ── generated files ──────────────────────────────────────────────────────
    @property
    def tfvars(self) -> Path:
        return self.state / "tofu.tfvars.json"

    @property
    def tfstate(self) -> Path:
        return self.state / "terraform.tfstate"

    @property
    def inventory(self) -> Path:
        return self.state / "inventory.yml"

    @property
    def playbook(self) -> Path:
        return self.state / "site.yml"

    @property
    def kubeconfig(self) -> Path:
        return self.state / "kubeconfig"

    # ── settings with defaults ───────────────────────────────────────────────
    @property
    def ssh_pub(self) -> Path:
        return Path(self.infra.get("ssh_key", "~/.ssh/id_ed25519.pub")).expanduser()

    @property
    def ssh_priv(self) -> Path:
        return self.ssh_pub.with_suffix("") if self.ssh_pub.suffix == ".pub" else self.ssh_pub

    @property
    def user(self) -> str:
        return self.infra.get("user", "ubuntu")

    @property
    def uri(self) -> str:
        return self.infra.get("libvirt_uri", "qemu:///system")

    @property
    def gateway(self) -> str:
        return str(next(self.network.hosts()))

    def role_dirs(self) -> list[Path]:
        """Ansible roles_path: env roles, then extra libraries, then the labkit library."""
        extra = [(self.dir / p).expanduser().resolve() for p in self.cfg.get("libraries") or []]
        return [self.dir / "roles", *extra, LIBRARY_ROLES]

    def pool_groups(self) -> dict[str, list[str]]:
        return {pool: list(spec.get("groups") or []) for pool, spec in self.infra["nodes"].items()}

    def planned_ips(self) -> dict[str, list[str]]:
        """IPs per pool, computed like infra/main.tf does (pools in lexical order)."""
        start, seq, out = self.infra.get("ip_start", 10), 0, {}
        for pool in sorted(self.infra["nodes"]):
            spec = self.infra["nodes"][pool]
            count = spec.get("count", 1)
            first = spec["ip_offset"] if spec.get("ip_offset") is not None else start + seq
            out[pool] = [str(self.network.network_address + first + i) for i in range(count)]
            seq += count
        return out
