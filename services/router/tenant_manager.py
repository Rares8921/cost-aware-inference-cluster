import time
from typing import Dict, Optional
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class TenantConfig:
    def __init__(
        self,
        tenant_id: str,
        quota_per_second: int,
        quota_per_minute: int,
        quota_per_hour: int,
        priority: int = 0,
    ):
        self.tenant_id = tenant_id
        self.quota_per_second = quota_per_second
        self.quota_per_minute = quota_per_minute
        self.quota_per_hour = quota_per_hour
        self.priority = priority


class TenantManager:
    def __init__(
            self,
            redis_url: str,
            default_quota_per_second: int,
            default_quota_per_minute: int,
            default_quota_per_hour: int,
    ):
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None

        self.default_quota_per_second = default_quota_per_second
        self.default_quota_per_minute = default_quota_per_minute
        self.default_quota_per_hour = default_quota_per_hour

        self._tenant_configs: Dict[str, TenantConfig] = {}

    async def connect(self):
        self.redis = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("tenant_manager_connected")

    async def disconnect(self):
        if self.redis:
            await self.redis.close()

    def get_tenant_config(self, tenant_id: str) -> TenantConfig:
        if tenant_id not in self._tenant_configs:
            self._tenant_configs[tenant_id] = TenantConfig(
                tenant_id=tenant_id,
                quota_per_second=self.default_quota_per_second,
                quota_per_minute=self.default_quota_per_minute,
                quota_per_hour=self.default_quota_per_hour,
                priority=0,
            )
        return self._tenant_configs[tenant_id]

    async def get_tenant_metrics(self, tenant_id: str) -> Dict:
        current_time = time.time()

        second_key = f"ratelimit:{tenant_id}:second:{int(current_time)}"
        minute_key = f"ratelimit:{tenant_id}:minute:{int(current_time / 60)}"
        hour_key = f"ratelimit:{tenant_id}:hour:{int(current_time / 3600)}"

        second_count = await self.redis.get(second_key) or 0
        minute_count = await self.redis.get(minute_key) or 0
        hour_count = await self.redis.get(hour_key) or 0

        config = self.get_tenant_config(tenant_id)

        return {
            "tenant_id": tenant_id,
            "current_second": int(second_count),
            "current_minute": int(minute_count),
            "current_hour": int(hour_count),
            "quota_second": config.quota_per_second,
            "quota_minute": config.quota_per_minute,
            "quota_hour": config.quota_per_hour,
            "utilization_second": int(second_count) / config.quota_per_second,
            "utilization_minute": int(minute_count) / config.quota_per_minute,
            "utilization_hour": int(hour_count) / config.quota_per_hour,
        }
