locals {
  dns_domain = coalesce(var.dns_domain, "${var.name}.lab")

  # One entry per VM, pools in lexical order. `seq` is the global position,
  # used for IPs of pools without an explicit ip_offset.
  node_list = flatten([
    for pool in sort(keys(var.nodes)) : [
      for i in range(var.nodes[pool].count) : {
        hostname = "${var.name}-${pool}-${i + 1}"
        pool     = pool
        index    = i
        spec     = var.nodes[pool]
      }
    ]
  ])

  nodes = {
    for seq, n in local.node_list : n.hostname => merge(n, {
      ip = cidrhost(var.network_cidr, n.spec.ip_offset != null ? n.spec.ip_offset + n.index : var.ip_start + seq)
    })
  }

  ssh_keys = [for k in var.ssh_authorized_keys : trimspace(k)]
}

resource "libvirt_pool" "this" {
  name = "${var.name}-pool"
  type = "dir"

  target {
    path = var.pool_path
  }
}

resource "libvirt_network" "this" {
  name      = "${var.name}-net"
  mode      = var.network_mode
  domain    = local.dns_domain
  addresses = [var.network_cidr]
  autostart = true # VMs cannot start after a host reboot if their network is down

  dhcp {
    enabled = true
  }

  dns {
    enabled    = true
    local_only = true

    dynamic "hosts" {
      for_each = local.nodes
      content {
        hostname = hosts.key
        ip       = hosts.value.ip
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(distinct([for n in local.nodes : n.ip])) == length(local.nodes)
      error_message = "Two VMs got the same IP: check the ip_offset of your node pools."
    }
  }
}

resource "libvirt_volume" "base" {
  name   = "${var.name}-base-${basename(var.base_image)}"
  pool   = libvirt_pool.this.name
  source = var.base_image
  format = "qcow2"
}

module "node" {
  source   = "./modules/node"
  for_each = local.nodes

  name           = each.key
  domain         = local.dns_domain
  pool           = libvirt_pool.this.name
  base_volume_id = libvirt_volume.base.id
  network_id     = libvirt_network.this.id
  ip             = each.value.ip

  cpu         = each.value.spec.cpu
  memory      = each.value.spec.memory
  disk_gb     = each.value.spec.disk_gb
  autostart   = each.value.spec.autostart
  extra_disks = each.value.spec.extra_disks

  user                = var.user
  password_hash       = var.password_hash
  ssh_password_auth   = var.ssh_password_auth
  ssh_authorized_keys = local.ssh_keys
  packages            = var.packages
  runcmd              = var.runcmd
  cloud_init_extra    = var.cloud_init_extra
  disk_partition      = var.disk_partition

  graphics_type = var.graphics_type
  video_type    = var.video_type
}
