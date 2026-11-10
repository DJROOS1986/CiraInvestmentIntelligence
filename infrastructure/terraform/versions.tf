terraform {
  backend "azurerm" {}
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
    azuread = { source = "hashicorp/azuread", version = "~> 3.0" }
    azapi   = { source = "Azure/azapi", version = "~> 2.0" }
  }

}
provider "azurerm" {
  storage_use_azuread             = true
  resource_provider_registrations = "none"
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}

provider "azuread" {
  tenant_id = var.tenant_id
}

provider "azapi" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}
