"""
app/core/dependencies.py
=========================
FastAPI dependency providers for shared resources.

Provides singleton instances of JobStore and StorageClient via FastAPI's
Depends() system. Adding new shared dependencies here keeps routers clean
and makes testing easy — swap implementations in one place.
"""

from __future__ import annotations

from functools import lru_cache

from app.modules.images.job_store import JobStore
from app.modules.images.storage_client import StorageClient


@lru_cache(maxsize=1)
def _job_store_singleton() -> JobStore:
    return JobStore()


@lru_cache(maxsize=1)
def _storage_client_singleton() -> StorageClient:
    return StorageClient()


def get_job_store() -> JobStore:
    """
    FastAPI dependency — returns the shared JobStore instance.

    Usage:
        job_store: JobStore = Depends(get_job_store)
    """
    return _job_store_singleton()


def get_storage_client() -> StorageClient:
    """
    FastAPI dependency — returns the shared StorageClient instance.

    Usage:
        storage: StorageClient = Depends(get_storage_client)
    """
    return _storage_client_singleton()