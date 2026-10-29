"""Configuration commands: install, up, ansible, kubeconfig."""
from __future__ import annotations

from ..common import LabError, log, suggest
from ..env import Env
from ..playbook import ansible, write_inventory, write_playbook
from ..stack import resolve
from ..tofu import outputs
from .vms import cmd_create


def cmd_install(args) -> None:
    env = Env(args.env)
    stack = resolve(env)
    for name in args.components:
        if name not in stack.options:
            raise LabError(f"component '{name}' is not enabled in {env.file}{suggest(name, stack.options)}")
    write_inventory(env, stack, outputs(env)["nodes"])
    selected = write_playbook(env, stack, args.components or None)
    log(f"installing: {', '.join(selected)}")
    ansible(env, "ansible-playbook", env.playbook, *args.ansible_args)
    if env.kubeconfig.exists():
        log(f"kubeconfig ready:  export KUBECONFIG={env.kubeconfig}")


def cmd_up(args) -> None:
    cmd_create(args)
    cmd_install(args)


def cmd_ansible(args) -> None:
    env = Env(args.env)
    write_inventory(env, resolve(env), outputs(env)["nodes"])
    ansible(env, "ansible", *args.ansible_args)


def cmd_kubeconfig(args) -> None:
    env = Env(args.env)
    if not env.kubeconfig.exists():
        raise LabError(f"no kubeconfig for '{env.name}' yet (the kubernetes component fetches it)")
    print(f"export KUBECONFIG={env.kubeconfig}")
