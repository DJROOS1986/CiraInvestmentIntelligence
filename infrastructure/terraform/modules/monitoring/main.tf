variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "prefix" { type = string }
variable "tags" { type = map(string) }
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.prefix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5
  tags                = var.tags
}
output "workspace_id" { value = azurerm_log_analytics_workspace.main.id }
