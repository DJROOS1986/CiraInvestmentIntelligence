variable "cira_dashboard_image_tag" {
  type    = string
  default = "dashboard-20261112-01b3556"
}

resource "azurerm_user_assigned_identity" "dashboard" {
  name                = "id-cira-dashboard-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "dashboard_reports_reader" {
  scope                = "${data.azurerm_storage_account.cira_ingestion.id}/blobServices/default/containers/reports"
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.dashboard.principal_id
}

resource "azurerm_role_assignment" "dashboard_acr_pull" {
  scope                = azurerm_container_registry.cira.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.dashboard.principal_id
}

resource "azurerm_container_app" "dashboard" {
  name                         = "ca-cira-dashboard-${var.environment}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.cira.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.dashboard.id]
  }

  registry {
    server   = azurerm_container_registry.cira.login_server
    identity = azurerm_user_assigned_identity.dashboard.id
  }

  ingress {
    external_enabled           = true
    target_port                = 8501
    transport                  = "auto"
    allow_insecure_connections = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name   = "research-dashboard"
      image  = "${azurerm_container_registry.cira.login_server}/cira-dashboard:${var.cira_dashboard_image_tag}"
      cpu    = 0.5
      memory = "1Gi"
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.dashboard.client_id
      }
      env {
        name  = "CIRA_STORAGE_ACCOUNT"
        value = data.azurerm_storage_account.cira_ingestion.name
      }
      env {
        name  = "CIRA_REPORTS_CONTAINER"
        value = "reports"
      }
      env {
        name  = "STREAMLIT_THEME_BASE"
        value = "dark"
      }
      env {
        name  = "STREAMLIT_THEME_PRIMARY_COLOR"
        value = "#5eead4"
      }
      env {
        name  = "STREAMLIT_THEME_BACKGROUND_COLOR"
        value = "#0b1422"
      }
      env {
        name  = "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR"
        value = "#111f30"
      }
      env {
        name  = "STREAMLIT_THEME_TEXT_COLOR"
        value = "#e5eaf2"
      }
      env {
        name  = "CIRA_AI_ENDPOINT"
        value = azurerm_cognitive_account.research.endpoint
      }
      env {
        name  = "CIRA_AI_DEPLOYMENT"
        value = azurerm_cognitive_deployment.research.name
      }
      env {
        name  = "CIRA_ALLOWED_PRINCIPAL_ID"
        value = data.azurerm_client_config.current.object_id
      }
    }
  }

  depends_on = [azurerm_role_assignment.dashboard_acr_pull, azurerm_role_assignment.dashboard_reports_reader, azurerm_role_assignment.dashboard_ai_user]
}

output "dashboard_url" {
  value = "https://${azurerm_container_app.dashboard.ingress[0].fqdn}"
}
