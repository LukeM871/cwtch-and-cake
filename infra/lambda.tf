# -----------------------------------------------------------------------------
# API Lambdas: one function and one IAM role per job (least privilege).
#
# Terraform creates the functions with the first code bundle. After that,
# GitHub Actions deploys new code on every push (so Terraform ignores code changes).
# -----------------------------------------------------------------------------

variable "sender_email" {
  description = "Verified SES sender address for booking emails. Empty = emails switched off."
  type        = string
  default     = ""
}

variable "site_url" {
  description = "Public site address, used for links in emails. (A variable, not a reference to CloudFront, to avoid a dependency loop: CloudFront → API → Lambda.)"
  type        = string
  default     = "https://d37nt89jw5nszl.cloudfront.net"
}

# Shared secret CloudFront adds to API requests; Lambdas reject anything without it.
resource "random_password" "origin_secret" {
  length  = 40
  special = false
}

data "archive_file" "lambda_bundle" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/src"
  output_path = "${path.module}/.build/lambda.zip"
  excludes    = ["**/__pycache__/**"]
}

locals {
  table_arns = {
    bookings = aws_dynamodb_table.bookings.arn
    slots    = aws_dynamodb_table.slots.arn
    cafe     = aws_dynamodb_table.cafe.arn
  }

  ses_statement = var.sender_email == "" ? [] : [{
    actions   = ["ses:SendEmail"]
    resources = ["arn:aws:ses:${var.region}:${data.aws_caller_identity.current.account_id}:identity/*"]
    condition = { test = "StringEquals", variable = "ses:FromAddress", values = [var.sender_email] }
  }]

  # docs/SECURITY.md section 4: exactly these actions, nothing else.
  # leading_keys (optional) limits a statement to rows with those partition
  # keys, so get-status can only read the status row and get-menu only the
  # menu and deals, even though they share the café table.
  functions = {
    create-booking = {
      handler = "create_booking.handler"
      dynamo = [
        { actions = ["dynamodb:PutItem"], resources = [local.table_arns.bookings] },
        { actions = ["dynamodb:UpdateItem"], resources = [local.table_arns.slots] },
      ]
      ses = true
    }
    cancel-booking = {
      handler = "cancel_booking.handler"
      dynamo = [
        { actions = ["dynamodb:GetItem", "dynamodb:DeleteItem"], resources = [local.table_arns.bookings] },
        { actions = ["dynamodb:UpdateItem"], resources = [local.table_arns.slots] },
      ]
      ses = true
    }
    get-availability = {
      handler = "get_availability.handler"
      dynamo = [
        { actions = ["dynamodb:BatchGetItem"], resources = [local.table_arns.slots] },
      ]
      ses = false
    }
    get-status = {
      handler = "get_status.handler"
      dynamo = [
        { actions = ["dynamodb:GetItem"], resources = [local.table_arns.cafe], leading_keys = ["status"] },
      ]
      ses = false
    }
    get-menu = {
      handler = "get_menu.handler"
      dynamo = [
        { actions = ["dynamodb:Query"], resources = [local.table_arns.cafe], leading_keys = ["menu", "deal"] },
      ]
      ses = false
    }
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "${var.project}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.project}-${each.key}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "fn" {
  for_each = local.functions

  dynamic "statement" {
    for_each = each.value.dynamo
    content {
      actions   = statement.value.actions
      resources = statement.value.resources

      dynamic "condition" {
        for_each = length(try(statement.value.leading_keys, [])) > 0 ? [1] : []
        content {
          test     = "ForAllValues:StringEquals"
          variable = "dynamodb:LeadingKeys"
          values   = statement.value.leading_keys
        }
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.ses ? local.ses_statement : []
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
      condition {
        test     = statement.value.condition.test
        variable = statement.value.condition.variable
        values   = statement.value.condition.values
      }
    }
  }

  # Write its own logs only (not anyone else's).
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions
  name     = "least-privilege"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${var.project}-${each.key}"
  role             = aws_iam_role.fn[each.key].arn
  handler          = each.value.handler
  runtime          = "python3.12"
  architectures    = ["arm64"] # Graviton: cheaper and faster for Python
  memory_size      = 128
  timeout          = 10
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256

  environment {
    variables = {
      BOOKINGS_TABLE = aws_dynamodb_table.bookings.name
      SLOTS_TABLE    = aws_dynamodb_table.slots.name
      CAFE_TABLE     = aws_dynamodb_table.cafe.name
      ORIGIN_SECRET  = random_password.origin_secret.result
      SENDER_EMAIL   = var.sender_email
      SITE_URL       = var.site_url
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.fn[each.key].name
  }

  # Code updates come from GitHub Actions after the first deploy.
  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [aws_iam_role_policy.fn]
}

# Optional: the SES sender identity (AWS emails a verification link to it).
resource "aws_sesv2_email_identity" "sender" {
  count          = var.sender_email == "" ? 0 : 1
  email_identity = var.sender_email
}
