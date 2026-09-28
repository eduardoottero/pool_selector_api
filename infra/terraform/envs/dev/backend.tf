# State isolado por ambiente: dev e prod nunca compartilham o mesmo
# arquivo de state, entao um terraform apply em dev nao tem como afetar prod.
terraform {
  backend "s3" {
    bucket         = "pool-selector-api-tfstate"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "pool-selector-api-tflock"
    encrypt        = true
  }
}