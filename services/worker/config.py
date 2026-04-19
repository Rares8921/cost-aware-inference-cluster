from pydantic_settings import BaseSettings


class WorkerConfig(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    scheduler_url: str = "http://localhost:8001"

    worker_id: str = ""
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"

    model_name: str = "distilbert-base-uncased"
    model_version: str = "v1"

    batch_size_max: int = 32
    batch_timeout_ms: float = 50

    worker_warm_pool: bool = True
    heartbeat_interval_seconds: int = 5
    poll_interval_ms: int = 10

    max_requests_per_worker: int = 10000

    class Config:
        env_file = ".env"
