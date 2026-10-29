# labkit

Reusable base for "spawn libvirt VMs with OpenTofu, then configure them with Ansible".

- **One file per environment** (`envs/<name>/cluster.yml`) describes the VMs *and* what to install on them.
- **A component library** (`ansible/roles/`): versioned, configurable building blocks (kubernetes,
  cni, metallb, ingress, gateway, cert_manager, ceph ...) with dependency tracking.
- **One CLI** (`./lab`) validates the config, creates the VMs, generates inventory and playbook, runs Ansible.

```
envs/demo/cluster.yml ──► lab ──► .state/tofu.tfvars.json ──► tofu (infra/)  ──► VMs, network, pool
                               └► .state/inventory.yml + site.yml ──► ansible-playbook (library roles)
```

## Quick start

Prerequisites on the host: libvirt/KVM (`qemu:///system` usable by your user), `tofu`, `virsh`,
`openssl`, `curl`, `python3`, an ssh key (`~/.ssh/id_ed25519.pub` by default), `kubectl` (optional).
The first run of `./lab` creates `.venv/` with ansible-core and the needed collections.

```bash
./lab new demo          # envs/demo/cluster.yml with a free subnet and sensible defaults
$EDITOR envs/demo/cluster.yml
./lab check demo        # validate: nodes, IPs, components in install order
./lab up demo           # create VMs + install everything
export KUBECONFIG=$PWD/envs/demo/.state/kubeconfig
```

Optional: `ln -s "$PWD/lab" ~/.local/bin/lab` to run it from anywhere.

## Commands

| Command | What it does |
|---|---|
| `lab new NAME [--path DIR]` | scaffold an environment from `templates/cluster.yml` |
| `lab check ENV` | validate cluster.yml, print nodes / IPs / install order |
| `lab up ENV` | `create` + `install` |
| `lab create ENV [--confirm]` | create or update the VMs (tofu apply; `--confirm` shows the plan first) |
| `lab install ENV [COMPONENT...] [-- ansible args]` | run all components, or only some (`lab install demo gateway -- -v`) |
| `lab stop ENV` / `lab start ENV` | graceful shutdown / boot, waits for ssh and Ready nodes |
| `lab status ENV` | VM state, IPs, `kubectl get nodes` |
| `lab ssh ENV HOST [cmd]` | ssh as the VM user; HOST can be short (`cp-1`) |
| `lab destroy ENV [-y]` | destroy VMs, disks, network and pool |
| `lab components [NAME...] [-v]` | the library, with every option, type and default |
| `lab tofu ENV ARGS` / `lab ansible ENV ARGS` | raw tofu / ad-hoc ansible on the env (`lab ansible demo all -m ping`) |
| `lab kubeconfig ENV` | prints `export KUBECONFIG=...` |

ENV is a name under `envs/` (or `$LAB_ENVS_DIR`) **or a path**: a project can keep its env dir in its
own repo and run `lab up ./deploy/lab`.

## cluster.yml

`templates/cluster.yml` is the commented reference. In short:

```yaml
name: demo
infra:
  network: {cidr: 192.168.150.0/24}
  image: {url: https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img}
  user: ubuntu
  ssh_key: ~/.ssh/id_ed25519.pub
  nodes:                                   # node pools; pool name = Ansible group
    cp:     {count: 1, cpu: 2, memory: 4096, disk: 20, groups: [k8s_control_plane]}
    worker: {count: 2, cpu: 2, memory: 4096, disk: 20, groups: [k8s_workers],
             extra_disks: [{size: 20, mount_point: /data}]}
components:                                # only what differs from the defaults
  kubernetes: {version: "1.36"}
  cni: {provider: calico}
  metallb:
  gateway: {provider: envoy-gateway}       # and/or  ingress: {provider: traefik}
  cert_manager:
```

- VM names: `<name>-<pool>-<n>`; static IPs from `.10` in pool-name order (or per-pool `ip_offset`).
  The libvirt network resolves the VM names via DNS and starts automatically at boot.
- Options are the component's variables without the prefix: `cni: {provider: calico}` sets `cni_provider`.
  Unknown options, wrong types/choices, unquoted versions (`1.30` is a float!) and missing
  dependencies are reported before anything is created.
- `vars:` sets any other Ansible variable; `libraries:` and `playbooks:` add project-specific things (below).

## The component library

A component is an Ansible role with a `meta/component.yml`:

```yaml
description: Pod network (cilium, calico or flannel), installed with Helm
hosts: k8s_control_plane[0]       # play target (any Ansible host pattern)
requires: [kubernetes]            # capabilities that must be enabled, or `lab check` fails
after: [loadbalancer]             # ordering only, when present
provides: [loadbalancer]          # extra capability names (alternatives can share one)
conflicts: []
requires_groups: [k8s_control_plane]
become: true                      # also: gather_facts, connection, environment
```

