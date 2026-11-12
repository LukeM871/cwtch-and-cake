# -----------------------------------------------------------------------------
# Monitoring: two alarms that email the café owner, and one dashboard.
#
# Business numbers (bookings, reviews, bots...) come from the Lambdas themselves:
# they print one JSON line in CloudWatch's "embedded metric format" and CloudWatch
# Logs turns it into a metric (lambdas/src/cwtch/metrics.py). No extra IAM
# permission and no extra API call. Everything else is AWS's own free metrics.
#
# Kept inside CloudWatch's always-free tier: 10 custom metrics, 10 alarm
# metrics (the two alarms below use exactly 10) and 3 dashboards of up to 50
# metrics (this one uses 34).
# -----------------------------------------------------------------------------

variable "alarm_email" {
  description = "Where alarm emails go. Kept out of Git: set it in infra/alarm.auto.tfvars (gitignored). Empty = no email."
  type        = string
  default     = ""
  sensitive   = true
}

locals {
  # The live stack counts into "CwtchAndCake" (cwtch/metrics.py's default); a copy
  # built in another workspace gets its own, so its test traffic never lands on the
  # live dashboard. (The first rebuild proof caught exactly that.)
  metric_namespace = local.is_main ? "CwtchAndCake" : "CwtchAndCake-${terraform.workspace}"
  function_keys    = sort(keys(local.functions))
  function_names   = { for k in local.function_keys : k => aws_lambda_function.fn[k].function_name }
}

# --- where alarms go ---------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name = "${local.project}-alarms"
  # Not encrypted with SNS's AWS-managed key: CloudWatch can't publish to a topic
  # using it, and a customer-managed key costs $1/month. Alarm emails only say
  # which alarm changed state, never any customer data.
}

# Only these two alarms, from this account, over HTTPS, may publish to the topic.
data "aws_iam_policy_document" "alarms_topic" {
  statement {
    sid       = "OnlyThisProjectsAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_metric_alarm.backend_errors.arn,
        aws_cloudwatch_metric_alarm.daily_reset_failed.arn,
      ]
    }
  }

  statement {
    sid       = "HttpsOnly"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_topic.json
}

# AWS emails a "Confirm subscription" link first; nothing arrives until it's clicked.
# Only the live stack emails anyone: a throwaway copy's alarms stay quiet.
resource "aws_sns_topic_subscription" "alarm_email" {
  count     = local.is_main && var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# --- the alarms --------------------------------------------------------------

# "Something is broken": more than 5 errors in 5 minutes across the backend.
# AWS's own Lambda "Errors" metric only counts crashes the code didn't catch
# (and timeouts). A crash that the API safety net (cwtch/http.py) turned into a
# friendly 500 is a SUCCESSFUL Lambda run as far as AWS knows, so it's counted
# by our own ServerError metric and added in here too.
resource "aws_cloudwatch_metric_alarm" "backend_errors" {
  alarm_name          = "${local.project}-backend-errors"
  alarm_description   = "More than 5 errors in 5 minutes across the Cwtch & Cake backend (Lambda errors plus crashes turned into 500s). Check the dashboard, then the Lambda logs."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching" # no traffic = nothing wrong
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn] # also say when it's fixed

  metric_query {
    id          = "total"
    label       = "Errors in 5 minutes"
    expression  = join(" + ", concat([for i, _ in local.function_keys : "FILL(e${i}, 0)"], ["FILL(crash, 0)"]))
    return_data = true
  }

  dynamic "metric_query" {
    for_each = { for i, k in local.function_keys : "e${i}" => k }
    content {
      id = metric_query.key
      metric {
        namespace   = "AWS/Lambda"
        metric_name = "Errors"
        dimensions  = { FunctionName = local.function_names[metric_query.value] }
        period      = 300
        stat        = "Sum"
      }
    }
  }

  metric_query {
    id = "crash"
    metric {
      namespace   = local.metric_namespace
      metric_name = "ServerError"
      period      = 300
      stat        = "Sum"
    }
  }
}

