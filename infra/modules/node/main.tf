terraform {
  required_providers {
    libvirt = {
      source = "dmacvicar/libvirt"
    }
  }
}

locals {
  # Extra disks are attached as virtio after the OS disk: vdb, vdc, ...
  disk_letters = split("", "bcdefghijklmnopqrstuvwxyz")
  disks = [
    for i, d in var.extra_disks : {
      device      = "/dev/vd${local.disk_letters[i]}"
      partition   = "/dev/vd${local.disk_letters[i]}1"
      filesystem  = d.filesystem
      mount_point = d.mount_point
    }
  ]

  user = merge(
    {
      name                = var.user
      shell               = "/bin/bash"
      sudo                = "ALL=(ALL) NOPASSWD:ALL"
      lock_passwd         = var.password_hash == null
      ssh_authorized_keys = var.ssh_authorized_keys
    },
    var.password_hash == null ? {} : { passwd = var.password_hash },
  )

  # Objects with different shapes cannot be the two branches of a conditional:
  # go through JSON so the disk section can be omitted when there are no disks.
  disk_config = jsondecode(length(local.disks) == 0 ? "{}" : jsonencode({
    disk_setup = {
      for d in local.disks : d.device => {
        table     = var.disk_partition.table
        layout    = var.disk_partition.layout
        overwrite = var.disk_partition.overwrite
      }
    }
    fs_setup = [for d in local.disks : { device = d.partition, filesystem = d.filesystem }]
    mounts   = [for d in local.disks : [d.partition, d.mount_point, d.filesystem, "defaults,nofail", "0", "2"]]
  }))

  cloud_config = merge(
    {
      hostname          = var.name
      fqdn              = "${var.name}.${var.domain}"
      preserve_hostname = false
      users             = [local.user]
      ssh_pwauth        = var.ssh_password_auth
      package_update    = length(var.packages) > 0
      packages          = var.packages
      runcmd            = var.runcmd
    },
    local.disk_config,
    var.cloud_init_extra,
  )
}

resource "libvirt_volume" "os" {
  name           = "${var.name}.qcow2"
  pool           = var.pool
  base_volume_id = var.base_volume_id
  size           = var.disk_gb * 1024 * 1024 * 1024
  format         = "qcow2"
}

resource "libvirt_volume" "extra" {
  count  = length(var.extra_disks)
  name   = "${var.name}-extra-${count.index}.qcow2"
  pool   = var.pool
  size   = var.extra_disks[count.index].size * 1024 * 1024 * 1024
  format = "qcow2"
}

resource "libvirt_cloudinit_disk" "this" {
  name      = "${var.name}-cloudinit.iso"
  pool      = var.pool
  user_data = "#cloud-config\n${yamlencode(local.cloud_config)}"
  meta_data = yamlencode({
    instance-id    = var.name
    local-hostname = var.name
  })
}

resource "libvirt_domain" "this" {
  name      = var.name
  vcpu      = var.cpu
  memory    = var.memory
  autostart = var.autostart
  cloudinit = libvirt_cloudinit_disk.this.id

  cpu {
    mode = "host-passthrough"
  }

  network_interface {
    network_id = var.network_id
    hostname   = var.name
    addresses  = [var.ip] # static DHCP reservation
  }

  disk {
    volume_id = libvirt_volume.os.id
  }

  dynamic "disk" {
    for_each = libvirt_volume.extra
    content {
      volume_id = disk.value.id
    }
  }

  # `virsh console <name>` works out of the box
  console {
    type        = "pty"
    target_type = "serial"
    target_port = "0"
  }

  graphics {
    type        = var.graphics_type
    listen_type = "address"
    autoport    = true
  }

  video {
    type = var.video_type
  }
}
