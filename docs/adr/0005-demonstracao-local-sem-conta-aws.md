# ADR 0005 — Demonstrar o comportamento AWS-dependente sem uma conta AWS

## Contexto

Não há conta AWS disponível para este projeto e não haverá uma criada. O desafio exige, ainda assim, um `EVENT_SOURCE=s3` funcional e um comando único que sobe o ambiente de desenvolvimento de forma imediata e isolada.

## Decisão

Uma porta `EventSource` (`app/ingestion/sources.py`) com dois adapters — `LocalFileEventSource` (padrão) e `S3EventSource` (boto3) — mais dois níveis de teste para o segundo: `moto` (mock em memória da biblioteca boto3, usado nos testes automatizados) e LocalStack (serviço S3 real emulado, usado no caminho opcional `make dev-aws`).

## Por que o adapter local é o caminho padrão, não LocalStack

O `make dev` — o comando único exigido pelo desafio — usa `LocalFileEventSource` por padrão. LocalStack precisa de um daemon Docker ativo, um pull de imagem (~600MB na primeira vez) e um container saudável antes de qualquer coisa funcionar. Se o comando único dependesse disso, a primeira experiência de quem avalia o projeto poderia falhar por um motivo alheio ao código — inclusive nesta própria máquina de desenvolvimento, onde o daemon do Docker estava parado no início do projeto. `make dev` funciona com qualquer Python 3.12 instalado, sem essa dependência.

## Por que moto, não só LocalStack, para os testes automatizados

`moto` mocka a biblioteca boto3 inteiramente em memória — sem rede, sem container, roda em menos de um segundo dentro do `pytest`, e por isso mora no CI (`.github/workflows/ci.yml`). Ele prova que o *código* do adapter (paginação do `list_objects_v2`, parsing do ETag, montagem de chaves) está correto — sem essa suíte, a afirmação "o caminho do S3 está testado" seria falsa; o adapter existiria só como código nunca exercitado.

LocalStack prova uma camada diferente: que a *configuração de rede* entre containers está correta (a variável `AWS_ENDPOINT_URL`, credenciais, comunicação entre serviços do compose) — o tipo de problema que só aparece integrando peças reais. Os dois não são redundantes; testam camadas diferentes da mesma pirâmide de testes.

## O que fica provado, e o que não fica

`S3EventSource` nunca foi exercitado contra a AWS real — só contra `moto` e LocalStack. É razoável esperar ajustes de primeira execução real (limites de IAM, paginação em escala maior, latência de rede real). O ponto do design é que esse ajuste ficaria confinado à implementação do adapter — a interface `EventSource` e todo o resto do sistema (scoring, snapshot, API) permaneceriam intocados, porque nunca souberam de onde os bytes vieram.
