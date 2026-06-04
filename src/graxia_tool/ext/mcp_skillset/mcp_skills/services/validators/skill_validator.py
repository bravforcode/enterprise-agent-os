"""Validator for skill files and data structures."""

import logging
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from mcp_skills.models.skill import Skill


logger = logging.getLogger(__name__)


class SkillValidator:
    """Validator for skill files and data structures.

    Handles all validation logic for skills including:
    - File format validation (YAML frontmatter)
    - Required field validation
    - Content length validation
    - Category validation
    - Format validation (skill IDs, paths)
    - Business rule validation
    - agentskills.io specification compliance

    Supports both mcp-skillset native format and agentskills.io specification
    with backward-compatible metadata normalization.
    """

    # Predefined skill categories
    VALID_CATEGORIES = {
        "testing",
        "debugging",
        "refactoring",
        "documentation",
        "security",
        "performance",
        "deployment",
        "architecture",
        "data-analysis",
        "code-review",
        "collaboration",
    }

    # agentskills.io specification limits
    MAX_NAME_LENGTH = 64  # chars
    MAX_DESCRIPTION_LENGTH = 1024  # chars
    MAX_COMPATIBILITY_LENGTH = 500  # chars

    def validate_skill(self, skill: Skill) -> dict[str, list[str]]:
        """Check skill structure and dependencies.

        Validates skill against structure requirements and business rules.
        Returns both critical errors (MUST fix) and warnings (SHOULD fix).

        Args:
            skill: Skill object to validate

        Returns:
            Dictionary with validation results:
            {
                "errors": ["Critical errors that prevent skill usage"],
                "warnings": ["Non-critical warnings for improvement"]
            }

        Validation Rules:
        - ERRORS (critical):
            - Missing required fields: name, description, instructions
            - Invalid YAML frontmatter
            - Description too short (<10 chars)
            - Instructions too short (<50 chars)

        - WARNINGS (non-critical):
            - Unknown category (not in VALID_CATEGORIES)
            - Missing tags
            - Missing examples in instructions
            - Unresolved dependencies (requires dependency_resolver callback)
            - agentskills.io spec compliance (name format, length limits)

        Example:
            >>> validator = SkillValidator()
            >>> result = validator.validate_skill(skill)
            >>> result["errors"]
            ['Description too short (5 chars, minimum 10)']
            >>> result["warnings"]
            ['Unknown category: invalid-cat']
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check required fields
        if not skill.name or len(skill.name.strip()) == 0:
            errors.append("Missing required field: name")

        if not skill.description or len(skill.description.strip()) < 10:
            errors.append(
                f"Description too short ({len(skill.description)} chars, minimum 10)"
            )

        if not skill.instructions or len(skill.instructions.strip()) < 50:
            errors.append(
                f"Instructions too short ({len(skill.instructions)} chars, minimum 50)"
            )

        # agentskills.io spec: Validate name format (warn only, don't break)
        if skill.name and not re.match(r"^[a-z0-9-]+$", skill.name):
            warnings.append(
                f"Name '{skill.name}' doesn't follow agentskills.io spec format. "
                "Use lowercase letters, numbers, and hyphens only (e.g., 'my-skill')"
            )

        # agentskills.io spec: Validate name length (warn only)
        if skill.name and len(skill.name) > self.MAX_NAME_LENGTH:
            warnings.append(
                f"Name too long ({len(skill.name)} chars, "
                f"agentskills.io spec recommends max {self.MAX_NAME_LENGTH} chars)"
            )

        # agentskills.io spec: Validate description length (warn only)
        if skill.description and len(skill.description) > self.MAX_DESCRIPTION_LENGTH:
            warnings.append(
                f"Description too long ({len(skill.description)} chars, "
                f"agentskills.io spec recommends max {self.MAX_DESCRIPTION_LENGTH} chars)"
            )

        # agentskills.io spec: Validate compatibility length (warn only)
        if (
            skill.compatibility
            and len(skill.compatibility) > self.MAX_COMPATIBILITY_LENGTH
        ):
            warnings.append(
                f"Compatibility field too long ({len(skill.compatibility)} chars, "
                f"agentskills.io spec max {self.MAX_COMPATIBILITY_LENGTH} chars)"
            )

        # Validate category
        if skill.category not in self.VALID_CATEGORIES:
            warnings.append(
                f"Unknown category: {skill.category}. "
                f"Valid categories: {', '.join(sorted(self.VALID_CATEGORIES))}"
            )

        # Check tags
        if not skill.tags or len(skill.tags) == 0:
            warnings.append("No tags specified. Tags improve discoverability.")

        # Check for examples in instructions (basic heuristic)
        instructions_lower = skill.instructions.lower()
        has_examples = (
            "example" in instructions_lower
            or "usage" in instructions_lower
            or "```" in skill.instructions  # Code blocks often indicate examples
        )
        if not has_examples:
            warnings.append(
                "No examples found in instructions. Consider adding usage examples."
            )

        return {"errors": errors, "warnings": warnings}

    def validate_skill_with_dependencies(
        self, skill: Skill, dependency_resolver: Callable[[str], Skill | None]
    ) -> dict[str, list[str]]:
        """Validate skill including dependency resolution.

        This is a separate method to avoid circular dependencies between
        SkillValidator and SkillManager.

        Args:
            skill: Skill object to validate
            dependency_resolver: Callable that takes a skill_id and returns a Skill or None

        Returns:
            Dictionary with validation results including dependency warnings
        """
        result = self.validate_skill(skill)

        # Validate dependencies (check if they can be resolved)
        if skill.dependencies:
            for dep_id in skill.dependencies:
                # Check if dependency exists using the provided resolver
                dep_skill = dependency_resolver(dep_id)
                if not dep_skill:
                    result["warnings"].append(f"Unresolved dependency: {dep_id}")

        return result

    def split_frontmatter(self, content: str) -> tuple[str, str]:
        """Split SKILL.md content into frontmatter and instructions.

        Expected format:
        ---
        name: skill-name
        description: Brief description
        ---

        # Instructions
        Markdown content...

        Args:
            content: Full file content

        Returns:
            Tuple of (frontmatter_yaml, instructions_markdown)
        """
        # Match YAML frontmatter between --- markers
        frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if match:
            return match.group(1), match.group(2)

        # No frontmatter found
        return "", content

    def parse_frontmatter(self, file_path: Path) -> dict | None:
        """Parse YAML frontmatter from SKILL.md file.

        This is a faster alternative to full file parsing when only
        metadata is needed.

        Args:
            file_path: Path to SKILL.md file

        Returns:
            Dictionary with frontmatter data or None if parsing fails
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            frontmatter, _ = self.split_frontmatter(content)

            if not frontmatter:
                return None

            metadata = yaml.safe_load(frontmatter)
            return metadata if isinstance(metadata, dict) else None

        except (yaml.YAMLError, OSError) as e:
            logger.error(f"Failed to parse frontmatter from {file_path}: {e}")
            return None

    def normalize_skill_id(self, skill_id: str) -> str:
        """Normalize skill ID to lowercase with hyphens.

        Args:
            skill_id: Raw skill ID from file path

        Returns:
            Normalized skill ID (lowercase, special chars replaced)

        Examples:
            "Anthropics/Testing/PyTest" -> "anthropics/testing/pytest"
            "My Skill!" -> "my-skill"
        """
        # Convert to lowercase
        normalized = skill_id.lower()

        # Replace special characters (except /) with hyphens
        normalized = re.sub(r"[^a-z0-9/]", "-", normalized)

        # Remove consecutive hyphens
        normalized = re.sub(r"-+", "-", normalized)

        # Remove leading/trailing hyphens
        normalized = normalized.strip("-")

        return normalized

    def extract_examples(self, instructions: str) -> list[str]:
        """Extract examples from skill instructions.

        Looks for sections like:
        - ## Examples
        - ## Example Usage
        - Code blocks (```)

        Args:
            instructions: Skill instructions markdown

        Returns:
            List of example strings (empty if none found)

        Performance Note:
        - This is a basic heuristic extraction
        - For more sophisticated parsing, consider using markdown AST
        - Current implementation is fast enough for <100KB files
        """
        examples: list[str] = []

        # Look for "Examples" section (case-insensitive)
        examples_pattern = r"##\s+Examples?\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(examples_pattern, instructions, re.IGNORECASE | re.DOTALL)

        if match:
            examples_text = match.group(1).strip()
            if examples_text:
                examples.append(examples_text)

        # Also extract code blocks as examples
        code_block_pattern = r"```[\w]*\n(.*?)\n```"
        code_blocks = re.findall(code_block_pattern, instructions, re.DOTALL)

        # Limit to first 3 code blocks to avoid bloat
        examples.extend(code_blocks[:3])

        return examples

    def normalize_frontmatter(self, frontmatter: dict) -> dict:
        """Normalize frontmatter to support both mcp-skillset and agentskills.io formats.

        Handles two format styles:
        1. mcp-skillset native (flat): tags, version, author at top level
        2. agentskills.io spec (nested): tags, version, author in metadata object

        This method merges both formats, preserving all fields and ensuring
        backward compatibility with existing skills.

        Args:
            frontmatter: Dictionary parsed from YAML frontmatter

        Returns:
            Normalized dictionary with all fields at top level

        Example:
            >>> # agentskills.io format
            >>> frontmatter = {
            ...     "name": "test-skill",
            ...     "description": "Test description",
            ...     "metadata": {"version": "1.0", "tags": ["test"]}
            ... }
            >>> normalized = validator.normalize_frontmatter(frontmatter)
            >>> normalized["version"]
            '1.0'
            >>> normalized["tags"]
            ['test']

            >>> # mcp-skillset native format (no change needed)
            >>> frontmatter = {
            ...     "name": "test-skill",
            ...     "description": "Test description",
            ...     "version": "1.0",
            ...     "tags": ["test"]
            ... }
            >>> normalized = validator.normalize_frontmatter(frontmatter)
            >>> normalized["version"]
            '1.0'
        """
        # Start with copy of original frontmatter
        normalized = frontmatter.copy()

        # If nested metadata object exists, flatten it
        if "metadata" in frontmatter and isinstance(frontmatter["metadata"], dict):
            nested_metadata = frontmatter["metadata"]

            # Merge nested fields into top level (only if not already present)
            for key, value in nested_metadata.items():
                if key not in normalized:
                    normalized[key] = value

            # Remove the nested metadata object (we've flattened it)
            normalized.pop("metadata", None)

        # Ensure lists for array fields (agentskills.io may use strings)
        if "tags" in normalized and isinstance(normalized["tags"], str):
            normalized["tags"] = [normalized["tags"]]

        if "dependencies" in normalized and isinstance(normalized["dependencies"], str):
            normalized["dependencies"] = [normalized["dependencies"]]

        return normalized
