# State isolado por ambiente: dev e prod nunca compartilham o mesmo arquivo de state, então um `terraform apply` em dev não tem como afetar prod por engano. 
# Bucket e tabela de lock nunca são criados por este próprio Terraform, são provisionados uma vez, manualmente, fora deste código.

terraform {
  backend "s3" {
    bucket         = "pool-selector-api-tfstate"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "pool-selector-api-tflock"
    encrypt        = true
  }
}
