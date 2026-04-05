import hashlib
import json
import logging
import re
from typing import Any, Optional, Dict, List
from redis.exceptions import RedisError
from app.core.cache.redis_client import get_redis
from app.core.config import settings

logger = logging.getLogger(__name__)

class CacheService:
    PREFIX_RAG = "rag"
    PREFIX_EMBEDDING = "emb"
    PREFIX_CONTENT="content"

    @staticmethod
    def _normalize_for_cache(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text)
        tokens = sorted(text.split())
        return " ".join(tokens)

    @staticmethod
    def _generate_hash_key(prefix: str, org_id: Optional[str] = None) -> str:
        if org_id:
            return f"{prefix}:{org_id}"
        return f"{prefix}:global"

    @classmethod
    def _generate_field_key(cls, raw_query: str, provider: Optional[str] = None) -> str:
        normalized = cls._normalize_for_cache(raw_query)
        key_material = f"{normalized}:{provider}" if provider else normalized
        return hashlib.sha256(key_material.encode('utf-8')).hexdigest()

    @staticmethod
    def _serialize(data: Any) -> str:
        try:
            return json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error(f"Serialization error: {e}")
            raise

    @staticmethod
    def _deserialize(data: str) -> Any:
        try:
            return json.loads(data)
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"Deserialization error: {e}")
            return None

    @classmethod
    def get_rag_response(cls, normalized_query: str, org_id: Optional[str] = None, provider: str = "gemini") -> Optional[Dict[str, Any]]:
        redis = get_redis()
        if not redis:
            logger.debug("Redis unavailable, cache miss")
            return None
        try:
            hash_key = cls._generate_hash_key(cls.PREFIX_RAG, org_id)
            field_key = cls._generate_field_key(normalized_query, provider)
            cached_value = redis.hget(hash_key, field_key)
            if cached_value:
                logger.info(f"Cache HIT - RAG (org={org_id}, provider={provider}, hash={field_key[:12]}...)")
                return cls._deserialize(cached_value)
            logger.debug(f"Cache MISS - RAG (org={org_id}, provider={provider})")
            return None
        except RedisError as e:
            logger.error(f"Redis error during RAG GET: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during RAG cache GET: {e}")
            return None

    @classmethod
    def set_rag_response(cls, normalized_query: str, response: Dict[str, Any], org_id: Optional[str] = None, provider: str = "gemini", ttl: Optional[int] = None) -> bool:
        redis = get_redis()
        if not redis:
            logger.debug("Redis unavailable, skipping RAG cache set")
            return False
        try:
            hash_key = cls._generate_hash_key(cls.PREFIX_RAG, org_id)
            field_key = cls._generate_field_key(normalized_query, provider)
            ttl = ttl or settings.REDIS_TTL_RAG
            redis.hset(hash_key, field_key, cls._serialize(response))
            redis.expire(hash_key, ttl)
            logger.info(f"Cache SET - RAG (org={org_id}, provider={provider}, hash={field_key[:12]}..., ttl={ttl}s)")
            return True
        except RedisError as e:
            logger.error(f"Redis error during RAG SET: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during RAG cache SET: {e}")
            return False

    @classmethod
    def get_embedding(cls, query: str) -> Optional[List[float]]:
        redis = get_redis()
        if not redis:
            return None
        try:
            hash_key = cls._generate_hash_key(cls.PREFIX_EMBEDDING)
            field_key = cls._generate_field_key(query)
            cached_value = redis.hget(hash_key, field_key)
            if cached_value:
                logger.info(f"Cache HIT - Embedding (hash={field_key[:12]}...)")
                return cls._deserialize(cached_value)
            logger.debug("Cache MISS - Embedding")
            return None
        except RedisError as e:
            logger.error(f"Redis error during Embedding GET: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Embedding cache GET: {e}")
            return None

    @classmethod
    def set_embedding(cls, query: str, embedding: List[float], ttl: Optional[int] = None) -> bool:
        redis = get_redis()
        if not redis:
            return False
        try:
            hash_key = cls._generate_hash_key(cls.PREFIX_EMBEDDING)
            field_key = cls._generate_field_key(query)
            ttl = ttl or settings.REDIS_TTL_EMBEDDINGS
            redis.hset(hash_key, field_key, cls._serialize(embedding))
            redis.expire(hash_key, ttl)
            logger.info(f"Cache SET - Embedding (hash={field_key[:12]}..., ttl={ttl}s)")
            return True
        except RedisError as e:
            logger.error(f"Redis error during Embedding SET: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during Embedding cache SET: {e}")
            return False

    @classmethod
    def invalidate_org(cls, org_id: str) -> bool:
        redis = get_redis()
        if not redis:
            return False
        try:
            hash_key = cls._generate_hash_key(cls.PREFIX_RAG, org_id)
            deleted = redis.delete(hash_key)
            if deleted:
                logger.info(f"Cache INVALIDATED - All RAG responses for org={org_id}")
            else:
                logger.debug(f"Cache INVALIDATE - No entries found for org={org_id}")
            return True
        except RedisError as e:
            logger.error(f"Redis error during invalidation: {e}")
            return False

    @classmethod
    def clear_all_cache(cls) -> bool:
        redis = get_redis()
        if not redis:
            return False
        try:
            pattern = f"{cls.PREFIX_RAG}:*"
            total_deleted = 0
            cursor = 0
            while True:
                cursor, keys = redis.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted = redis.delete(*keys)
                    total_deleted += deleted
                if cursor == 0:
                    break
            logger.warning(f"Cache CLEARED - Deleted {total_deleted} RAG cache entries")
            return True
        except RedisError as e:
            logger.error(f"Redis error during cache clear: {e}")
            return False

    @classmethod
    def get_cache_stats(cls, org_id: Optional[str] = None) -> Dict[str, Any]:
        redis = get_redis()
        if not redis:
            return {"available": False}
        try:
            rag_key = cls._generate_hash_key(cls.PREFIX_RAG, org_id)
            emb_key = cls._generate_hash_key(cls.PREFIX_EMBEDDING)
            rag_exists = redis.exists(rag_key)
            emb_exists = redis.exists(emb_key)
            return {
                "available": True,
                "org_id": org_id,
                "rag": {
                    "hash_key": rag_key,
                    "cached_queries": redis.hlen(rag_key) if rag_exists else 0,
                    "ttl_remaining_seconds": redis.ttl(rag_key) if rag_exists else -1,
                    "memory_bytes": redis.memory_usage(rag_key) if rag_exists else 0,
                },
                "embeddings": {
                    "hash_key": emb_key,
                    "cached_embeddings": redis.hlen(emb_key) if emb_exists else 0,
                    "ttl_remaining_seconds": redis.ttl(emb_key) if emb_exists else -1,
                    "memory_bytes": redis.memory_usage(emb_key) if emb_exists else 0,
                },
            }
        except RedisError as e:
            logger.error(f"Redis error getting stats: {e}")
            return {"available": False, "error": str(e)}
    @classmethod
    def get_content(cls, field_key: str) -> Optional[Dict[str, Any]]:
        redis = get_redis()
        if not redis:
            return None
        try:
            hash_key = f"{cls.PREFIX_CONTENT}:global"
            cached_value = redis.hget(hash_key, field_key)
            if cached_value:
                logger.info(f"Cache HIT - Content (hash={field_key[:12]}...)")
                return cls._deserialize(cached_value)
            logger.debug("Cache MISS - Content")
            return None
        except RedisError as e:
            logger.error(f"Redis error during Content GET: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Content cache GET: {e}")
            return None
 
    @classmethod
    def set_content(cls, field_key: str, response: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        redis = get_redis()
        if not redis:
            return False
        try:
            hash_key = f"{cls.PREFIX_CONTENT}:global"
            ttl = ttl or 3600  # 1 hour default
            redis.hset(hash_key, field_key, cls._serialize(response))
            redis.expire(hash_key, ttl)
            logger.info(f"Cache SET - Content (hash={field_key[:12]}..., ttl={ttl}s)")
            return True
        except RedisError as e:
            logger.error(f"Redis error during Content SET: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during Content cache SET: {e}")
            return False
cache_service = CacheService()
