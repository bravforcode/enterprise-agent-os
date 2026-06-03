"""Vault tools for Graxia MCP server — 9 Obsidian vault tools."""
from __future__ import annotations
import asyncio, os, re
from pathlib import Path
from typing import Any, Dict, List
from ..shared.helpers import _ok, _err
from ..integrations.obsidian import ObsidianBridge

VAULT_PATH = Path(os.environ.get("AGENT_OS_VAULT_PATH", r"C:\Users\menum\Documents\ObsidianVault\Second Brain"))


def _bridge() -> ObsidianBridge:
    return ObsidianBridge()


def _vault_rel(path: str) -> Path:
    """Resolve a vault-relative path to absolute, blocking traversal."""
    clean = path.replace("\\", "/").lstrip("/")
    parts = Path(clean).parts
    if any(p == ".." for p in parts):
        raise ValueError("Path traversal not allowed")
    return VAULT_PATH / clean


# ---------------------------------------------------------------------------
# 1. vault_write
# ---------------------------------------------------------------------------

async def vault_write(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return _err("path is required")
    if content is None:
        return _err("content is required")

    def _do():
        full = _vault_rel(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return {"success": True, "path": path}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 2. vault_link
# ---------------------------------------------------------------------------

async def vault_link(args: Dict[str, Any]) -> Dict[str, Any]:
    source = args.get("source", "")
    target = args.get("target", "")
    link_text = args.get("link_text", "")
    if not source or not target:
        return _err("source and target are required")

    def _do():
        src = _vault_rel(source)
        if not src.exists():
            raise FileNotFoundError(f"Source note not found: {source}")
        content = src.read_text(encoding="utf-8")
        link = f"[[{target}]]" if not link_text else f"[[{target}|{link_text}]]"
        if link in content:
            return {"success": True, "links_added": 0, "reason": "link already exists"}
        content = content.rstrip() + f"\n\n{link}\n"
        src.write_text(content, encoding="utf-8")
        return {"success": True, "links_added": 1}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 3. vault_tag
# ---------------------------------------------------------------------------

async def vault_tag(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path", "")
    tags = args.get("tags", [])
    action = args.get("action", "add")
    if not path:
        return _err("path is required")
    if not tags:
        return _err("tags list is required")

    def _do():
        full = _vault_rel(path)
        if not full.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        content = full.read_text(encoding="utf-8")

        # Parse existing frontmatter
        fm_start = content.find("---")
        body = content
        fm_block = ""
        if fm_start == 0:
            fm_end = content.find("---", 3)
            if fm_end > 0:
                fm_block = content[3:fm_end].strip()
                body = content[fm_end + 3:].lstrip("\n")

        # Parse existing tags
        existing: List[str] = []
        in_tags = False
        for line in fm_block.splitlines():
            if line.strip().startswith("tags:"):
                val = line.split(":", 1)[1].strip()
                if val.startswith("["):
                    # Inline list: [tag1, tag2]
                    existing = [t.strip().strip('"').strip("'")
                                for t in val.strip("[]").split(",") if t.strip()]
                    in_tags = False
                elif val:
                    existing = [val]
                    in_tags = False
                else:
                    in_tags = True
            elif in_tags and line.startswith("  - "):
                existing.append(line.strip().lstrip("- ").strip())

        # Deduplicate: tags in frontmatter AND inline #tags in body
        body_tags = re.findall(r"#([\w\-/]+)", body)
        all_tags = list(set(existing + body_tags))

        if action == "add":
            for t in tags:
                if t not in all_tags:
                    all_tags.append(t)
        elif action == "remove":
            all_tags = [t for t in all_tags if t not in tags]
        else:
            raise ValueError(f"Unknown action: {action}")

        # Rebuild frontmatter
        new_fm_lines: List[str] = []
        replaced = False
        for line in fm_block.splitlines():
            if line.strip().startswith("tags:"):
                new_fm_lines.append("tags: " + str(all_tags))
                replaced = True
            elif not (line.startswith("  - ") and replaced):
                new_fm_lines.append(line)
        if not replaced and all_tags:
            new_fm_lines.append("tags: " + str(all_tags))

        new_content = "---\n" + "\n".join(new_fm_lines) + "\n---\n" + body
        full.write_text(new_content, encoding="utf-8")
        return {"success": True, "tags": all_tags}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 4. vault_moc
# ---------------------------------------------------------------------------

async def vault_moc(args: Dict[str, Any]) -> Dict[str, Any]:
    topic = args.get("topic", "")
    folder = args.get("folder", "MOC")
    if not topic:
        return _err("topic is required")

    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        topic_lower = topic.lower()
        topic_words = [w for w in re.split(r"\s+", topic_lower) if len(w) > 2]

        matches: List[Dict[str, str]] = []
        for note in index.values():
            score = 0
            for w in topic_words:
                if w in note.title.lower():
                    score += 5
                if w in note.content.lower():
                    score += 1
                if any(w in t.lower() for t in note.tags):
                    score += 3
            if score > 0:
                matches.append({"path": note.path, "title": note.title, "score": score})

        matches.sort(key=lambda m: m["score"], reverse=True)

        # Build MOC content
        lines = [
            f"---\ntags: [MOC, {topic}]\n---",
            f"# {topic}",
            f"",
            f"Map of Content for **{topic}** — auto-generated by Agent OS.",
            f"",
            f"## Related Notes ({len(matches)})",
            f"",
        ]
        for m in matches[:50]:
            lines.append(f"- [[{m['title']}]]")
        moc_content = "\n".join(lines)

        moc_dir = VAULT_PATH / folder
        moc_dir.mkdir(parents=True, exist_ok=True)
        moc_file = moc_dir / f"{topic}.md"
        moc_file.write_text(moc_content, encoding="utf-8")
        rel = str(moc_file.relative_to(VAULT_PATH)).replace("\\", "/")
        return {"success": True, "moc_path": rel, "notes_found": len(matches)}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 5. vault_tasks
# ---------------------------------------------------------------------------

_TASK_PATTERNS = [
    re.compile(r"-\s*\[\s*\]\s*(.+)"),          # - [ ] task
    re.compile(r"-\s*\[x\]\s*(.+)", re.I),        # - [x] task
    re.compile(r"TODO:\s*(.+)", re.I),
    re.compile(r"ACTION:\s*(.+)", re.I),
]


async def vault_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    folder = args.get("folder", "")

    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        tasks: List[Dict[str, Any]] = []
        scan_root = VAULT_PATH / folder if folder else VAULT_PATH

        for note in index.values():
            note_path = VAULT_PATH / note.path
            try:
                if not str(note_path).startswith(str(scan_root)):
                    continue
            except Exception:
                continue
            lines = note.content.splitlines()
            for i, line in enumerate(lines):
                for pat in _TASK_PATTERNS:
                    m = pat.search(line)
                    if m:
                        status = "open" if "[ ]" in line or "TODO:" in line.upper() or "ACTION:" in line.upper() else "done"
                        tasks.append({
                            "note": note.path,
                            "line": i + 1,
                            "task": m.group(1).strip()[:200],
                            "status": status,
                        })
                        break
        return {"tasks": tasks, "total": len(tasks)}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 6. vault_graph
# ---------------------------------------------------------------------------

async def vault_graph(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path", "")
    if not path:
        return _err("path is required")

    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        note_path = path.replace("\\", "/").lstrip("/")

        # Find the note
        target: Any = None
        for n in index.values():
            if n.path == note_path or n.path.rstrip(".md") == note_path.rstrip(".md"):
                target = n
                break
        if target is None:
            raise FileNotFoundError(f"Note not found: {path}")

        # Outgoing links
        links = target.links

        # Backlinks: find notes that link to this note
        backlinks: List[str] = []
        title = target.title
        for n in index.values():
            if title in n.links and n.path != target.path:
                backlinks.append(n.path)

        # Related: notes sharing tags
        related: List[str] = []
        if target.tags:
            tag_set = set(target.tags)
            for n in index.values():
                if n.path == target.path:
                    continue
                if tag_set & set(n.tags):
                    related.append(n.path)

        return {
            "note": target.path,
            "links": links,
            "backlinks": backlinks,
            "related": related[:30],
        }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 7. vault_analytics
# ---------------------------------------------------------------------------

async def vault_analytics(args: Dict[str, Any]) -> Dict[str, Any]:
    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        total_notes = len(index)
        total_links = sum(len(n.links) for n in index.values())

        # Orphans: notes with 0 incoming and 0 outgoing links
        all_titles = {n.title: n.path for n in index.values()}
        incoming: Dict[str, int] = {}
        for n in index.values():
            for link in n.links:
                incoming[link] = incoming.get(link, 0) + 1

        orphans = []
        for n in index.values():
            out_count = len(n.links)
            in_count = incoming.get(n.title, 0)
            if out_count == 0 and in_count == 0:
                orphans.append(n.path)

        # Tag frequency
        tag_freq: Dict[str, int] = {}
        for n in index.values():
            for t in n.tags:
                tag_freq[t] = tag_freq.get(t, 0) + 1
        top_tags = sorted(tag_freq.items(), key=lambda x: x[1], reverse=True)[:20]

        # Folder distribution
        folder_counts: Dict[str, int] = {}
        for n in index.values():
            folder = n.path.split("/")[0] if "/" in n.path else "(root)"
            folder_counts[folder] = folder_counts.get(folder, 0) + 1

        total_chars = sum(len(n.content) for n in index.values())

        return {
            "total_notes": total_notes,
            "total_links": total_links,
            "orphans": len(orphans),
            "orphan_examples": orphans[:10],
            "unique_tags": len(tag_freq),
            "top_tags": top_tags,
            "folder_distribution": folder_counts,
            "total_chars": total_chars,
        }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 8. vault_auto_link
# ---------------------------------------------------------------------------

async def vault_auto_link(args: Dict[str, Any]) -> Dict[str, Any]:
    dry_run = args.get("dry_run", False)

    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        incoming: Dict[str, set] = {}
        all_titles = {n.title: n.path for n in index.values()}

        for n in index.values():
            for link in n.links:
                incoming.setdefault(link, set()).add(n.path)

        fixed = 0
        orphans_remaining = 0
        changes: List[Dict[str, str]] = []

        for n in index.values():
            out_count = len(n.links)
            in_count = len(incoming.get(n.title, set()))
            if out_count == 0 and in_count == 0:
                # Try to find a related note by title word overlap
                title_words = set(w.lower() for w in re.split(r"[\s\-_]+", n.title) if len(w) > 2)
                best_match = None
                best_score = 0
                for other in index.values():
                    if other.path == n.path:
                        continue
                    other_words = set(w.lower() for w in re.split(r"[\s\-_]+", other.title) if len(w) > 2)
                    overlap = title_words & other_words
                    if len(overlap) > best_score:
                        best_score = len(overlap)
                        best_match = other

                if best_match and best_score > 0:
                    fixed += 1
                    changes.append({"note": n.path, "linked_to": best_match.path})
                    if not dry_run:
                        full = VAULT_PATH / n.path
                        content = full.read_text(encoding="utf-8", errors="ignore")
                        link = f"\n\nRelated: [[{best_match.title}]]\n"
                        full.write_text(content.rstrip() + link, encoding="utf-8")
                else:
                    orphans_remaining += 1

        return {
            "fixed": fixed,
            "orphans_remaining": orphans_remaining,
            "changes": changes if dry_run else [],
        }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 9. vault_auto_tag
# ---------------------------------------------------------------------------

_TAG_RULES: List[tuple] = [
    (re.compile(r"\b(python|pip|conda|virtualenv|pytest|django|flask)\b", re.I), "python"),
    (re.compile(r"\b(typescript|javascript|npm|node|react|vue|angular|svelte)\b", re.I), "javascript"),
    (re.compile(r"\b(docker|kubernetes|k8s|container|helm|terraform)\b", re.I), "devops"),
    (re.compile(r"\b(api|rest|graphql|endpoint|http|curl)\b", re.I), "api"),
    (re.compile(r"\b(database|sql|postgres|mysql|mongo|redis|sqlite)\b", re.I), "database"),
    (re.compile(r"\b(security|auth|jwt|oauth|encrypt|password)\b", re.I), "security"),
    (re.compile(r"\b(test|spec|mock|assert|tdd|unittest)\b", re.I), "testing"),
    (re.compile(r"\b(music|song|album|guitar|piano|melody|rhythm)\b", re.I), "music"),
    (re.compile(r"\b(health|fitness|exercise|sleep|nutrition|meditation)\b", re.I), "health"),
    (re.compile(r"\b(money|finance|budget|invest|stock|crypto|savings)\b", re.I), "finance"),
    (re.compile(r"\b(recipe|cooking|food|ingredient|meal|kitchen)\b", re.I), "recipes"),
    (re.compile(r"\b(book|reading|author|novel|summary)\b", re.I), "reading"),
    (re.compile(r"\b(learning|course|tutorial|study|education|lecture)\b", re.I), "learning"),
    (re.compile(r"\b(idea|brainstorm|concept|innovation|creative)\b", re.I), "ideas"),
    (re.compile(r"\b(project|task|todo|plan|milestone|deadline)\b", re.I), "projects"),
]


async def vault_auto_tag(args: Dict[str, Any]) -> Dict[str, Any]:
    dry_run = args.get("dry_run", False)

    def _do():
        bridge = _bridge()
        index = bridge._build_index()
        tagged = 0
        all_tags_added: List[str] = []

        for note in index.values():
            full = VAULT_PATH / note.path
            if not full.exists():
                continue
            content = full.read_text(encoding="utf-8", errors="ignore")
            body_lower = content.lower()

            new_tags: List[str] = []
            for pattern, tag in _TAG_RULES:
                if tag not in note.tags and pattern.search(body_lower):
                    new_tags.append(tag)

            if new_tags:
                all_tags_added.extend(new_tags)
                tagged += 1
                if not dry_run:
                    # Rebuild frontmatter
                    fm_start = content.find("---")
                    fm_block = ""
                    body = content
                    if fm_start == 0:
                        fm_end = content.find("---", 3)
                        if fm_end > 0:
                            fm_block = content[3:fm_end].strip()
                            body = content[fm_end + 3:].lstrip("\n")

                    existing_tags: List[str] = []
                    for line in fm_block.splitlines():
                        if line.strip().startswith("tags:"):
                            val = line.split(":", 1)[1].strip()
                            if val.startswith("["):
                                existing_tags = [t.strip().strip('"').strip("'")
                                                 for t in val.strip("[]").split(",") if t.strip()]

                    combined = list(set(existing_tags + note.tags + new_tags))
                    tag_line = "tags: " + str(combined)

                    new_fm_lines: List[str] = []
                    replaced = False
                    for line in fm_block.splitlines():
                        if line.strip().startswith("tags:"):
                            new_fm_lines.append(tag_line)
                            replaced = True
                        elif not (line.startswith("  - ") and replaced):
                            new_fm_lines.append(line)
                    if not replaced:
                        new_fm_lines.append(tag_line)

                    new_content = "---\n" + "\n".join(new_fm_lines) + "\n---\n" + body
                    full.write_text(new_content, encoding="utf-8")

        unique_added = sorted(set(all_tags_added))
        return {"tagged": tagged, "tags_added": unique_added, "total_tags_added": len(all_tags_added)}

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")
