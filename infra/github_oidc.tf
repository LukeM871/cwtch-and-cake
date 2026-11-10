# -----------------------------------------------------------------------------
# GitHub Actions → AWS without stored keys (OIDC).
#
# GitHub gives each workflow run a short-lived signed token. AWS checks the
# token came from GitHub, from THIS repo, from the main branch, and only then
# hands out temporary credentials for the deploy role below.
# -----------------------------------------------------------------------------

# GitHub's "immutable" subject format: owner@ownerId/repo@repoId. The numeric
# IDs never change, so a renamed or re-created repo with the same name can't
# reuse this trust. Value from: gh api repos/<owner>/<repo>/actions/oidc/customization/sub
variable "github_oidc_sub_prefix" {
  description = "OIDC subject prefix of the repo allowed to deploy."
  type        = string
  default     = "repo:LukeM871@186709624/cwtch-and-cake@1452962527"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only the main branch of this one repo. Forks, other branches, pull
    # requests and other repos are all refused.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_oidc_sub_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.project}-deploy"
  description          = "Assumed by GitHub Actions (main branch only) to deploy the website"
  assume_role_policy   = data.aws_iam_policy_document.deploy_trust.json
  max_session_duration = 3600
}

# Least privilege: sync files to the one site bucket, clear the one
# distribution's cache. Nothing else. (Lambda deploy rights are added in Phase 3.)
data "aws_iam_policy_document" "deploy_permissions" {
  statement {
    sid       = "ListSiteBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]
  }

  statement {
    sid       = "WriteSiteFiles"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "InvalidateCache"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.site.arn]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-website"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_permissions.json
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes (stored as repo variable AWS_DEPLOY_ROLE_ARN)."
  value       = aws_iam_role.deploy.arn
}
