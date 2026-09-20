# Makefile — porta de entrada única do projeto.
#
# Por que existe: o requisito do desafio é "um único comando" sobe tudo,
# isolado, sem exigir Docker (que depende de um daemon que pode estar
# parado na máquina do avaliador). `make dev` resolve isso com Poetry.
#
# Armadilha de ambiente que este Makefile evita: nesta máquina o comando
# `python3` "puro" resolve para um shim do pyenv apontando para 3.9.18,
# que viola o requisito do desafio (Python > 3.9 "de verdade", e nossas
# dependências pedem >=3.12). Por isso fixamos o interpretador explicitamente
# via `poetry env use`, em vez de deixar o Poetry adivinhar.

PYTHON := /opt/homebrew/bin/python3.12
PORT := 5050

.PHONY: dev install seed reseed serve test lint verify clean dev-aws docker-down

dev: install seed serve

install:
	@echo "→ fixando o interpretador do Poetry em $(PYTHON) (evita o pyenv 3.9.18)"
	poetry env use $(PYTHON)
	poetry install

seed:
	@echo "→ gerando dataset sintético em data/events/ (se ainda não existir)"
	@if [ -z "$$(find data/events -name '*.jsonl' -print -quit 2>/dev/null)" ]; then \
		poetry run python -m app.tools.generate_events --out data/events --hours 48 --seed 42; \
	else \
		echo "  dataset já existe, pulando geração (use 'make reseed' para forçar)"; \
	fi

reseed:
	rm -f data/events/*/*.jsonl
	poetry run python -m app.tools.generate_events --out data/events --hours 48 --seed 42

serve:
	poetry run uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	poetry run pytest --cov=app --cov-report=term-missing

lint:
	poetry run ruff check app tests
	poetry run ruff format --check app tests
	poetry run mypy app

verify:
	@curl -s http://localhost:$(PORT)/health | poetry run python -m json.tool

dev-aws: seed
	@echo "→ subindo LocalStack (emula S3) + seeder + API via Docker Compose"
	@echo "  requer o daemon do Docker rodando — este é o caminho OPCIONAL de"
	@echo "  demonstração do adapter S3; make dev (sem Docker) continua sendo"
	@echo "  o caminho padrão de desenvolvimento"
	docker compose --profile aws up --build

docker-down:
	docker compose --profile aws down -v

clean:
	rm -rf data/events/*/*.jsonl .venv
