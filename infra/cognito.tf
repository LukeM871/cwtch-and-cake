# -----------------------------------------------------------------------------
# Cognito: the admin login (docs/SECURITY.md section 3).
#
# One user pool with sign-up switched OFF and MFA (an authenticator app)
# REQUIRED. The admin page (Phase 7) sends people to Cognito's own hosted login
# page, gets a code back, swaps it for tokens (with PKCE), and sends the access
# token to /api/admin/*. API Gateway checks the token before the admin Lambda
# runs. No passwords ever touch our code.
#
# The admin user itself is NOT created here (it would put a personal email and
# a password into Terraform state). It's made once with the AWS CLI; see
# docs/SECURITY.md section 3.
# -----------------------------------------------------------------------------

resource "aws_cognito_user_pool" "admin" {
  name = "${local.project}-admin"

  # Essentials is needed for the newer "managed login" page. Free for the
  # first 10,000 monthly active users (there's one).
  user_pool_tier = "ESSENTIALS"

  # Off so Phase 6 can prove the whole stack rebuilds (terraform destroy + apply).
  deletion_protection = "INACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true # nobody can sign themselves up
  }

  mfa_configuration = "ON" # required for every user, not optional
  software_token_mfa_configuration {
    enabled = true # authenticator app codes (no SMS: costs money and can be SIM-swapped)
  }

  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false # length beats symbols; long passphrases are fine
    temporary_password_validity_days = 3
    password_history_size            = 5
  }

  # No email or phone is stored, so a forgotten password is reset by the AWS
  # account owner (admin-set-user-password), not by a self-service email link.
  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
}

# Only members of this group can use the admin routes (the admin Lambda checks
# the token's cognito:groups claim, as a second layer behind "no sign-up").
resource "aws_cognito_user_group" "admins" {
  name         = "admins"
  user_pool_id = aws_cognito_user_pool.admin.id
  description  = "Can use /api/admin/* (moderate reviews, set the busy status, edit the menu)"
}

# The hosted login page lives at https://<domain>.auth.<region>.amazoncognito.com
resource "aws_cognito_user_pool_domain" "admin" {
  domain                = "${local.project}-admin"
  user_pool_id          = aws_cognito_user_pool.admin.id
  managed_login_version = 2 # the newer "managed login" page
}

locals {
  cognito_host = "${aws_cognito_user_pool_domain.admin.domain}.auth.${var.region}.amazoncognito.com"
  # Where Cognito may send people back to after logging in: the admin page, and
  # a localhost address for working on the admin page on a laptop. A login code
  # is only ever delivered to these exact addresses.
  admin_redirect_urls = ["${var.site_url}/admin/", "http://localhost:8765/admin/"]
}

# The admin page's "app client". Public (no client secret): JavaScript in a
# browser can't keep a secret, so the login code is protected with PKCE instead.
resource "aws_cognito_user_pool_client" "admin" {
  name         = "${local.project}-admin-page"
  user_pool_id = aws_cognito_user_pool.admin.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"] # authorization code flow (never the old "implicit" flow)
  allowed_oauth_scopes                 = ["openid"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = local.admin_redirect_urls
  logout_urls                          = local.admin_redirect_urls

  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  prevent_user_existence_errors = "ENABLED" # "wrong username" and "wrong password" look the same
  enable_token_revocation       = true      # logging out really ends the session
  auth_session_validity         = 5         # minutes to finish the login + MFA steps

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 12
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }
}

# The look of the managed login page (Cognito's default style for now; the
# café's colours and logo can be added in Phase 7).
resource "aws_cognito_managed_login_branding" "admin" {
  client_id                   = aws_cognito_user_pool_client.admin.id
  user_pool_id                = aws_cognito_user_pool.admin.id
  use_cognito_provided_values = true
}

output "cognito_user_pool_id" {
  description = "Admin user pool (used when creating the admin user with the CLI)."
  value       = aws_cognito_user_pool.admin.id
}

output "cognito_client_id" {
  description = "The admin page's app client id (public, not a secret)."
  value       = aws_cognito_user_pool_client.admin.id
}

output "admin_login_url" {
  description = "Cognito's hosted login page for the admin."
  value       = "https://${local.cognito_host}/login?client_id=${aws_cognito_user_pool_client.admin.id}&response_type=code&scope=openid&redirect_uri=${urlencode(local.admin_redirect_urls[0])}"
}
