"""Enterprise Agent OS — Skills module."""
from .registry import SkillDefinition, SkillRegistry

__all__ = ["SkillDefinition", "SkillRegistry", "get_default_registry"]


_default_registry: SkillRegistry | None = None


def get_default_registry() -> SkillRegistry:
    """Get or create the default skill registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry()
        _default_registry.load_all()
    return _default_registry


def list_skills() -> list[dict]:
    """List all available skills as dicts."""
    registry = get_default_registry()
    return [
        {
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "tags": s.tags or [],
        }
        for s in registry.list_skills()
    ]


def load_skill(name: str) -> dict | None:
    """Load a specific skill by name."""
    registry = get_default_registry()
    skill = registry.get_skill(name)
    if skill is None:
        return None
    return {
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "content": skill.content,
        "tags": skill.tags or [],
    }
