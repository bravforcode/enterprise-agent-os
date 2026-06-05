"""Pipeline orchestration — re-exports from top-level pipeline (lazy)."""
try:
    from ..pipeline import EndToEndPipeline as Pipeline
except (ImportError, AttributeError):
    Pipeline = None
__all__ = ["Pipeline"]
