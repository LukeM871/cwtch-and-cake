# -----------------------------------------------------------------------------
# The 06:00 daily reset (docs/API.md section 7): the Welsh cakes are baked fresh
# every morning, so every "sold out" flag goes back to false. The same run
# recounts the review summary and repairs it if it has drifted.
#
# EventBridge Scheduler, not an EventBridge rule: rules only understand UTC, so
# "06:00" would drift to 07:00 UK time every summer. Scheduler knows the
# Europe/London time zone and handles the clock change itself.
# -----------------------------------------------------------------------------

# The project's own schedule group. Scheduler identifies itself to IAM by the
# GROUP a schedule is in, so a dedicated group lets the role below trust this
# project's schedules only (not every schedule in the account's default group).
resource "aws_scheduler_schedule_group" "cafe" {
  name = local.project
}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    # Only this project's schedules, in this account, can use the role ("confused deputy" protection).
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_scheduler_schedule_group.cafe.arn]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.project}-scheduler"
  description        = "Lets the 06:00 schedule start the admin Lambda, and nothing else"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fn["admin"].arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-admin-lambda"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "daily_reset" {
  name        = "${local.project}-daily-reset"
  group_name  = aws_scheduler_schedule_group.cafe.name
  description = "06:00 UK time: clear sold-out flags (fresh bake) and recount the review summary"

  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "Europe/London"

  flexible_time_window {
    mode = "OFF" # exactly 06:00, not "some time around 06:00"
  }

  target {
    arn      = aws_lambda_function.fn["admin"].arn
    role_arn = aws_iam_role.scheduler.arn
    # The admin Lambda tells this apart from a web request: it has no requestContext.
    input = jsonencode({ task = "daily-reset" })

    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600 # give up after an hour (by then the café is open)
    }
  }

  depends_on = [aws_iam_role_policy.scheduler]
}
