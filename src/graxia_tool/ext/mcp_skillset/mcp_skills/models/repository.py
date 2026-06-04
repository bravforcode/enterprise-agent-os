"""Repository data model."""

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Repository:
    """Repository metadata.

    Attributes:
        id: Unique repository identifier
        url: Git repository URL
        local_path: Path to local clone
        priority: Priority for skill selection (higher = preferred)
        last_updated: Timestamp of last update
        skill_count: Number of skills in repository
        license: Repository license (MIT, Apache-2.0, etc.)
    """

    id: str
    url: str
    local_path: Path
    priority: int
    last_updated: datetime
    skill_count: int
    license: str

    def to_dict(self) -> dict[str, Any]:
        """Convert Repository to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields, Path and datetime converted to strings
        """
        data = asdict(self)
        data["local_path"] = str(self.local_path)
        data["last_updated"] = self.last_updated.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Repository":
        """Create Repository from dictionary loaded from JSON.

        Args:
            data: Dictionary with repository fields

        Returns:
            Repository instance
        """
        return cls(
            id=data["id"],
            url=data["url"],
            local_path=Path(data["local_path"]),
            priority=data["priority"],
            last_updated=datetime.fromisoformat(data["last_updated"]),
            skill_count=data["skill_count"],
            license=data["license"],
        )
