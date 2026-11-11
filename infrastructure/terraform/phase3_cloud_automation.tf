resource "azurerm_user_assigned_identity" "cira" {
  name                = "id-cira-dev"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

resource "azurerm_container_registry" "cira" {
  name                = "acrciradeva2pjnb"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "cira_storage_blob" {
  scope                = data.azurerm_storage_account.cira_ingestion.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.cira.principal_id
}

resource "azurerm_role_assignment" "cira_acr_pull" {
  scope                = azurerm_container_registry.cira.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.cira.principal_id
}

# Phase B: VNet-integrated environment. Setting the subnet REPLACES the environment (and the job and
# dashboard inside it); apply with an explicit -AllowReplace list.
resource "azurerm_container_app_environment" "cira" {
  name                       = "cae-cira-dev"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = module.monitoring.workspace_id
  infrastructure_subnet_id   = azurerm_subnet.cae.id
  tags                       = local.common_tags
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }
}
