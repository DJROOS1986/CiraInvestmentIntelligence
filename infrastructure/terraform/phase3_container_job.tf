variable "cira_sec_user_agent" {
  description = "SEC-compliant application contact header."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("@", var.cira_sec_user_agent))
    error_message = "The SEC User-Agent must contain a contact email."
  }
}

variable "cira_pipeline_image_tag" {
  type    = string
  default = "research-20261112-d963208"
}

resource "azurerm_container_app_job" "cira" {
  workload_profile_name        = "Consumption"
  name                         = "caj-cira-dev"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.cira.id

  replica_timeout_in_seconds = 1800
  replica_retry_limit        = 1

  identity {
    type = "UserAssigned"
    identity_ids = [
      azurerm_user_assigned_identity.cira.id
    ]
  }

  registry {
    server   = azurerm_container_registry.cira.login_server
    identity = azurerm_user_assigned_identity.cira.id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "cira-financial-intelligence"
      image  = "${azurerm_container_registry.cira.login_server}/cira-financial-intelligence:${var.cira_pipeline_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.cira.client_id
      }

      env {
        name  = "CIRA_STORAGE_ACCOUNT"
        value = module.storage.name
      }

      env {
        name  = "CIRA_RAW_CONTAINER"
        value = "raw-filings"
      }

      env {
        name  = "CIRA_REPORTS_CONTAINER"
        value = "reports"
      }

      env {
        name  = "CIRA_SEC_USER_AGENT"
        value = var.cira_sec_user_agent
      }
    }
  }

  tags = local.common_tags
}
