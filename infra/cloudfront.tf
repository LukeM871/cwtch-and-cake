# -----------------------------------------------------------------------------
# CloudFront: serves the site over HTTPS from edge locations, adds the
# security headers from docs/SECURITY.md to every response.
# -----------------------------------------------------------------------------

locals {
  # docs/SECURITY.md section 2. Keep the two in sync. The admin page's only
  # call to another site is swapping its login code for tokens at Cognito.
  content_security_policy = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self' https://${local.cognito_host}",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    "upgrade-insecure-requests",
  ])
}

# AWS-managed cache policy "CachingOptimized" (long caching, gzip/brotli).
data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

# API caching: off unless the Lambda says otherwise (availability and status
# send "max-age=30", the menu "max-age=300"). Query strings are part of the
# cache key so each day/type is cached separately.
resource "aws_cloudfront_cache_policy" "api" {
  name        = "${local.project}-api"
  comment     = "Respect Cache-Control from the API; never cache by default"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 300 # the menu's 5 minutes is the longest any API response is kept

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    query_strings_config {
      query_string_behavior = "all"
    }
    headers_config {
      header_behavior = "none"
    }
    cookies_config {
      cookie_behavior = "none"
    }
  }
}

# Admin API: the login token (Authorization header) must reach API Gateway.
# CloudFront strips that header from GET requests unless it's part of the cache
# key, so it's in the key here. Nothing is ever actually cached: the admin
# Lambda answers "Cache-Control: no-store", and with the token in the key two
# people could never share an answer anyway.
resource "aws_cloudfront_cache_policy" "api_admin" {
  name        = "${local.project}-api-admin"
  comment     = "Admin API: forwards the Cognito token; never cached (origin sends no-store)"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 1 # must be above 0 to allow a cache key; no-store wins anyway

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    query_strings_config {
      query_string_behavior = "all"
    }
    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Authorization"]
      }
    }
    cookies_config {
      cookie_behavior = "none"
    }
  }
}

# AWS-managed: forward everything the browser sent except the Host header
# (API Gateway needs its own Host).
data "aws_cloudfront_origin_request_policy" "all_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# Origin Access Control: CloudFront signs its requests to S3, so the bucket
# can stay fully private.
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.project}-site-oac"
  description                       = "CloudFront access to the private site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# The security headers (docs/SECURITY.md section 1).
resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "${local.project}-security-headers"
  comment = "Security headers from docs/SECURITY.md"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.content_security_policy
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 63072000 # 2 years
      include_subdomains         = true
      preload                    = false # only possible with a custom domain
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
      override = true
    }
    items {
      header   = "Cross-Origin-Opener-Policy"
      value    = "same-origin"
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${local.project} website"
  default_root_object = "index.html"
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = "PriceClass_100" # Europe + North America edges only (cheapest; covers the UK)

  origin {
    origin_id                = "site-s3"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    origin_id   = "api"
    domain_name = replace(aws_apigatewayv2_api.api.api_endpoint, "https://", "")

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    # Proves the request came through CloudFront (docs/SECURITY.md section 3).
    custom_header {
      name  = "x-origin-verify"
      value = random_password.origin_secret.result
    }
  }

  # Listed first: CloudFront uses the first pattern that matches.
  ordered_cache_behavior {
    path_pattern               = "/api/admin/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.api_admin.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.api.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  default_cache_behavior {
    target_origin_id           = "site-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # A private S3 bucket answers 403 (not 404) for a missing file; show the
  # friendly 404 page instead. Error pages apply to EVERY origin, so 404 is
  # deliberately NOT mapped: the API's JSON 404 ("booking not found") must reach
  # the browser untouched. The API never returns 403 through CloudFront: the
  # origin check only fails for direct calls, and the admin routes use 401 for
  # every login problem (no authorization scopes on the routes, whose failure
  # would be a 403 from API Gateway; the admin Lambda checks the token instead).
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # The shared *.cloudfront.net certificate doesn't allow choosing a minimum
    # TLS version (AWS fixes it). With a custom domain + ACM cert this becomes
    # minimum_protocol_version = "TLSv1.2_2021".
    cloudfront_default_certificate = true
  }
}
