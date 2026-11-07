variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name" { type = string }
variable "tenant_id" { type = string }
variable "tags" { type = map(string) }
resource "azurerm_key_vault" "main" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = true # bootstrap MVP; restrict before storing broker credentials
  tags                          = var.tags
}
output "name" { value = azurerm_key_vault.main.name }
