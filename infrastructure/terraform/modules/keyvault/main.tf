variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name" { type = string }
variable "tenant_id" { type = string }
variable "tags" { type = map(string) }
variable "allowed_ips" {
  type        = list(string)
  description = "Public IPv4 addresses allowed through the firewall for management. Workloads use the private endpoint."
}
resource "azurerm_key_vault" "main" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = true # Phase B option 1: firewall default Deny + admin IP allowlist; workloads via private endpoint
  tags                          = var.tags

  network_acls {
    default_action = "Deny"
    bypass         = "None"
    ip_rules       = var.allowed_ips
  }
}
output "name" { value = azurerm_key_vault.main.name }
output "id" { value = azurerm_key_vault.main.id }
