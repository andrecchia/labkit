"""VM lifecycle commands: create, destroy, start, stop, status, ssh, tofu."""
from __future__ import annotations

import os
import shutil
import time

from ..common import LabError, log, need, run, warn
from ..env import Env
from ..playbook import write_inventory
from ..stack import resolve
from ..tofu import outputs, tofu, write_tfvars
from ..virt import dom_state, net_active, port_open, ssh_cmd, virsh


def cmd_create(args) -> None:
    env = Env(args.env)
    need("tofu", "virsh", "openssl")
    stack = resolve(env)  # fail on a bad config before creating anything
    write_tfvars(env)
    tofu(env, "apply", "-input=false", *([] if args.confirm else ["-auto-approve"]))
    write_inventory(env, stack, outputs(env)["nodes"])
    log(f"inventory: {env.inventory}")


def cmd_destroy(args) -> None:
    env = Env(args.env)
    if not env.tfstate.exists():
        log("nothing to destroy")
        return
    if not args.yes:
        answer = input(f"Destroy ALL VMs, disks, network and pool of '{env.name}'? Type the name to confirm: ")
        if answer.strip() != env.name:
            raise LabError("aborted")
    write_tfvars(env)
    tofu(env, "destroy", "-input=false", "-auto-approve")
    for f in (env.inventory, env.playbook, env.kubeconfig):
        f.unlink(missing_ok=True)


def cmd_stop(args) -> None:
    env = Env(args.env)
    nodes = outputs(env)["nodes"]
    for name in nodes:
        state = dom_state(env, name)
        if state == "paused":
            virsh(env, "resume", name)
            state = "running"
        if state == "running":
            log(f"shutting down {name}")
            virsh(env, "shutdown", name)
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if all(dom_state(env, n) in ("shut off", "missing") for n in nodes):
            log(f"all VMs are off. Bring them back with: lab start {env.name}")
            return
        time.sleep(2)
    raise LabError(f"some VMs are still running; force them off with: virsh -c {env.uri} destroy <name>")


def cmd_start(args) -> None:
    env = Env(args.env)
    out = outputs(env)
    if not net_active(env, out["network"]["name"]):
        virsh(env, "net-start", out["network"]["name"], check=True)
    for name in out["nodes"]:
        state = dom_state(env, name)
        if state == "shut off":
            log(f"starting {name}")
            virsh(env, "start", name, check=True)
        elif state == "paused":
            warn(f"{name} was paused (often the host disk is full): resuming")
            virsh(env, "resume", name, check=True)
    log("waiting for ssh")
    pending, deadline = dict(out["nodes"]), time.time() + 300
    while pending and time.time() < deadline:
        pending = {n: v for n, v in pending.items() if not port_open(v["ip"])}
        time.sleep(2)
    if pending:
        raise LabError(f"no ssh on {', '.join(pending)} after 5 minutes (try: virsh -c {env.uri} console <name>)")
    if env.kubeconfig.exists() and shutil.which("kubectl"):
        _wait_kubernetes(env)
    cmd_status(args)


def _wait_kubernetes(env: Env, timeout: int = 300) -> None:
    kubectl = ["kubectl", "--kubeconfig", env.kubeconfig, "--request-timeout=5s"]
    log("waiting for the Kubernetes API server")
    deadline = time.time() + timeout
    while run([*kubectl, "get", "--raw", "/readyz"], check=False, capture_output=True).returncode != 0:
        if time.time() > deadline:
            warn("API server not ready after 5 minutes")
            return
        time.sleep(3)
    log("waiting for Kubernetes nodes to be Ready")
    run([*kubectl, "wait", "--for=condition=Ready", "node", "--all", f"--timeout={timeout}s"], check=False)


def cmd_status(args) -> None:
    env = Env(args.env)
    for name, node in sorted(outputs(env)["nodes"].items()):
        state = dom_state(env, name)
        ssh = "ssh ok" if state == "running" and port_open(node["ip"]) else ""
        print(f"{name:28} {node['ip']:16} {state:10} {ssh}")
    if env.kubeconfig.exists() and shutil.which("kubectl"):
        print()
        run(["kubectl", "--kubeconfig", env.kubeconfig, "--request-timeout=5s", "get", "nodes", "-o", "wide"],
            check=False)


def cmd_ssh(args) -> None:
    env = Env(args.env)
    nodes = outputs(env)["nodes"]
    match = [n for n in nodes if n == args.host or n == f"{env.name}-{args.host}"]
    if len(match) != 1:
        raise LabError(f"host '{args.host}' not found. Hosts: {', '.join(sorted(nodes))}")
    os.execvp("ssh", ssh_cmd(env, nodes[match[0]]["ip"]) + args.command)


def cmd_tofu(args) -> None:
    env = Env(args.env)
    write_tfvars(env)
    tofu(env, *args.tofu_args)
