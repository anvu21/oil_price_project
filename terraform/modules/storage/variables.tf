variable "project" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "raw_retention_days_ia" {
  description = "Days before raw objects transition to STANDARD_IA."
  type        = number
  default     = 30
}

variable "raw_retention_days_glacier" {
  description = "Days before raw objects transition to GLACIER."
  type        = number
  default     = 90
}
