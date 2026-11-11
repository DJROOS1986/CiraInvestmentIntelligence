resource "azurerm_cognitive_account" "research" {
  name                          = "ai-cira-${var.environment}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "ai-cira-${var.environment}-${random_string.suffix.result}"
  local_auth_enabled            = false
  public_network_access_enabled = true # Phase B option 1: default Deny + admin IP allowlist; dashboard via private endpoint
  tags                          = local.common_tags

  network_acls {
    default_action = "Deny"
    ip_rules       = var.allowed_admin_ips
  }
}

resource "azurerm_cognitive_deployment" "research" {
  name                 = "cira-research"
  cognitive_account_id = azurerm_cognitive_account.research.id
  model {
    format  = "OpenAI"
    name    = "gpt-5.4-mini"
    version = "2026-03-17"
  }
  sku {
    name     = "GlobalStandard"
    capacity = 1
  }
  version_upgrade_option = "OnceNewDefaultVersionAvailable"
}

resource "azurerm_role_assignment" "dashboard_ai_user" {
  scope                = azurerm_cognitive_account.research.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.dashboard.principal_id
}

resource "azurerm_role_assignment" "developer_ai_user" {
  scope                = azurerm_cognitive_account.research.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

output "research_ai_endpoint" {
  value = azurerm_cognitive_account.research.endpoint
}
