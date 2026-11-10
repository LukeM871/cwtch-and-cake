output "site_url" {
  description = "Live HTTPS address of the website."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "site_bucket" {
  description = "S3 bucket holding the website files (private)."
  value       = aws_s3_bucket.site.bucket
}

output "distribution_id" {
  description = "CloudFront distribution ID (needed for cache invalidations)."
  value       = aws_cloudfront_distribution.site.id
}
