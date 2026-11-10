# Cwtch & Cake ☕🍪

A fictional, student-friendly café in Cathays, Cardiff, serving coffee and fresh Welsh cakes. It's built as a cloud portfolio project on AWS.

> **Fictional business, built as a portfolio project.** 🚧 Work in progress.

## Planned stack
- **Hosting:** S3 + CloudFront, with strict security headers
- **API:** API Gateway (HTTP API) + AWS Lambda (Python 3.12)
- **Data:** DynamoDB, including transactions that stop double-booking
- **Login:** Amazon Cognito (admin only)
- **Email and AI:** Amazon SES confirmations, Amazon Comprehend review toxicity check
- **Monitoring:** CloudWatch alarms and a dashboard
- **Infrastructure as code:** Terraform
- **CI/CD:** GitHub Actions with OIDC (no stored AWS keys)
