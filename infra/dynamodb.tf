# -----------------------------------------------------------------------------
# DynamoDB tables for bookings (docs/API.md section 9). On-demand = pay per request.
# -----------------------------------------------------------------------------

resource "aws_dynamodb_table" "bookings" {
  name         = "${local.project}-bookings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "date"
    type = "S"
  }
  attribute {
    name = "time"
    type = "S"
  }

  # For the admin page (Phase 5): one day's bookings, sorted by time.
  global_secondary_index {
    name            = "by-date"
    projection_type = "ALL"

    key_schema {
      attribute_name = "date"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "time"
      key_type       = "RANGE"
    }
  }

  # Personal data deletes itself 30 days after the booking date.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled = true # AWS-owned key is used when no KMS key is given (free)
  }

  point_in_time_recovery {
    enabled = false # keeps it free; bookings are short-lived anyway
  }
}

resource "aws_dynamodb_table" "slots" {
  name         = "${local.project}-slots"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# Café content: the busy status, the menu and the deals (docs/API.md section 9).
# pk + sk so the whole menu, in display order, is one Query on pk = "menu".
resource "aws_dynamodb_table" "cafe" {
  name         = "${local.project}-cafe"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = false # the menu can be rebuilt any time with scripts/seed_menu.py
  }
}

# Reviews (docs/API.md section 9): one row per review (pk "rv_..."), plus one
# summary row (pk "summary") with running totals for the approved reviews.
# No TTL: reviews stay until the admin deletes them.
resource "aws_dynamodb_table" "reviews" {
  name         = "${local.project}-reviews"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "createdAt"
    type = "S"
  }

  # The public list (status = approved, newest first) and the admin's moderation
  # queue (status = pending, oldest first). The summary row has no status, so
  # it's never in this index.
  global_secondary_index {
    name            = "by-status"
    projection_type = "ALL"

    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = false # keeps it free; a portfolio café's reviews aren't worth the backup cost
  }
}
