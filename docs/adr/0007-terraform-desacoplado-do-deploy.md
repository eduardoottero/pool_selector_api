# ADR 0007 — Terraform desacoplado da esteira de deploy

## Contexto

O desafio pede uma estratégia de CI/CD. O fluxo desenhado tem dois
ambientes (dev/prod), branches de referência, aprovação manual e promoção
automática de dev para main via PR (ver `.github/workflows/deploy-*.yml`).
Sem conta AWS provisionada, nenhum `terraform apply` real acontece — mas a
topologia (ADR 0004) existe como código, validada no CI.

## Decisão

Duas camadas que nunca se referenciam por código: `infra/terraform/`
(provisiona a infraestrutura, roda fora do CI de aplicação) e
`.github/workflows/` (deploya a aplicação a cada merge). O único
acoplamento entre elas é um **nome**: os workflows de deploy leem
`ECS_CLUSTER`, `ECS_SERVICE` e `ECR_REPO` de `vars` do repositório GitHub —
nunca leem um arquivo `.tf`.

## Por quê

Esses três nomes poderiam ter vindo dos `outputs.tf` deste Terraform
(`infra/terraform/modules/api/outputs.tf`) ou ter sido digitados
manualmente no console da AWS — o workflow de deploy não tem como
distinguir, e não precisa. Provisionar e deployar são responsabilidades
diferentes, que mudam em cadências diferentes (infraestrutura muda
raramente; a aplicação muda a cada PR), e acoplá-las por código faria o
pipeline de deploy depender, sem necessidade, de todo o estado do
Terraform.

## Consequência prática

O pipeline de CI/CD é honesto e completo sem exigir que a pasta
`infra/terraform/` seja sequer mencionada. Numa conversa técnica, essa
camada pode ser aprofundada se for perguntada, ou deixada de fora sem que
o resto do desenho de CI/CD pareça incompleto — o discurso de "merge →
build → push da imagem → update do serviço ECS" se sustenta sozinho.

## Isolamento adicional: state por ambiente

Dentro do Terraform em si, `envs/dev` e `envs/prod` têm cada um seu
próprio `backend.tf` — arquivos de state fisicamente separados no mesmo
bucket remoto (prefixos `dev/terraform.tfstate` e `prod/terraform.tfstate`),
não apenas uma convenção de nomenclatura. Um `terraform apply` em dev não
tem como, por engano, alterar o state de prod. Ver `infra/terraform/README.md`
para a tabela completa de diferenças de capacidade entre os dois `.tfvars`.
