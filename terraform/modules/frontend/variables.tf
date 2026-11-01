variable "project" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment (prod or dev)."
  type        = string
}

variable "api_invoke_url" {
  description = "API Gateway invoke URL injected into the frontend build as VITE_API_BASE_URL."
  type        = string
}

variable "worthit_bucket_regional_domain" {
  description = "Regional domain of the WorthItFood site bucket. When set, /worthit* is served from it; empty disables the route."
  type        = string
  default     = ""
}
