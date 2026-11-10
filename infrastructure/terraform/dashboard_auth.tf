# Entra ID sign-in for the CIRA dashboard (Container Apps built-in authentication).
#
# - App registration "CIRA Dashboard (<env>)", single tenant, no client secret (ID-token sign-in).
# - Enterprise app requires assignment; only the identity running Terraform (Roland) is assigned.
# - Every unauthenticated request is redirected to the Microsoft sign-in page.
# - The app-level access key in the dashboard remains as a second layer for now.
#
# azurerm 4.81 has no resource for Container Apps auth configs, so azapi is used for that part
# (same Microsoft.App API version 2024-03-01 the Logic Apps already call).

locals {
  dashboard_fqdn         = azurerm_container_app.dashboard.ingress[0].fqdn
  dashboard_callback_url = "https://${local.dashboard_fqdn}/.auth/login/aad/callback"
}

resource "azuread_application" "dashboard" {
  display_name     = "CIRA Dashboard (${var.environment})"
  sign_in_audience = "AzureADMyOrg"

  web {
    redirect_uris = [local.dashboard_callback_url]

    implicit_grant {
      id_token_issuance_enabled = true
    }
  }
}

resource "azuread_service_principal" "dashboard" {
  client_id                    = azuread_application.dashboard.client_id
  app_role_assignment_required = true
}

# Default access (empty app role ID) for the signed-in Terraform user only.
resource "azuread_app_role_assignment" "dashboard_owner" {
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = data.azurerm_client_config.current.object_id
  resource_object_id  = azuread_service_principal.dashboard.object_id
}

resource "azapi_resource" "dashboard_auth" {
  type      = "Microsoft.App/containerApps/authConfigs@2024-03-01"
  name      = "current"
  parent_id = azurerm_container_app.dashboard.id

  body = {
    properties = {
      platform = {
        enabled = true
      }
      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureactivedirectory"
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId     = azuread_application.dashboard.client_id
            openIdIssuer = "https://login.microsoftonline.com/${var.tenant_id}/v2.0"
          }
          validation = {
            allowedAudiences = [azuread_application.dashboard.client_id]
          }
        }
      }
    }
  }

  depends_on = [azuread_app_role_assignment.dashboard_owner]
}
