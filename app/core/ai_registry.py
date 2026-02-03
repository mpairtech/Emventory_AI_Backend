"""
Model registry: model name → handler. New AI feature = register one handler; no more long if-chain in ai_invoke.
"""
from typing import Callable, Any

# type: (request_input, db) -> result dict
ModelHandler = Callable[[Any, Any], dict]

_REGISTRY: dict[str, ModelHandler] = {}


def register(model: str):
    """Decorator: register a function as the handler for `model`."""
    def decorator(fn: ModelHandler):
        _REGISTRY[model] = fn
        return fn
    return decorator


def get_handler(model: str) -> ModelHandler | None:
    return _REGISTRY.get(model)


def list_models() -> list[str]:
    return list(_REGISTRY.keys())
