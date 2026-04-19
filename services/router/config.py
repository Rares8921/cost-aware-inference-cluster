from pydantic_settings import BaseSettings


class RouterConfig(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    scheduler_url: str = "http://localhost:8001"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    default_tenant_quota_per_second: int = 100
    default_tenant_quota_per_minute: int = 5000
    default_tenant_quota_per_hour: int = 50000

    noisy_neighbor_threshold: float = 0.5

    class Config:
        env_file = ".env"
