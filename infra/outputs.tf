output "nodes" {
  description = "VMs keyed by hostname (consumed by `lab` to build the Ansible inventory)"
  value = {
    for name, n in local.nodes : name => {
      ip     = n.ip
      pool   = n.pool
      index  = n.index
      domain = module.node[name].domain_name
    }
  }
}

output "network" {
  value = {
    name   = libvirt_network.this.name
    cidr   = var.network_cidr
    domain = local.dns_domain
  }
}
