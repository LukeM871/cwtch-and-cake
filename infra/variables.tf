variable "project" {
  description = "Name used as a prefix for every resource."
  type        = string
  default     = "cwtch-and-cake"
}

locals {
  # One complete copy of the system per Terraform workspace. "default" is the
  # live site. Any other workspace (for example "proof") builds a separate,
  # full copy named cwtch-and-cake-<workspace>-..., with its own state, so the
  # whole stack can be built from nothing, tested and destroyed without
  # touching the live one. Names can't collide, because they come from here.
  is_main = terraform.workspace == "default"
  project = local.is_main ? var.project : "${var.project}-${terraform.workspace}"
}

variable "region" {
  description = "Main AWS region (London)."
  type        = string
  default     = "eu-west-2"
}

variable "toxicity_check_region" {
  description = <<-EOT
    Region for the Amazon Comprehend toxicity check on reviews. London doesn't
    offer it, so the nearest is Ireland ("eu-west-1"). Empty = switched off:
    reviews are still word-filtered and every one waits for the admin's approval.
    Off for now because the account is on AWS's Free plan, which blocks
    Comprehend; set it to "eu-west-1" after upgrading to the Paid plan.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "eu-west-1", "us-east-1", "us-west-2", "ap-southeast-2"], var.toxicity_check_region)
    error_message = "Toxicity detection is only offered in eu-west-1, us-east-1, us-west-2 and ap-southeast-2 (or \"\" for off)."
  }
}
