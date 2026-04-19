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