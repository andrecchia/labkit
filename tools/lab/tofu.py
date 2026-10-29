"""OpenTofu side: base image cache, tfvars generation, tofu wrapper and outputs."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.parse
from pathlib import Path

from .common import CACHE_DIR, DATA_DIR, INFRA_DIR, LabError, log, need, run
from .env import Env

DEFAULT_IMAGE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
VAR_FILE_CMDS = {"plan", "apply", "destroy", "refresh", "import", "console"}


def ensure_image(env: Env) -> Path:
    """infra.image: {url: ...} (downloaded once into ~/.cache/labkit/images) or {path: ...}."""
    img = env.infra.get("image") or {"url": DEFAULT_IMAGE}
    if isinstance(img, str):
        img = {"url": img} if img.startswith(("http://", "https://")) else {"path": img}
    if img.get("path"):
        path = Path(img["path"]).expanduser().resolve()
        if not path.is_file():
            raise LabError(f"infra.image.path: {path} does not exist")
        return path
    url = img["url"]
    dest = CACHE_DIR / "images" / Path(urllib.parse.urlparse(url).path).name
    if not dest.exists():
        need("curl")
        dest.parent.mkdir(parents=True, exist_ok=True)
        log(f"downloading {url}")
        part = dest.with_name(dest.name + ".part")
        run(["curl", "-fL", "--progress-bar", "-C", "-", "-o", part, url])
        part.rename(dest)
    return dest


def password_hash(env: Env) -> str | None:
    """Console password, never in plaintext in cluster.yml: infra.password_hash (crypt(3), used as is),
    else infra.password_file or $LAB_PASSWORD hashed with SHA-512 crypt and a salt derived from
    env+password: stable across applies (a random salt would rebuild the cloud-init disk, and so the VM)."""
    if env.infra.get("password_hash"):
        return str(env.infra["password_hash"])
    if env.infra.get("password_file"):
        path = (env.dir / env.infra["password_file"]).expanduser()
        if not path.is_file():
            raise LabError(f"infra.password_file: {path} does not exist")
        pw = path.read_text().strip()
    else:
        pw = os.environ.get("LAB_PASSWORD")
    if not pw:
        return None
    salt = hashlib.sha256(f"{env.name}:{pw}".encode()).hexdigest()[:16]
    out = run(["openssl", "passwd", "-6", "-salt", salt, "-stdin"], input=str(pw), capture_output=True, text=True)
    return out.stdout.strip()


def write_tfvars(env: Env) -> None:
    inf = env.infra
    if not env.ssh_pub.is_file():
        raise LabError(f"ssh public key {env.ssh_pub} not found. Create it with:\n"
                       f"  ssh-keygen -t ed25519 -N '' -f {env.ssh_priv}\nor set infra.ssh_key")
    net = inf.get("network") or {}
    ci = inf.get("cloud_init") or {}
    console = inf.get("console") or {}
    nodes = {}
    for pool, spec in inf["nodes"].items():
        nodes[pool] = {k: v for k, v in spec.items() if k not in ("groups", "disk")}
        if "disk" in spec:
            nodes[pool]["disk_gb"] = spec["disk"]
    tfvars = {
        "name": env.name,
        "libvirt_uri": env.uri,
        "pool_path": str(Path(inf.get("pool_path", DATA_DIR / "pools" / env.name)).expanduser()),
        "base_image": str(ensure_image(env)),
        "network_cidr": str(env.network),
        "network_mode": net.get("mode", "nat"),
        "dns_domain": net.get("domain"),
        "ip_start": inf.get("ip_start", 10),
        "nodes": nodes,
        "user": env.user,
        "password_hash": password_hash(env),
        "ssh_password_auth": bool(inf.get("ssh_password_auth", False)),
        "ssh_authorized_keys": [env.ssh_pub.read_text().strip(), *(ci.get("ssh_authorized_keys") or [])],
        "packages": ci.get("packages") or [],
        "runcmd": ci.get("runcmd") or [],
        "cloud_init_extra": ci.get("extra") or {},
        "graphics_type": console.get("graphics", "vnc"),
        "video_type": console.get("video", "vga"),
    }
    env.state.mkdir(parents=True, exist_ok=True)
    env.tfvars.write_text(json.dumps(tfvars, indent=2) + "\n")
    env.tfvars.chmod(0o600)


def tofu(env: Env, *args: str, capture: bool = False) -> str:
    """Run tofu in infra/ with this env's data dir and state file."""
    need("tofu")
    cache = CACHE_DIR / "tofu-plugins"
    cache.mkdir(parents=True, exist_ok=True)
    tenv = dict(os.environ, TF_DATA_DIR=str(env.state / ".terraform"), TF_IN_AUTOMATION="1")
    tenv.setdefault("TF_PLUGIN_CACHE_DIR", str(cache))
    env.state.mkdir(parents=True, exist_ok=True)
    if not (env.state / ".terraform" / "terraform.tfstate").exists():
        log("tofu init")
        run(["tofu", f"-chdir={INFRA_DIR}", "init", "-input=false", f"-backend-config=path={env.tfstate}"],
            env=tenv, stdout=subprocess.DEVNULL)
    cmd = ["tofu", f"-chdir={INFRA_DIR}", *args]
    if args and args[0] in VAR_FILE_CMDS:
        cmd.append(f"-var-file={env.tfvars}")
    if capture:
        return run(cmd, env=tenv, capture_output=True, text=True).stdout
    run(cmd, env=tenv)
    return ""


def outputs(env: Env) -> dict:
    """tofu outputs as plain values: {'nodes': {...}, 'network': {...}}."""
    if not env.tfstate.exists():
        raise LabError(f"'{env.name}' has no VMs yet: run `lab create {env.name}` (or `lab up`)")
    data = json.loads(tofu(env, "output", "-json", capture=True) or "{}")
    if "nodes" not in data:
        raise LabError(f"'{env.name}' has no VMs yet: run `lab create {env.name}` (or `lab up`)")
    return {k: v["value"] for k, v in data.items()}
