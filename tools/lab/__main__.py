"""Command line entry point: `lab COMMAND ENV ...`."""
from __future__ import annotations

import argparse
import sys

from .commands.info import cmd_check, cmd_components, cmd_envs, cmd_new
from .commands.stack import cmd_ansible, cmd_install, cmd_kubeconfig, cmd_up
from .commands.vms import cmd_create, cmd_destroy, cmd_ssh, cmd_start, cmd_status, cmd_stop, cmd_tofu
from .common import LabError

EPILOG = """\
ENV is a directory name under envs/ (or $LAB_ENVS_DIR), or a path to a directory with a cluster.yml.

examples:
  lab new demo                    scaffold envs/demo/cluster.yml
  lab check demo                  validate it, show nodes and component order
  lab up demo                     create VMs + install every component
  lab install demo cni gateway    re-run only some components
  lab install demo -- -v --check  extra args for ansible-playbook go after --
  lab components cni              options of a component
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lab", description="libvirt VMs (OpenTofu) + component library (Ansible)",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    def add(name, fn, help_, env=True):
        sp = sub.add_parser(name, help=help_, description=help_)
        if env:
            sp.add_argument("env", metavar="ENV")
        sp.set_defaults(fn=fn)
        return sp

    add("envs", cmd_envs, "list environments", env=False)
    sp = add("components", cmd_components, "list library components (and options)", env=False)
    sp.add_argument("names", nargs="*", help="show the options of these components")
    sp.add_argument("--env", help="also list the env's own roles and libraries")
    sp.add_argument("-v", "--verbose", action="store_true", help="show the options of every component")
    sp = add("new", cmd_new, "create an environment from templates/cluster.yml", env=False)
    sp.add_argument("name")
    sp.add_argument("--path", help="create it in this directory instead of envs/NAME")
    add("check", cmd_check, "validate cluster.yml, show nodes and install order")

    for name, fn, help_ in (("up", cmd_up, "create the VMs and install all components"),
                            ("create", cmd_create, "create or update the VMs only (tofu apply)")):
        sp = add(name, fn, help_)
        sp.add_argument("--confirm", action="store_true", help="review the tofu plan before applying")
        sp.set_defaults(components=[])
    sp = add("install", cmd_install, "run Ansible for all components, or only the given ones")
    sp.add_argument("components", nargs="*", metavar="COMPONENT")
    sp = add("destroy", cmd_destroy, "destroy VMs, disks, network and pool")
    sp.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    sp = add("stop", cmd_stop, "gracefully shut down the VMs (data is kept)")
    sp.add_argument("--timeout", type=int, default=180)
    add("start", cmd_start, "start the VMs, wait for ssh and Ready nodes")
    add("status", cmd_status, "VM state, IPs and Kubernetes nodes")
    add("kubeconfig", cmd_kubeconfig, "print the export line for the env kubeconfig")

    sp = add("ssh", cmd_ssh, "ssh into a VM, by full or short name (e.g. cp-1)")
    sp.add_argument("host")
    sp.add_argument("command", nargs=argparse.REMAINDER)
    sp = add("tofu", cmd_tofu, "run tofu on the env, e.g. `lab tofu ENV plan`")
    sp.add_argument("tofu_args", nargs=argparse.REMAINDER)
    sp = add("ansible", cmd_ansible, "ad-hoc ansible, e.g. `lab ansible ENV all -m ping`")
    sp.add_argument("ansible_args", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    passthrough: list[str] = []
    if argv[:1] in (["install"], ["up"]) and "--" in argv:  # extra ansible-playbook args
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    if args.cmd in ("install", "up"):
        args.ansible_args = passthrough
    for attr in ("tofu_args", "ansible_args", "command"):  # `lab tofu ENV -- plan` == `lab tofu ENV plan`
        val = getattr(args, attr, None)
        if val and val[0] == "--":
            setattr(args, attr, val[1:])
    try:
        args.fn(args)
    except LabError as e:
        print(f"\033[1;31merror:\033[0m {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