Options are documented in `meta/argument_specs.yml` (Ansible validates them at run time, `lab`
validates them before) and defaulted in `defaults/main.yml`. Conventions:

- every variable is prefixed with the component name (`metallb_pools`);
- providers/versions live in a `<name>_catalog` table in defaults: adding a provider = one entry
  + its name in the `choices` of `<name>_provider`;
- `<name>_values` is merged over the generated Helm values: the escape hatch for anything not exposed;
- the defaults of **all enabled components** are written into the inventory, so a component can read
  another one's settings (cni uses `kubernetes_pod_cidr`, cert_manager uses `gateway_name`).
  `lab_components` / `lab_capabilities` tell what is enabled; `lab_lb_range`, `lab_network_*`,
  `lab_state_dir`, `lab_kubeconfig` describe the environment;
- roles without `component.yml` (e.g. `helm`) are helpers, pulled in through `meta/main.yml` dependencies.

Current components (`lab components -v` for all options):

| Component | Choices / notes |
|---|---|
| `base` | hostname, /etc/hosts, packages, timezone, optional upgrade + reboot |
| `kubernetes` | kubeadm, version `1.36`/`1.36.5`, containerd/runc/CNI-plugins pinned from upstream; Ubuntu/Debian and Alma/RHEL; multi control-plane; kubeconfig fetched to `.state/kubeconfig` |
| `cni` | `cilium` (optionally replacing kube-proxy), `calico`, `flannel` |
| `metallb` | L2, default pool = top of the VM subnet |
| `ingress` | `traefik`, `haproxy`, `ingress-nginx` (retired upstream, legacy only); fixed LB IP option |
| `gateway` | Gateway API: `envoy-gateway`, `nginx-gateway-fabric`, `traefik`; installs CRDs when needed, creates a shared `Gateway` |
| `cert_manager` | issuers `selfsigned`, `ca` (local CA), `acme` (HTTP-01 through the shared Gateway or the ingress class) |
| `ceph_demo` | Ceph in a docker container on the host (ported from the old `ansible/` setup) |
| `ceph_csi` | RBD StorageClass, auto-configured from `ceph_demo` or pointed to an external cluster |

### Adding things for one project

Without touching the library:

- **Own components**: put roles in `envs/<env>/roles/` or in any directory listed in `libraries:`;
  give them a `meta/component.yml` and list them under `components:` like library ones. A role with
  the same name as a library role overrides it.
- **Plain playbooks**: `playbooks: [post.yml]` runs them after the components on a full install,
  with the same inventory (all `lab_*` and component variables available).

When something proves reusable, move the role into `ansible/roles/`.

## Layout

```
lab                     entry point (bash: manages .venv, runs tools/lab)
tools/lab/              the CLI: env.py, components.py, stack.py (dependency resolution),
                        tofu.py, playbook.py (inventory/playbook generation), virt.py, commands/
infra/                  OpenTofu root module (libvirt): pool, network, base image, modules/node (one VM)
ansible/ansible.cfg     used by lab; roles path and collections are set per env
ansible/roles/          the component library
templates/cluster.yml   template for `lab new`, also the config reference
examples/               sample environments (`lab check examples/almalinux`)
envs/<env>/cluster.yml  your environments, with generated files in envs/<env>/.state/ (gitignored)
```

## Tested

End to end (create → install → traffic through LB → re-run with 0 changes → stop/start → destroy):

- Ubuntu 24.04, 1 cp + 1 worker: kubernetes 1.36, cilium, metallb, gateway envoy-gateway + ingress traefik, cert_manager
- AlmaLinux 10.2, single node: kubernetes 1.35.9, calico, metallb, gateway nginx-gateway-fabric + ingress haproxy, cert_manager

Not yet exercised on a real run: flannel, ingress-nginx, the traefik gateway provider, ceph_demo / ceph_csi, multiple control planes.

## Notes and limits

- Version changes apply to new clusters: the kubernetes component never changes packages on a node
  that already joined (that is a `kubeadm upgrade`, not automated). Same for switching CNI provider.
- Multiple control planes work, but the API endpoint defaults to the first one: set
  `control_plane_endpoint` to a VIP/LB for real HA.
- The console password is never written in `cluster.yml` in plaintext: use `infra.password_hash`
  (crypt(3), `openssl passwd -6`), `infra.password_file`, or `$LAB_PASSWORD`. A plaintext one is hashed
  with a salt derived from env+password, so `lab create` is idempotent (a random salt would rebuild
  every VM on each apply).
- `envs/` is gitignored (your environments are yours); `examples/` has a sample. A gitleaks
  pre-commit hook is configured: `pre-commit install`.
- Infra is libvirt-only for now; `infra/` is a plain tofu module, `lab` only needs its `nodes` output
  (`{hostname: {ip, pool}}`) to support another provider.
