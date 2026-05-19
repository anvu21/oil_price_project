terraform {
  required_version = ">= 1.7"

  backend "s3" {
    bucket         = "gas-price-tf-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "gas-price-tf-lock"
    encrypt        = true
  }
}
