# Copy into existing infrastructure/terraform root, alongside main.tf.
# This grants the signed-in deployment identity blob data access without account keys.
# It does NOT create a new storage account or container.

data "azurerm_storage_account" "cira_ingestion" {
  name                = "stciradeva2pjnb"
  resource_group_name = azurerm_resource_group.main.name
}

resource "azurerm_role_assignment" "cira_ingestion_blob_contributor" {
  scope                = data.azurerm_storage_account.cira_ingestion.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}
