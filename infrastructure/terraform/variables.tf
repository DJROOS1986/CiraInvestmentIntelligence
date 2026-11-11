variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "Use dev, test or prod."
  }
}
variable "location" {
  type    = string
  default = "westeurope"
}
variable "project" {
  type    = string
  default = "cira"
}
variable "monthly_budget_amount" {
  type    = number
  default = 120
}
variable "budget_contact_emails" {
  type    = list(string)
  default = []
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "allowed_admin_ips" {
  type        = list(string)
  description = "Public IPv4 addresses (no CIDR suffix) allowed through the Storage, Key Vault and AI firewalls for management. Set in dev.tfvars."
}
