# Added after the first apply: the bootstrap stack now stores its own state in
# the bucket it created, so nothing important lives only on the laptop.
terraform {
  backend "s3" {
    bucket       = "cwtch-and-cake-tfstate-588170396620"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true # S3-native state locking (no DynamoDB lock table needed)
  }
}
