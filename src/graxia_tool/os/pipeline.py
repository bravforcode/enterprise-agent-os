"""Pipeline orchestration — re-exports from top-level pipeline (lazy)."""
try:
    from ..pipeline import Pipeline
except (ImportError, AttributeError):
    Pipeline = None  # lazy — will fail at call time if database_pool_size missing
__all__ = ["Pipeline"]
