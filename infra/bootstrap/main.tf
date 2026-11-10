# -----------------------------------------------------------------------------
# Bootstrap: the S3 bucket that stores Terraform's state for the main stack.
#
# Run once by hand (see infra/bootstrap/README.md). Everything else in infra/
# keeps its state in this bucket.
# -----------------------------------------------------------------------------

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "eu-west-2" # London

  default_tags {
    tags = {
      Project   = "cwtch-and-cake"
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}

# Looks up the AWS account ID so the bucket name is unique worldwide.
data "aws_caller_identity" "current" {}

locals {
  bucket_name = "cwtch-and-cake-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.bucket_name

  # Stops `terraform destroy` from ever deleting the state bucket by accident.
  lifecycle {
    prevent_destroy = true
  }
}

# Keeps every old version of the state file, so a bad change can be rolled back.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Encrypts everything stored in the bucket (SSE-S3: free, managed by AWS).
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Blocks every kind of public access. The state file must never be public.
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Turns off old-style ACLs; access is controlled only by IAM and bucket policy.
resource "aws_s3_bucket_ownership_controls" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Rejects any request that isn't over HTTPS.
resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tfstate.arn,
          "${aws_s3_bucket.tfstate.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

# Deletes old state versions after 90 days so storage never builds up.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.tfstate]
}

output "state_bucket_name" {
  description = "Put this in the backend block of infra/ (and here, after the first apply)."
  value       = aws_s3_bucket.tfstate.bucket
}
