# Bootstrap: Terraform state bucket

This creates the S3 bucket that holds Terraform's state for the rest of `infra/`. You only run it once.

**What it builds:** `cwtch-and-cake-tfstate-<account-id>` in `eu-west-2`, with:
- versioning
- SSE-S3 encryption
- all public access blocked
- an HTTPS-only bucket policy
- old versions expiring after 90 days
- `prevent_destroy`, so it can't be deleted by accident

**How it was run (first time):**
1. `terraform init` and `terraform apply`, with local state, which creates the bucket.
2. Add `backend.tf`, which points at the new bucket.
3. `terraform init -migrate-state`, which moves this stack's own state into the bucket (`bootstrap/terraform.tfstate`).

**Locking:** S3-native lock files (`use_lockfile = true`). No DynamoDB lock table is needed.
