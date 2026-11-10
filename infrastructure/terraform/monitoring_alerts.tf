# Failure alerting for the CIRA research pipeline.
#
# Signals come from the job's own console output in Log Analytics (ContainerAppConsoleLogs_CL):
#   - "CIRA CLOUD PIPELINE FAILED"       printed by scripts/12-Run-Cloud-Pipeline.py on any unhandled error
#   - "CIRA CLOUD PIPELINE: SUCCESS"     printed only after a complete batch has been published
#
# The action group ag-cira-failures-<env> was created outside Terraform. It is REFERENCED here
# (data source), not managed, so Terraform will never modify or delete it.

data "azurerm_monitor_action_group" "cira_failures" {
  name                = "ag-cira-failures-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
}

data "azurerm_log_analytics_workspace" "cira" {
  name                = "law-cira-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
}

# Fast notice: a run logged a failure.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cira_pipeline_failed" {
  name                    = "alert-cira-pipeline-failed-${var.environment}"
  display_name            = "CIRA pipeline failed (${var.environment})"
  description             = "The CIRA research job logged CIRA CLOUD PIPELINE FAILED. No new batch was published."
  resource_group_name     = azurerm_resource_group.main.name
  location                = data.azurerm_log_analytics_workspace.cira.location
  scopes                  = [data.azurerm_log_analytics_workspace.cira.id]
  severity                = 1
  enabled                 = true
  evaluation_frequency    = "PT15M"
  window_duration         = "PT30M"
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerJobName_s == "${azurerm_container_app_job.cira.name}"
      | where Log_s contains "CIRA CLOUD PIPELINE FAILED"
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [data.azurerm_monitor_action_group.cira_failures.id]
  }

  tags = local.common_tags
}

# Safety net: no complete batch published for 15 hours.
# Catches failed runs, crashes before logging, Logic Apps not firing and early exits.
# Azure only allows fixed window sizes, so the window is 1 day and the 14-hour limit is in the query.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "cira_pipeline_silent" {
  name                    = "alert-cira-pipeline-silent-${var.environment}"
  display_name            = "CIRA pipeline silent for 15h (${var.environment})"
  description             = "No CIRA CLOUD PIPELINE: SUCCESS in the last 15 hours. The dashboard is serving an ageing batch."
  resource_group_name     = azurerm_resource_group.main.name
  location                = data.azurerm_log_analytics_workspace.cira.location
  scopes                  = [data.azurerm_log_analytics_workspace.cira.id]
  severity                = 2
  enabled                 = true
  evaluation_frequency    = "PT1H"
  window_duration         = "P1D"
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where TimeGenerated > ago(15h)
      | where ContainerJobName_s == "${azurerm_container_app_job.cira.name}"
      | where Log_s contains "CIRA CLOUD PIPELINE: SUCCESS"
    KQL
    time_aggregation_method = "Count"
    operator                = "LessThan"
    threshold               = 1

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [data.azurerm_monitor_action_group.cira_failures.id]
  }

  tags = local.common_tags
}
