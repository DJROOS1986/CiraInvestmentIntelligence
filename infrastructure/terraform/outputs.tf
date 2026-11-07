output "resource_group_name" { value = azurerm_resource_group.main.name }
output "storage_account_name" { value = module.storage.name }
output "key_vault_name" { value = module.keyvault.name }
output "log_analytics_workspace_id" { value = module.monitoring.workspace_id }
