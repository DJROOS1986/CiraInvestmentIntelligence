variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name" { type = string }
variable "tags" { type = map(string) }
variable "allowed_ips" {
  type        = list(string)
  description = "Public IPv4 addresses allowed through the firewall for management. Workloads use the private endpoint."
}
resource "azurerm_storage_account" "main" {
  name                            = var.name
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  public_network_access_enabled   = true # Phase B option 1: firewall default Deny + admin IP allowlist; workloads via private endpoint
  tags                            = var.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = var.allowed_ips
  }
}
resource "azurerm_storage_container" "raw" {
  name                  = "raw-filings"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}
resource "azurerm_storage_container" "reports" {
  name                  = "reports"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}
output "name" { value = azurerm_storage_account.main.name }
output "id" { value = azurerm_storage_account.main.id }
