# Terraform — provisionamento desacoplado do deploy

Esta pasta descreve a infraestrutura AWS da API (ECS Fargate, ALB, S3, IAM, ECR) como código.
Nunca foi aplicada pois não há conta AWS provisionada para este desafio.
O que existe aqui é validado no CI (terraform fmt + terraform validate, que não exigem credencial AWS).

## Por que esta camada é desacoplada da esteira de deploy

O workflow que efetivamente publica a aplicação
(`.github/workflows/deploy-dev.yml` e `.github/workflows/deploy-prod.yml`) não importa nem lê
nenhum arquivo `.tf`. Ele lê apenas três nomes, vindos de vars do GitHub:
`ECS_CLUSTER`, `ECS_SERVICE` e `ECR_REPO`. Esses nomes podem ter vindo dos outputs deste Terraform
(`outputs.tf`) ou ter sido digitados manualmente no console da AWS — o workflow de deploy não tem
como distinguir.

## Estrutura (variante com isolamento de ambiente)

```
modules/api/     # o desenho da topologia, parametrizado — nunca aplicado direto
envs/dev/        # instância do módulo para dev, state e tfvars próprios
envs/prod/       # idem para prod
```

Cada `envs/<ambiente>` tem seu próprio `backend.tf` (state em S3 + lock em DynamoDB) e seu próprio
`.tfvars`, apontando para o mesmo módulo (`modules/api`). Isso é o que garante que um `terraform
apply` em dev não tem como, por acidente, afetar o state de prod — são arquivos de state
fisicamente diferentes desde a raiz.

## Diferenças reais entre dev e prod (não apenas nomenclatura)

| Parâmetro | dev | prod | Por quê |
|---|---|---|---|
| desired_count | 1 | 3 | prod cobre ≥2 AZs e mantém margem para um pico sem esperar o autoscaling reagir |
| task_cpu / task_memory | 256 / 512 | 512 / 1024 | volume de produção justifica mais headroom por task |
| log_retention_days | 7 | 30 | prod precisa reter log o bastante para investigar um incidente passado |
| enable_deletion_protection | false | true | dev deve ser fácil de destruir/recriar; prod nunca deve cair por comando errado |

## Como seria aplicado, se houvesse uma conta AWS

```bash
cd envs/dev
terraform init
terraform plan -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

O `container_image` e os IDs de VPC/subnet em `dev.tfvars` e `prod.tfvars` estão vazios de propósito
— seriam preenchidos com valores reais no momento do primeiro apply, o que nunca aconteceu neste
projeto.
