"""
Redis client singleton for caching operations.
Supports hash-based caching with automatic serialization/deserialization.
"""

import json
import logging
from typing import Any, Optional
import redis
from redis.connection import ConnectionPool
from redis.exceptions import RedisError, ConnectionError, TimeoutError
from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Singleton Redis client with connection pooling.
    Thread-safe and handles connection failures gracefully.
    """
    
    _instance: Optional["RedisClient"] = None
    _pool: Optional[ConnectionPool] = None
    _client: Optional[redis.Redis] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Redis connection pool (called once)."""
        if self._pool is None:
            self._initialize_pool()
    
    def _initialize_pool(self):
        """Create Redis connection pool with configured settings."""
        try:
            self._pool = ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
                decode_responses=True,  # Auto decode bytes to strings
            )
            self._client = redis.Redis(connection_pool=self._pool)
            # Test connection
            self._client.ping()
            logger.info(
                f"Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
            )
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection failed: {e}")
            self._client = None
            self._pool = None
        except Exception as e:
            logger.error(f"Unexpected Redis initialization error: {e}")
            self._client = None
            self._pool = None
    
    @property
    def is_available(self) -> bool:
        """Check if Redis is available and responding."""
        if not settings.REDIS_ENABLED:
            return False
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except RedisError:
            return False
    
    def get_client(self) -> Optional[redis.Redis]:
        """Get Redis client instance. Returns None if unavailable."""
        if not self.is_available:
            return None
        return self._client
    
    def close(self):
        """Close Redis connections (call on app shutdown)."""
        if self._pool:
            self._pool.disconnect()
            logger.info("Redis connection pool closed")


# Singleton instance
redis_client = RedisClient()


def get_redis() -> Optional[redis.Redis]:
    """
    Dependency injection helper for FastAPI routes.
    Returns None if Redis is disabled or unavailable.
    """
    return redis_client.get_client()