from typing import Annotated, Any

from fastapi import Depends
from redis import Redis
from sqlalchemy.orm import Session

from app.core.clickhouse_client import get_clickhouse_client
from app.core.database import get_db_session
from app.core.redis_client import get_redis_client

DbSession = Annotated[Session, Depends(get_db_session)]
ClickHouseClient = Annotated[Any, Depends(get_clickhouse_client)]
RedisClient = Annotated[Redis, Depends(get_redis_client)]
