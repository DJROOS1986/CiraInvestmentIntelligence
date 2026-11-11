# Phase B (option 1): private network for CIRA workloads.
#
# - VNet with a delegated subnet for the Container Apps environment and a subnet for private endpoints.
# - Private endpoints + private DNS zones for Storage (blob), Key Vault and the AI account.
# - Public endpoints of those services stay on but default to Deny with an admin IP allowlist
#   (var.allowed_admin_ips), so Terraform and local scripts keep working from the admin machine.

resource "azurerm_virtual_network" "cira" {
  name                = "vnet-${local.prefix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = ["10.40.0.0/16"]
  tags                = local.common_tags
}

resource "azurerm_subnet" "cae" {
  name                 = "snet-cae"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.cira.name
  address_prefixes     = ["10.40.0.0/23"]

  delegation {
    name = "containerapps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "pe" {
  name                 = "snet-pe"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.cira.name
  address_prefixes     = ["10.40.2.0/24"]
}

locals {
  private_dns_zones = {
    blob   = "privatelink.blob.core.windows.net"
    vault  = "privatelink.vaultcore.azure.net"
    openai = "privatelink.openai.azure.com"
  }

  private_endpoints = {
    blob   = { resource_id = module.storage.id, subresource = "blob", zone = "blob" }
    vault  = { resource_id = module.keyvault.id, subresource = "vault", zone = "vault" }
    openai = { resource_id = azurerm_cognitive_account.research.id, subresource = "account", zone = "openai" }
  }
}

resource "azurerm_private_dns_zone" "cira" {
  for_each            = local.private_dns_zones
  name                = each.value
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "cira" {
  for_each              = local.private_dns_zones
  name                  = "link-${each.key}"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.cira[each.key].name
  virtual_network_id    = azurerm_virtual_network.cira.id
  registration_enabled  = false
  tags                  = local.common_tags
}

resource "azurerm_private_endpoint" "cira" {
  for_each            = local.private_endpoints
  name                = "pe-${local.prefix}-${each.key}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  subnet_id           = azurerm_subnet.pe.id
  tags                = local.common_tags

  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.cira[each.value.zone].id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.cira]
}
