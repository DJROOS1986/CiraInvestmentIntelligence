data "azurerm_client_config" "current" {}
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}
locals {
  prefix      = "${var.project}-${var.environment}"
  common_tags = merge(var.tags, { project = var.project, environment = var.environment, managed_by = "terraform" })
}
resource "azurerm_resource_group" "main" {
  name     = "rg-${local.prefix}"
  location = var.location
  tags     = local.common_tags
}
module "storage" {
  source              = "./modules/storage"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  name                = "st${var.project}${var.environment}${random_string.suffix.result}"
  tags                = local.common_tags
}
module "monitoring" {
  source              = "./modules/monitoring"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  prefix              = local.prefix
  tags                = local.common_tags
}
module "keyvault" {
  source              = "./modules/keyvault"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  name                = "kv-${local.prefix}-${random_string.suffix.result}"
  tenant_id           = var.tenant_id
  tags                = local.common_tags
}
resource "azurerm_consumption_budget_resource_group" "monthly" {
  count             = length(var.budget_contact_emails) > 0 ? 1 : 0
  name              = "budget-${local.prefix}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.monthly_budget_eur
  time_grain        = "Monthly"
  time_period { start_date = "2026-11-01T00:00:00Z" }
  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = var.budget_contact_emails
  }
  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    contact_emails = var.budget_contact_emails
  }
}
