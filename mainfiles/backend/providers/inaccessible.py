"""
Inaccessible model tracking - models that returned 404 during streaming.
"""
from typing import Any

# Global set of model IDs (litellm format) confirmed inaccessible
_inaccessible_models: set[str] = set()


def track_inaccessible(litellm_id: str) -> None:
    """Mark a model as inaccessible (returned 404/NotFound)."""
    _inaccessible_models.add(litellm_id)


def is_inaccessible(litellm_id: str) -> bool:
    """Check if a model is in the inaccessible set."""
    return litellm_id in _inaccessible_models


def filter_inaccessible(models: list[Any], get_litellm_id) -> list[Any]:
    """Filter out inaccessible models from a list."""
    return [m for m in models if not is_inaccessible(get_litellm_id(m))]


def clear_inaccessible() -> int:
    """Clear the inaccessible set and return count of removed models."""
    count = len(_inaccessible_models)
    _inaccessible_models.clear()
    return count


def get_inaccessible_count() -> int:
    """Get count of currently inaccessible models."""
    return len(_inaccessible_models)