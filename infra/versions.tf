terraform {
  required_version = ">= 1.6"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "0.8.3"
    }
  }

  # The state path is given per environment by the `lab` CLI:
  #   tofu init -backend-config=path=<env>/.state/terraform.tfstate
  backend "local" {}
}

provider "libvirt" {
  uri = var.libvirt_uri
}
