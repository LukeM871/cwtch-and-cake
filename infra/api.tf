# -----------------------------------------------------------------------------
# API Gateway (HTTP API): routes /api/* to the Lambdas, with rate limits.
# Reached through CloudFront only (Lambdas check the secret origin header).
# -----------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "api" {
  name          = "${local.project}-api"
  protocol_type = "HTTP"
  description   = "Cwtch & Cake API (see docs/API.md)"
}

locals {
  # admin = true: API Gateway checks for a valid Cognito login first (401 if not).
  routes = {
    "POST /api/booking"                  = { fn = "create-booking", rate = 3, burst = 5 }
    "POST /api/booking/cancel"           = { fn = "cancel-booking", rate = 3, burst = 5 }
    "GET /api/availability"              = { fn = "get-availability", rate = 10, burst = 20 }
    "GET /api/status"                    = { fn = "get-status", rate = 10, burst = 20 }
    "GET /api/menu"                      = { fn = "get-menu", rate = 10, burst = 20 }
    "POST /api/reviews"                  = { fn = "create-review", rate = 1, burst = 3 }
    "GET /api/reviews"                   = { fn = "list-reviews", rate = 10, burst = 20 }
    "GET /api/admin/bookings"            = { fn = "admin", rate = 5, burst = 10, admin = true }
    "PUT /api/admin/status"              = { fn = "admin", rate = 5, burst = 10, admin = true }
    "PATCH /api/admin/menu/{itemId}"     = { fn = "admin", rate = 5, burst = 10, admin = true }
    "GET /api/admin/reviews"             = { fn = "admin", rate = 5, burst = 10, admin = true }
    "POST /api/admin/reviews/{reviewId}" = { fn = "admin", rate = 5, burst = 10, admin = true }
  }
}

# Checks the Cognito token's signature, expiry, issuer (our user pool) and
# audience (our admin app client) before the admin Lambda is even started.
resource "aws_apigatewayv2_authorizer" "admin" {
  api_id           = aws_apigatewayv2_api.api.id
  name             = "cognito-admin"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://${aws_cognito_user_pool.admin.endpoint}"
    audience = [aws_cognito_user_pool_client.admin.id]
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each               = local.functions
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "route" {
  for_each  = local.routes
  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.fn[each.value.fn].id}"

  authorization_type = try(each.value.admin, false) ? "JWT" : "NONE"
  authorizer_id      = try(each.value.admin, false) ? aws_apigatewayv2_authorizer.admin.id : null
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # Whole-API limit (docs/SECURITY.md section 6).
  default_route_settings {
    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }

  # Stricter limits on the forms.
  dynamic "route_settings" {
    for_each = local.routes
    content {
      route_key              = route_settings.key
      throttling_rate_limit  = route_settings.value.rate
      throttling_burst_limit = route_settings.value.burst
    }
  }

  depends_on = [aws_apigatewayv2_route.route]
}

resource "aws_lambda_permission" "api" {
  for_each      = local.functions
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

output "api_direct_url" {
  description = "API Gateway address. Direct calls are refused (403); use the site URL + /api/..."
  value       = aws_apigatewayv2_api.api.api_endpoint
}
