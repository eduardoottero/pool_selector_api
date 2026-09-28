"""
Configurações da aplicação.

Centralizando aqui os parâmetros do algoritmo de scoring, isso permite alterar o comportamento de
produção sem precisar de um novo deploy, bastando uma mudança de variável de ambiente no serviço.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # servidor
    app_name: str = "pool-selector-api"
    port: int = 5050

    # fonte dos eventos: local (disco) ou s3 (boto3, real ou LocalStack)
    event_source: str = "local"
    local_events_dir: str = "data/events"
    s3_bucket: str = "spark-job-events"
    s3_prefix: str = "events/"
    aws_endpoint_url: str | None = None  # configurado para apontar ao LocalStack
    aws_region: str = "us-east-1"

    # loop de ingestão
    refresh_interval_seconds: int = 60

    # 12h: a janela de análise precisa ficar próxima da escala de
    # tempo em que a disponibilidade de spot muda para que uma AZ que piorou nas últimas horas realmente
    # puxe a nota para baixo, ao invés de ser diluída por um histórico
    # longo que ainda estava bom.
    lookback_hours: int = 12

    # algoritmo de scoring (sistema de pontos)
    weight_recent: int = 3  # peso de evento com menos de window_recent_h
    weight_mid: int = 2  # peso de evento entre window_recent_h e window_mid_h
    weight_old: int = 1  # peso de evento entre window_mid_h e lookback_hours
    window_recent_h: float = 1.0
    window_mid_h: float = 6.0
    courtesy_points: int = 5  # pontos fantasma de cada lado, evita vitória por sorte
    top_k: int = 3  # tamanho do conjunto sorteado na resposta


settings = Settings()
