variable "name" { type = string }
variable "domain" { type = string }
variable "pool" { type = string }
variable "base_volume_id" { type = string }
variable "network_id" { type = string }
variable "ip" { type = string }

variable "cpu" { type = number }
variable "memory" { type = number }
variable "disk_gb" { type = number }
variable "autostart" { type = bool }
variable "extra_disks" {
  type = list(object({
    size        = number
    mount_point = string
    filesystem  = string
  }))
}

variable "user" { type = string }
variable "password_hash" {
  type      = string
  sensitive = true
}
variable "ssh_password_auth" { type = bool }
variable "ssh_authorized_keys" { type = list(string) }
variable "packages" { type = list(string) }
variable "runcmd" { type = list(any) }
variable "cloud_init_extra" { type = any }
variable "disk_partition" {
  type = object({
    table     = string
    layout    = bool
    overwrite = bool
  })
}

variable "graphics_type" { type = string }
variable "video_type" { type = string }
