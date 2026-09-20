terraform {
  backend "s3" {
    bucket         = "pool-selector-api-tfstate"
    key            = "prod/terraform.tfstate" # state próprio, isolado do de dev
    region         = "us-east-1"
    dynamodb_table = "pool-selector-api-tflock"
    encrypt        = true
  }
}
