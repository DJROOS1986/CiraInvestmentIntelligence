resource "azurerm_logic_app_workflow" "cira_evening_scheduler" {
  name                = "logic-cira-evening-dev"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  identity {
    type = "SystemAssigned"
  }

  enabled = true

  tags = local.common_tags
}

resource "azurerm_logic_app_trigger_recurrence" "cira_evening" {
  name         = "EveryDayAt2130"
  logic_app_id = azurerm_logic_app_workflow.cira_evening_scheduler.id

  frequency = "Day"
  interval  = 1

  time_zone = "Romance Standard Time"

  schedule {
    at_these_hours   = [21]
    at_these_minutes = [30]
  }
}

resource "azurerm_logic_app_action_custom" "cira_evening_start_job" {
  name         = "StartCiraContainerJob"
  logic_app_id = azurerm_logic_app_workflow.cira_evening_scheduler.id

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
    azurerm_logic_app_trigger_recurrence.cira_evening
  ]
}

resource "azurerm_role_assignment" "cira_evening_scheduler" {
  scope              = azurerm_container_app_job.cira.id
  role_definition_id = azurerm_role_definition.cira_job_starter.role_definition_resource_id
  principal_id       = azurerm_logic_app_workflow.cira_evening_scheduler.identity[0].principal_id
  principal_type     = "ServicePrincipal"
}