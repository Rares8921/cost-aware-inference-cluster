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