# The 06:00 job is retried at most twice by Lambda, so a failed morning makes 3
# errors: never enough for the alarm above. One failure is worth an email here.
# (Web requests to the admin Lambda can't trip this: their crashes become 500s.)
resource "aws_cloudwatch_metric_alarm" "daily_reset_failed" {
  alarm_name          = "${local.project}-daily-reset-failed"
  alarm_description   = "The 06:00 daily reset (or another scheduled admin task) failed, so sold-out flags may not have been cleared. Check the admin Lambda's logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = local.function_names["admin"] }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# --- the dashboard -----------------------------------------------------------

locals {
  biz    = local.metric_namespace
  api_id = aws_apigatewayv2_api.api.id
  cf_id  = aws_cloudfront_distribution.site.id

  # Counts for the line graphs. Each is drawn as FILL(metric, 0): a count with no
  # data in a period means nothing happened, so the line should sit at 0 instead
  # of breaking into dots. (Response times are NOT filled: no requests isn't 0 ms.)
  bookings_series = [
    { metric = [local.biz, "BookingCreated"], label = "Booked" },
    { metric = [local.biz, "BookingCancelled"], label = "Cancelled" },
    { metric = [local.biz, "SlotFull"], label = "Tried a full slot" },
  ]
  reviews_series = [
    { metric = [local.biz, "ReviewSubmitted"], label = "Submitted" },
    { metric = [local.biz, "ReviewApproved"], label = "Approved" },
    { metric = [local.biz, "ReviewRejected"], label = "Rejected" },
    { metric = [local.biz, "ReviewBlocked"], label = "Blocked by filters" },
  ]
  api_series = [
    { metric = ["AWS/ApiGateway", "Count", "ApiId", local.api_id], label = "Requests" },
    { metric = ["AWS/ApiGateway", "4xx", "ApiId", local.api_id], label = "4xx (refused: bad input, not logged in, rate limit)" },
    { metric = ["AWS/ApiGateway", "5xx", "ApiId", local.api_id], label = "5xx (our fault)" },
  ]
  errors_series = concat(
    [for k in local.function_keys : { metric = ["AWS/Lambda", "Errors", "FunctionName", local.function_names[k]], label = k }],
    [
      { metric = [local.biz, "ServerError"], label = "crashes turned into 500s" },
      { metric = ["AWS/Lambda", "Throttles"], label = "throttled (all Lambdas)" },
    ],
  )

  dashboard_widgets = [
    {
      type = "text", x = 0, y = 0, width = 24, height = 2
      properties = {
        markdown = join("\n", [
          "## Cwtch & Cake: live backend",
          "Bookings, reviews and bots are counted by the Lambdas themselves (CloudWatch embedded metric format: no extra permissions, no extra calls). Everything else is AWS's own metrics. Alarms email the café owner.",
        ])
      }
    },
    {
      type = "metric", x = 0, y = 2, width = 8, height = 4
      properties = {
        title                = "Bookings", view = "singleValue", region = var.region, stat = "Sum", period = 300
        setPeriodToTimeRange = true, sparkline = false
        metrics = [
          [local.biz, "BookingCreated", { label = "Booked" }],
          [local.biz, "BookingCancelled", { label = "Cancelled" }],
          [local.biz, "SlotFull", { label = "Tried a full slot" }],
        ]
      }
    },
    {
      type = "metric", x = 8, y = 2, width = 10, height = 4
      properties = {
        title                = "Reviews", view = "singleValue", region = var.region, stat = "Sum", period = 300
        setPeriodToTimeRange = true, sparkline = false
        metrics = [
          [local.biz, "ReviewSubmitted", { label = "Submitted" }],
          [local.biz, "ReviewApproved", { label = "Approved" }],
          [local.biz, "ReviewRejected", { label = "Rejected" }],
          [local.biz, "ReviewBlocked", { label = "Blocked by filters" }],
          [local.biz, "ReviewFlagged", { label = "Flagged by AI" }],
        ]
      }
    },
    {
      type = "metric", x = 18, y = 2, width = 6, height = 4
      properties = {
        title                = "Protection", view = "singleValue", region = var.region, stat = "Sum", period = 300
        setPeriodToTimeRange = true, sparkline = false
        metrics = [
          [local.biz, "BotCaught", { label = "Bots caught" }],
          [local.biz, "ServerError", { label = "Crashes caught" }],
        ]
      }
    },
    {
      type = "metric", x = 0, y = 6, width = 12, height = 6
      properties = {
        title = "Bookings over time", view = "timeSeries", region = var.region, stat = "Sum", period = 3600
        metrics = concat(
          [for i, s in local.bookings_series : [{ expression = "FILL(m${i}, 0)", label = s.label, id = "e${i}" }]],
          [for i, s in local.bookings_series : concat(s.metric, [{ id = "m${i}", visible = false }])],
        )
        yAxis = { left = { min = 0, showUnits = false } }
      }
    },
    {
      type = "metric", x = 12, y = 6, width = 12, height = 6
      properties = {
        title = "Reviews: submitted vs approved", view = "timeSeries", region = var.region, stat = "Sum", period = 3600
        metrics = concat(
          [for i, s in local.reviews_series : [{ expression = "FILL(m${i}, 0)", label = s.label, id = "e${i}" }]],
          [for i, s in local.reviews_series : concat(s.metric, [{ id = "m${i}", visible = false }])],
        )
        yAxis = { left = { min = 0, showUnits = false } }
      }
    },
    {
      type = "metric", x = 0, y = 12, width = 12, height = 6
      properties = {
        title = "API requests and errors (API Gateway)", view = "timeSeries", region = var.region, stat = "Sum", period = 300
        metrics = concat(
          [for i, s in local.api_series : [{ expression = "FILL(m${i}, 0)", label = s.label, id = "e${i}" }]],
          [for i, s in local.api_series : concat(s.metric, [{ id = "m${i}", visible = false }])],
        )
        yAxis = { left = { min = 0, showUnits = false } }
      }
    },
    {
      type = "metric", x = 12, y = 12, width = 12, height = 6
      properties = {
        title = "Website traffic (CloudFront)", view = "timeSeries", region = "us-east-1", period = 300
        metrics = [
          [{ expression = "FILL(m0, 0)", label = "Requests", id = "e0" }],
          ["AWS/CloudFront", "Requests", "Region", "Global", "DistributionId", local.cf_id, { stat = "Sum", id = "m0", visible = false }],
          ["AWS/CloudFront", "4xxErrorRate", "Region", "Global", "DistributionId", local.cf_id, { stat = "Average", label = "4xx %", yAxis = "right" }],
          ["AWS/CloudFront", "5xxErrorRate", "Region", "Global", "DistributionId", local.cf_id, { stat = "Average", label = "5xx %", yAxis = "right" }],
        ]
        yAxis = { left = { min = 0, showUnits = false }, right = { min = 0, max = 100, showUnits = false } }
      }
    },
    {
      type = "metric", x = 0, y = 18, width = 12, height = 6
      properties = {
        title = "Response time, slowest 5% (p95, ms)", view = "timeSeries", region = var.region, stat = "p95", period = 300
        metrics = concat(
          [for k in local.function_keys : ["AWS/Lambda", "Duration", "FunctionName", local.function_names[k], { label = k }]],
          [["AWS/ApiGateway", "Latency", "ApiId", local.api_id, { label = "whole API request" }]],
        )
        yAxis = { left = { min = 0, showUnits = false } }
      }
    },
    {
      type = "metric", x = 12, y = 18, width = 12, height = 6
      properties = {
        title = "Errors (what the alarm watches)", view = "timeSeries", region = var.region, stat = "Sum", period = 300
        metrics = concat(
          [for i, s in local.errors_series : [{ expression = "FILL(m${i}, 0)", label = s.label, id = "e${i}" }]],
          [for i, s in local.errors_series : concat(s.metric, [{ id = "m${i}", visible = false }])],
        )
        annotations = { horizontal = [{ label = "alarm: more than 5 in total", value = 5 }] }
        yAxis       = { left = { min = 0, showUnits = false } }
      }
    },
    {
      type = "alarm", x = 0, y = 24, width = 24, height = 2
      properties = {
        title  = "Alarms (email the café owner)"
        alarms = [aws_cloudwatch_metric_alarm.backend_errors.arn, aws_cloudwatch_metric_alarm.daily_reset_failed.arn]
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.project
  dashboard_body = jsonencode({
    start          = "-PT24H"
    periodOverride = "auto"
    widgets        = local.dashboard_widgets
  })
}

output "dashboard_url" {
  description = "The CloudWatch dashboard in the AWS console."
  value       = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.main.dashboard_name}"
}
