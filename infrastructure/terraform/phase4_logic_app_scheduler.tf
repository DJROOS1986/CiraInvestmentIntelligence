resource "azurerm_logic_app_workflow" "cira_scheduler" {
  name                = "logic-cira-daily-dev"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  identity {
    type = "SystemAssigned"
  }

  enabled = true

  tags = local.common_tags
}

resource "azurerm_logic_app_trigger_recurrence" "cira_daily" {
  name         = "EveryDayAt0700"
  logic_app_id = azurerm_logic_app_workflow.cira_scheduler.id

  frequency = "Day"
  interval  = 1

  time_zone = "Romance Standard Time"

  schedule {
    at_these_hours   = [9]
    at_these_minutes = [0]
  }
}

resource "azurerm_logic_app_action_custom" "cira_start_job" {
  name         = "StartCiraContainerJob"
  logic_app_id = azurerm_logic_app_workflow.cira_scheduler.id

  body = jsonencode({
    type = "Http"

    inputs = {
      method = "POST"

      uri = "https://management.azure.com${azurerm_container_app_job.cira.id}/start?api-version=2024-03-01"

      headers = {
        "Content-Type" = "application/json"
      }

      body = {}

      authentication = {
        type     = "ManagedServiceIdentity"
        audience = "https://management.azure.com/"
      }
    }

    runAfter = {}
  })

  depends_on = [
    azurerm_logic_app_trigger_recurrence.cira_daily
  ]
}

resource "azurerm_role_definition" "cira_job_starter" {
  name        = "CIRA Job Starter Dev"
  scope       = azurerm_resource_group.main.id
  description = "Allows the CIRA Logic App to start the CIRA Container Apps Job."

  permissions {
    actions = [
      "Microsoft.App/jobs/start/action"
    ]

    not_actions = []
  }

  assignable_scopes = [
    azurerm_resource_group.main.id
  ]
}

resource "azurerm_role_assignment" "cira_scheduler" {
  scope              = azurerm_container_app_job.cira.id
  role_definition_id = azurerm_role_definition.cira_job_starter.role_definition_resource_id
  principal_id       = azurerm_logic_app_workflow.cira_scheduler.identity[0].principal_id
  principal_type     = "ServicePrincipal"
}
