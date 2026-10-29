variable "name" {
  type        = string
  description = "Environment name: prefix for VMs, network, pool and volumes"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,30}$", var.name))
    error_message = "name must be lowercase letters, digits and dashes (max 31 chars), starting with a letter."
  }
}

variable "libvirt_uri" {
  type    = string
  default = "qemu:///system"
}

# ── Storage ───────────────────────────────────────────────────────────────────

variable "pool_path" {
  type        = string
  description = "Directory of the libvirt storage pool (created by libvirt)"
}

variable "base_image" {
  type        = string
  description = "Local path of the qcow2 cloud image every VM disk is layered on"
}

# ── Network ───────────────────────────────────────────────────────────────────

variable "network_cidr" {
  type        = string
  description = "Subnet of the libvirt network; the host gets the first address"

  validation {
    condition     = can(cidrhost(var.network_cidr, 0))
    error_message = "network_cidr must be a valid IPv4 CIDR, e.g. 192.168.150.0/24."
  }
}

variable "network_mode" {
  type    = string
  default = "nat"

  validation {
    condition     = contains(["nat", "route", "open", "none"], var.network_mode)
    error_message = "network_mode must be one of nat, route, open, none."
  }
}

variable "dns_domain" {
  type        = string
  default     = null
  description = "DNS domain served by the libvirt network (default: <name>.lab)"
}

variable "ip_start" {
  type        = number
  default     = 10
  description = "Host offset of the first VM IP inside network_cidr (pools without ip_offset)"
}

# ── Nodes ─────────────────────────────────────────────────────────────────────

variable "nodes" {
  description = "Node pools, keyed by pool name. VM hostnames are <name>-<pool>-<n>."
  type = map(object({
    count     = optional(number, 1)
    cpu       = optional(number, 2)
    memory    = optional(number, 2048) # MiB
    disk_gb   = optional(number, 20)
    ip_offset = optional(number) # fixed host offset for this pool: stable IPs when pools are added
    autostart = optional(bool, false)
    extra_disks = optional(list(object({
      size        = number # GiB
      mount_point = string
      filesystem  = optional(string, "ext4")
    })), [])
  }))

  validation {
    condition     = alltrue([for k, _ in var.nodes : can(regex("^[a-z][a-z0-9-]{0,20}$", k))])
    error_message = "Pool names must be lowercase letters, digits and dashes (they end up in hostnames)."
  }
}

# ── Cloud-init ────────────────────────────────────────────────────────────────

variable "user" {
  type    = string
  default = "ubuntu"
}

variable "password_hash" {
  type        = string
  default     = null
  sensitive   = true
  description = "crypt(3) hash for the user (console login). null = password login disabled."
}

variable "ssh_password_auth" {
  type    = bool
  default = false
}

variable "ssh_authorized_keys" {
  type = list(string)
}

variable "packages" {
  type    = list(string)
  default = []
}

variable "runcmd" {
  type        = list(any)
  default     = []
  description = "Commands run at first boot (cloud-init runcmd)"
}

variable "cloud_init_extra" {
  type        = any
  default     = {}
  description = "Extra top-level cloud-config keys, merged over the generated ones"
}

variable "disk_partition" {
  description = "cloud-init disk_setup settings for extra disks"
  type = object({
    table     = optional(string, "gpt")
    layout    = optional(bool, true)
    overwrite = optional(bool, false)
  })
  default = {}
}

# ── Console ───────────────────────────────────────────────────────────────────

variable "graphics_type" {
  type    = string
  default = "vnc"
}

variable "video_type" {
  type    = string
  default = "vga"
}
