variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "name" { type = string }
variable "tags" { type = map(string) }
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
  public_network_access_enabled   = true # bootstrap MVP; secure with private endpoints before sensitive data
  tags                            = var.tags
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
