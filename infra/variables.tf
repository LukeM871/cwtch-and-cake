variable "project" {
  description = "Name used as a prefix for every resource."
  type        = string
  default     = "cwtch-and-cake"
}

variable "region" {
  description = "Main AWS region (London)."
  type        = string
  default     = "eu-west-2"
}

variable "cognito_domain" {
  description = "Cognito hosted login domain, added to the CSP connect-src in Phase 5. Empty until then."
  type        = string
  default     = ""
}
