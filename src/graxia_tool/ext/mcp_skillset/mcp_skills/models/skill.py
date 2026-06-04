"""Pydantic models for skill data validation."""

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SkillMetadataModel(BaseModel):
    """Skill metadata from YAML frontmatter.

    Validates the structure of skill metadata extracted from
    SKILL.md frontmatter.

    Supports both mcp-skillset native format and agentskills.io specification:
    - Native: Flat structure with category, tags at top level
    - agentskills.io: Nested metadata with license, compatibility, allowed_tools
    """

    name: str = Field(..., min_length=1, description="Skill name")
    description: str = Field(..., min_length=10, description="Skill description")
    category: str = Field(..., description="Skill category")
    tags: list[str] = Field(default_factory=list, description="Skill tags")
    dependencies: list[str] = Field(
        default_factory=list, description="Required skill dependencies"
    )
    version: str | None = Field(None, description="Skill version")
    author: str | None = Field(None, description="Skill author")

    # agentskills.io specification fields (optional)
    license: str | None = Field(None, description="License identifier (SPDX)")
    compatibility: str | None = Field(
        None, max_length=500, description="Compatibility requirements"
    )
    allowed_tools: str | None = Field(
        None, description="Space-delimited list of allowed tools"
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Nested metadata object (agentskills.io spec)"
    )


class SkillModel(BaseModel):
    """Complete skill data model with validation.

    Validates full skill structure including metadata and instructions.

    Supports both mcp-skillset native format and agentskills.io specification.
    """

    id: str = Field(..., min_length=1, description="Unique skill identifier")
    name: str = Field(..., min_length=1, description="Skill name")
    description: str = Field(..., min_length=10, description="Skill description")
    instructions: str = Field(
        ..., min_length=50, description="Full skill instructions (markdown)"
    )
    category: str = Field(..., description="Skill category")
    tags: list[str] = Field(default_factory=list, description="Skill tags")
    dependencies: list[str] = Field(
        default_factory=list, description="Required skill dependencies"
    )
    examples: list[str] = Field(default_factory=list, description="Usage examples")
    file_path: str = Field(..., description="Path to SKILL.md file")
    repo_id: str = Field(..., description="Repository identifier")
    version: str | None = Field(None, description="Skill version")
    author: str | None = Field(None, description="Skill author")

    # agentskills.io specification fields (optional)
    license: str | None = Field(None, description="License identifier (SPDX)")
    compatibility: str | None = Field(
        None, max_length=500, description="Compatibility requirements"
    )
    allowed_tools: str | None = Field(
        None, description="Space-delimited list of allowed tools"
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "pytest-skill",
                "name": "pytest",
                "description": "Professional pytest testing for Python",
                "instructions": "# Pytest Skill\n\nDetailed instructions...",
                "category": "testing",
                "tags": ["python", "pytest", "tdd"],
                "dependencies": [],
                "examples": ["Example 1", "Example 2"],
                "file_path": "/path/to/pytest/SKILL.md",
                "repo_id": "anthropics-skills",
                "version": "1.0.0",
                "author": "Test Author",
            }
        }


@dataclass
class SkillMetadata:
    """Skill metadata from YAML frontmatter.

    Supports both mcp-skillset native format and agentskills.io specification.

    Attributes:
        name: Skill name
        description: Short description
        category: Skill category (testing, debugging, refactoring, etc.)
        tags: List of tags for categorization
        dependencies: List of skill IDs this skill depends on
        version: Optional version string
        author: Optional author information
        license: Optional license identifier (SPDX format)
        compatibility: Optional compatibility requirements (max 500 chars)
        allowed_tools: Optional space-delimited list of allowed tools
    """

    name: str
    description: str
    category: str
    tags: list[str]
    dependencies: list[str]
    version: str | None = None
    author: str | None = None
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert SkillMetadata to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillMetadata":
        """Create SkillMetadata from dictionary loaded from JSON.

        Args:
            data: Dictionary with metadata fields

        Returns:
            SkillMetadata instance
        """
        return cls(
            name=data["name"],
            description=data["description"],
            category=data["category"],
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
            version=data.get("version"),
            author=data.get("author"),
            license=data.get("license"),
            compatibility=data.get("compatibility"),
            allowed_tools=data.get("allowed_tools"),
        )


@dataclass
class Skill:
    """Complete skill data model.

    Supports both mcp-skillset native format and agentskills.io specification.

    Attributes:
        id: Unique skill identifier
        name: Skill name
        description: Short description
        instructions: Full skill instructions (markdown)
        category: Skill category
        tags: List of tags
        dependencies: List of skill IDs this depends on
        examples: List of example usage scenarios
        file_path: Path to SKILL.md file
        repo_id: Repository this skill belongs to
        version: Optional version string
        author: Optional author information
        updated_at: Timestamp when skill was last modified (from file mtime)
        license: Optional license identifier (SPDX format, agentskills.io spec)
        compatibility: Optional compatibility requirements (agentskills.io spec)
        allowed_tools: Optional space-delimited list of allowed tools (agentskills.io spec)
    """

    id: str
    name: str
    description: str
    instructions: str
    category: str
    tags: list[str]
    dependencies: list[str]
    examples: list[str]
    file_path: Path
    repo_id: str
    version: str | None = None
    author: str | None = None
    updated_at: datetime | None = None
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert Skill to dictionary for JSON serialization.

        Returns:
            Dictionary with all fields, Path converted to string, datetime to ISO
        """
        data = asdict(self)
        data["file_path"] = str(self.file_path)
        if self.updated_at:
            data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        """Create Skill from dictionary loaded from JSON.

        Args:
            data: Dictionary with skill fields

        Returns:
            Skill instance
        """
        # Parse updated_at from ISO string if present
        updated_at = None
        if "updated_at" in data and data["updated_at"]:
            updated_at = datetime.fromisoformat(data["updated_at"])

        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            instructions=data["instructions"],
            category=data["category"],
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
            examples=data.get("examples", []),
            file_path=Path(data["file_path"]),
            repo_id=data["repo_id"],
            version=data.get("version"),
            author=data.get("author"),
            updated_at=updated_at,
            license=data.get("license"),
            compatibility=data.get("compatibility"),
            allowed_tools=data.get("allowed_tools"),
        )
