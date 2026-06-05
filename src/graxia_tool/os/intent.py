"""Intent routing — re-exports from core."""
from ..core.intent_router import classify_intent, ClassifiedIntent, Intent

__all__ = ["classify_intent", "ClassifiedIntent", "Intent"]
