from pydantic_settings import BaseSettings


class SchedulerConfig(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    host: str = "0.0.0.0"
    port: int = 8001
    log_level: str = "INFO"

    autoscale_enabled: bool = True
    autoscale_interval_seconds: int = 10

    min_workers: int = 2
    max_workers: int = 10
    warm_pool_size: int = 2

    target_queue_depth: int = 50
    target_p95_latency_ms: float = 50.0
    max_p99_latency_ms: float = 100.0

    cost_per_gpu_hour: float = 2.5
    max_cost_per_hour: float = 20.0

    scale_up_threshold: float = 0.8
    scale_down_threshold: float = 0.3
    scale_cooldown_seconds: int = 60

    class Config:
        env_file = ".env"
