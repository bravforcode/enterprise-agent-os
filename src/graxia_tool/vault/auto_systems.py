"""Vault auto-systems — ported from Obsidian vault brain/auto-systems/.

Six auto-systems that operate on an Obsidian vault:
1. VaultAutoLinker      — Find orphaned notes and create links
2. VaultAutoTagger      — Analyze content and add tags
3. VaultAutoClassifier  — Classify notes into PARA structure
4. VaultAutoDuplicateFinder — Find duplicate/similar notes
5. VaultAutoConsistencyChecker — Check vault integrity
6. VaultAutoTaskExtractor    — Extract TODOs/FIXMEs from notes
"""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VAULT_PATH = Path(os.environ.get(
    "AGENT_OS_VAULT_PATH",
    r"C:\Users\menum\Documents\ObsidianVault\Second Brain",
))


class VaultAutoLinker:
    """Find orphaned notes and create links based on content analysis."""

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH
        self.all_files: List[Path] = []
        self.orphaned_files: List[Dict[str, Any]] = []

    def scan_vault(self) -> List[Path]:
        self.all_files = list(self.vault_root.rglob("*.md"))
        return self.all_files

    def find_orphaned_files(self) -> List[Dict[str, Any]]:
        file_links: Dict[Path, Dict[str, Any]] = {}
        backlink_count: Counter = Counter()

        for file_path in self.all_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            wiki_links = set(re.findall(r'\[\[([^\]|]+)', content))
            md_links = set(re.findall(r'\[([^\]]+)\]\([^)]+\)', content))
            tags = set(re.findall(r'#([a-zA-Z0-9_-]+)', content))
            file_links[file_path] = {
                'wiki_links': wiki_links, 'md_links': md_links,
                'tags': tags, 'content': content[:5000],
            }
            for link in wiki_links:
                backlink_count[link] += 1

        self.orphaned_files = []
        for file_path in self.all_files:
            fname = file_path.stem
            links = file_links.get(file_path, {'wiki_links': set(), 'md_links': set(), 'content': ''})
            has_outgoing = bool(links['wiki_links'] or links['md_links'])
            has_incoming = backlink_count.get(fname, 0) > 0
            if not has_outgoing and not has_incoming:
                self.orphaned_files.append({
                    'path': file_path, 'name': fname,
                    'relative': str(file_path.relative_to(self.vault_root)),
                    'content': links['content'],
                })
        return self.orphaned_files

    def analyze_content(self, file_info: Dict[str, Any]) -> Tuple[List, List[Dict[str, Any]]]:
        content = file_info['content']
        name = file_info['name']
        words = re.findall(r'\b[A-Z][a-z]+\b', content)
        key_terms = Counter(words).most_common(10)

        targets: List[Dict[str, Any]] = []
        for existing in self.all_files:
            existing_name = existing.stem
            if existing_name == name:
                continue
            if existing_name.lower() in content.lower():
                targets.append({'name': existing_name, 'reason': 'name_mentioned'})
                if len(targets) >= 5:
                    break
                continue
            try:
                existing_content = existing.read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                continue
            existing_tags = set(re.findall(r'#([a-zA-Z0-9_-]+)', existing_content))
            file_tags = set(re.findall(r'#([a-zA-Z0-9_-]+)', content))
            shared = existing_tags & file_tags
            if shared:
                targets.append({'name': existing_name, 'reason': f'shared_tags:{",".join(shared)}'})
                if len(targets) >= 5:
                    break

        return key_terms, targets

    def fix_orphans(self, dry_run: bool = True, max_files: int = 50) -> Dict[str, Any]:
        self.scan_vault()
        self.find_orphaned_files()

        if not self.orphaned_files:
            return {'orphaned': 0, 'linked': 0, 'message': 'No orphaned files found.'}

        linked = 0
        changes: List[Dict[str, Any]] = []
        for file_info in self.orphaned_files[:max_files]:
            _, targets = self.analyze_content(file_info)
            if not targets:
                continue
            linked += 1
            changes.append({
                'file': file_info['relative'],
                'targets': [t['name'] for t in targets],
            })
            if not dry_run:
                try:
                    content = file_info['path'].read_text(encoding="utf-8", errors="ignore")
                    links_section = "\n\n---\n\n**Auto-Generated Links**\n\n"
                    for t in targets:
                        links_section += f"- [[{t['name']}]] - {t['reason']}\n"
                    links_section += f"\nAuto-linked: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    file_info['path'].write_text(content + links_section, encoding="utf-8")
                except Exception:
                    pass

        return {
            'orphaned': len(self.orphaned_files),
            'linked': linked,
            'dry_run': dry_run,
            'changes': changes,
        }


class VaultAutoTagger:
    """Analyze content and add tags automatically."""

    DOMAIN_TAGS: Dict[str, List[str]] = {
        'ai': ['ai', 'ml', 'machine learning', 'neural', 'gpt', 'llm', 'prompt', 'model'],
        'backend': ['api', 'server', 'database', 'fastapi', 'flask', 'django', 'sql', 'redis'],
        'frontend': ['react', 'vue', 'angular', 'html', 'css', 'tailwind', 'component', 'ui'],
        'devops': ['docker', 'kubernetes', 'k8s', 'ci/cd', 'pipeline', 'deploy', 'infrastructure'],
        'testing': ['test', 'testing', 'jest', 'pytest', 'cypress', 'e2e', 'coverage'],
        'security': ['security', 'auth', 'oauth', 'jwt', 'encrypt', 'vulnerability'],
        'data': ['data', 'analytics', 'pandas', 'numpy', 'visualization', 'chart'],
        'automation': ['automation', 'script', 'bot', 'cron', 'workflow', 'pipeline'],
        'learning': ['learning', 'course', 'tutorial', 'study', 'education', 'book'],
        'project': ['project', 'milestone', 'roadmap', 'sprint', 'kanban', 'agile'],
    }

    TECH_TAGS: Dict[str, List[str]] = {
        'python': ['python', 'pip', 'django', 'flask', 'fastapi'],
        'typescript': ['typescript', 'ts', 'tsx', 'type'],
        'javascript': ['javascript', 'js', 'node', 'npm', 'yarn'],
        'react': ['react', 'jsx', 'hooks', 'usestate', 'useeffect', 'component'],
        'rust': ['rust', 'cargo', 'ownership', 'lifetime'],
        'go': ['go', 'golang', 'goroutine', 'channel'],
        'docker': ['docker', 'container', 'image', 'dockerfile', 'compose'],
        'kubernetes': ['kubernetes', 'k8s', 'pod', 'deployment', 'helm'],
    }

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH

    def analyze_content(self, content: str, filename: str) -> List[str]:
        content_lower = content.lower()
        words = re.findall(r'\b[a-z]+\b', content_lower)
        word_freq = Counter(words)
        suggested: List[str] = []

        for domain, keywords in self.DOMAIN_TAGS.items():
            score = sum(word_freq.get(kw, 0) for kw in keywords)
            if score >= 3:
                suggested.append(domain)
                for kw in keywords:
                    if word_freq.get(kw, 0) >= 5:
                        suggested.append(kw.replace(' ', '-'))

        for tech, keywords in self.TECH_TAGS.items():
            score = sum(word_freq.get(kw, 0) for kw in keywords)
            if score >= 2:
                suggested.append(tech)

        fname_lower = filename.lower()
        for tech, keywords in self.TECH_TAGS.items():
            if any(kw in fname_lower for kw in keywords) and tech not in suggested:
                suggested.append(tech)

        if re.search(r'\bTODO\b|\bFIXME\b|\bHACK\b', content):
            suggested.append('todo')
        if re.search(r'\berror\b|\bbug\b|\bfix\b|\bexception\b', content_lower):
            suggested.append('bug')
        if re.search(r'\bidea\b|\bconcept\b|\btheory\b|\bresearch\b', content_lower):
            suggested.append('idea')
        if len(content) > 10000:
            suggested.append('comprehensive')

        seen: set = set()
        unique: List[str] = []
        for t in suggested:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[:10]

    def process_file(self, file_path: Path, dry_run: bool = True) -> Optional[Dict[str, Any]]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        existing_tags = re.findall(r'#([a-zA-Z0-9_-]+)', content)
        if len(existing_tags) >= 8:
            return None

        suggested = self.analyze_content(content, file_path.stem)
        if not suggested:
            return None

        result = {
            'file': str(file_path.relative_to(self.vault_root)),
            'existing_tags': existing_tags[:10],
            'suggested_tags': suggested,
        }

        if not dry_run:
            try:
                tag_line = "\n\n---\n\n**Auto Tags:** " + " ".join(f"#{t}" for t in suggested) + "\n"
                file_path.write_text(content + tag_line, encoding="utf-8")
            except Exception:
                pass

        return result

    def run(self, dry_run: bool = True, max_files: int = 200) -> Dict[str, Any]:
        md_files = list(self.vault_root.rglob("*.md"))
        tagged = 0
        skipped = 0
        results: List[Dict[str, Any]] = []

        for fp in md_files[:max_files]:
            result = self.process_file(fp, dry_run=dry_run)
            if result:
                tagged += 1
                results.append(result)
            else:
                skipped += 1

        return {
            'total_files': len(md_files),
            'tagged': tagged,
            'skipped': skipped,
            'dry_run': dry_run,
            'results': results[:50],
        }


class VaultAutoClassifier:
    """Classify notes into PARA structure."""

    RULES: Dict[str, Dict[str, Any]] = {
        '01-Projects': {
            'keywords': ['project', 'app', 'system', 'platform', 'build', 'deploy'],
            'auto_tag': ['project'],
        },
        '02-Areas': {
            'keywords': ['area', 'domain', 'field', 'practice', 'discipline'],
            'auto_tag': ['area'],
        },
        '03-Resources': {
            'keywords': ['resource', 'guide', 'tutorial', 'reference', 'cheatsheet'],
            'auto_tag': ['resource'],
        },
        '04-Archive': {
            'keywords': ['archive', 'old', 'deprecated', 'legacy', 'done', 'completed'],
            'auto_tag': ['archive'],
        },
        'brain/skills-universal': {
            'keywords': ['skill', 'pattern', 'workflow', 'automation'],
            'auto_tag': ['skill'],
        },
        'brain/memory': {
            'keywords': ['memory', 'context', 'session', 'preference', 'decision'],
            'auto_tag': ['memory'],
        },
        'brain/learning': {
            'keywords': ['learn', 'course', 'module', 'lesson', 'study'],
            'auto_tag': ['learning'],
        },
        'brain/analytics': {
            'keywords': ['analytics', 'metric', 'dashboard', 'report', 'stat'],
            'auto_tag': ['analytics'],
        },
    }

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH

    def analyze_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")[:3000] if file_path.suffix == '.md' else ""
        except Exception:
            return None

        rel_path = file_path.relative_to(self.vault_root)
        current_folder = str(rel_path.parent)

        for rule_name in self.RULES:
            if rule_name in current_folder:
                return None

        content_lower = content.lower()
        word_freq = Counter(re.findall(r'\b\w+\b', content_lower))

        best_category = None
        best_score = 0
        for cat_name, rules in self.RULES.items():
            score = 0
            for kw in rules.get('keywords', []):
                score += word_freq.get(kw, 0) * 10
                if kw in file_path.stem.lower():
                    score += 50
            if len(content) > 5000 and cat_name in ('03-Resources', '01-Projects'):
                score += 20
            if score > best_score:
                best_score = score
                best_category = cat_name

        if best_category and best_score >= 20:
            tags = list(self.RULES[best_category].get('auto_tag', []))
            return {
                'path': str(rel_path),
                'name': file_path.stem,
                'suggested_category': best_category,
                'confidence': min(best_score / 100, 1.0),
                'suggested_tags': tags,
            }
        return None

    def classify_batch(self, dry_run: bool = True, max_files: int = 100) -> Dict[str, Any]:
        inbox_files = list(self.vault_root.glob("00-Inbox/**/*.md"))
        root_files = list(self.vault_root.glob("*.md"))
        all_files = inbox_files + root_files

        classified = []
        for fp in all_files[:max_files]:
            result = self.analyze_file(fp)
            if result and result['suggested_category']:
                classified.append(result)

        by_category: Dict[str, List] = {}
        for c in classified:
            by_category.setdefault(c['suggested_category'], []).append(c)

        return {
            'total_files': len(all_files),
            'classified': len(classified),
            'by_category': {k: len(v) for k, v in by_category.items()},
            'dry_run': dry_run,
            'details': classified[:50],
        }


class VaultAutoDuplicateFinder:
    """Find duplicate and similar notes."""

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH

    def file_hash(self, filepath: Path) -> Optional[str]:
        try:
            h = hashlib.md5()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def scan_duplicates(self) -> Dict[str, List[str]]:
        hashes: Dict[str, List[str]] = defaultdict(list)
        for md_file in self.vault_root.rglob("*.md"):
            fh = self.file_hash(md_file)
            if fh:
                hashes[fh].append(str(md_file.relative_to(self.vault_root)))
        return {h: files for h, files in hashes.items() if len(files) > 1}

    def analyze_similar_names(self) -> Dict[str, List[str]]:
        names: Dict[str, List[str]] = defaultdict(list)
        for f in self.vault_root.rglob("*.md"):
            base = f.stem.lower().replace("-", "").replace("_", "").replace(" ", "")
            names[base].append(str(f.relative_to(self.vault_root)))
        return {k: v for k, v in names.items() if len(v) > 1}

    def run(self, dry_run: bool = True) -> Dict[str, Any]:
        exact = self.scan_duplicates()
        similar = self.analyze_similar_names()
        return {
            'exact_duplicates_groups': len(exact),
            'exact_duplicates': dict(list(exact.items())[:20]),
            'similar_names_groups': len(similar),
            'similar_names': dict(list(similar.items())[:20]),
            'dry_run': dry_run,
        }


class VaultAutoConsistencyChecker:
    """Check vault integrity: broken links, empty files, orphaned images."""

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH

    def check_broken_links(self) -> List[Dict[str, str]]:
        existing_files = set()
        for md_file in self.vault_root.rglob("*.md"):
            rel = md_file.relative_to(self.vault_root)
            existing_files.add(str(rel.with_suffix('')))
            existing_files.add(str(rel.parent / md_file.stem))
            existing_files.add(md_file.stem)

        broken = []
        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            links = re.findall(r'\[\[([^\]|]+)', content)
            for link in links:
                link_clean = link.split('#')[0].split('|')[0].strip()
                if link_clean and link_clean not in existing_files:
                    broken.append({
                        'file': str(md_file.relative_to(self.vault_root)),
                        'broken_link': link_clean,
                    })
        return broken

    def check_empty_files(self) -> List[Dict[str, Any]]:
        empty = []
        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore").strip()
                if len(content) < 50:
                    empty.append({
                        'file': str(md_file.relative_to(self.vault_root)),
                        'size': len(content),
                    })
            except Exception:
                pass
        return empty

    def check_orphaned_images(self) -> List[str]:
        images = set()
        for ext in ('png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'):
            for img in self.vault_root.rglob(f"*.{ext}"):
                images.add(img.name)

        referenced = set()
        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for img in images:
                if img in content:
                    referenced.add(img)

        return list(images - referenced)

    def check_missing_frontmatter(self) -> List[str]:
        missing = []
        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                if not content.startswith('---') and len(content) > 100:
                    missing.append(str(md_file.relative_to(self.vault_root)))
            except Exception:
                pass
        return missing

    def run(self, dry_run: bool = True) -> Dict[str, Any]:
        broken = self.check_broken_links()
        empty = self.check_empty_files()
        orphaned_img = self.check_orphaned_images()
        missing_fm = self.check_missing_frontmatter()

        return {
            'broken_links': {'count': len(broken), 'samples': broken[:20]},
            'empty_files': {'count': len(empty), 'samples': empty[:20]},
            'orphaned_images': {'count': len(orphaned_img), 'samples': orphaned_img[:20]},
            'missing_frontmatter': {'count': len(missing_fm), 'samples': missing_fm[:20]},
            'total_issues': len(broken) + len(empty) + len(orphaned_img) + len(missing_fm),
            'dry_run': dry_run,
        }


class VaultAutoTaskExtractor:
    """Extract TODOs, FIXMEs, and task items from notes."""

    TASK_PATTERNS = [
        re.compile(r'- \[ \] (.+)'),
        re.compile(r'- \[x\] (.+)', re.I),
        re.compile(r'TODO[:\s]+(.+)', re.I),
        re.compile(r'\bTODO\b[:\s]*(.+)', re.I),
        re.compile(r'\bFIXME\b[:\s]*(.+)', re.I),
        re.compile(r'\bHACK\b[:\s]*(.+)', re.I),
        re.compile(r'ACTION[:\s]+(.+)', re.I),
    ]

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_root = vault_path or VAULT_PATH

    def extract_tasks(self) -> Dict[str, List[Dict[str, Any]]]:
        tasks: Dict[str, List[Dict[str, Any]]] = {
            'urgent': [], 'pending': [], 'completed': [],
        }
        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines = content.split('\n')
            for line_num, line in enumerate(lines, 1):
                for pattern in self.TASK_PATTERNS:
                    matches = pattern.findall(line, re.IGNORECASE)
                    for match in matches:
                        task = {
                            'text': match.strip()[:200],
                            'file': str(md_file.relative_to(self.vault_root)),
                            'line': line_num,
                            'checked': '[x]' in line.lower(),
                            'priority': 'high' if 'FIXME' in line or 'URGENT' in line else 'normal',
                        }
                        if task['checked']:
                            tasks['completed'].append(task)
                        elif task['priority'] == 'high':
                            tasks['urgent'].append(task)
                        else:
                            tasks['pending'].append(task)
        return tasks

    def run(self, dry_run: bool = True) -> Dict[str, Any]:
        tasks = self.extract_tasks()
        return {
            'urgent_count': len(tasks['urgent']),
            'pending_count': len(tasks['pending']),
            'completed_count': len(tasks['completed']),
            'urgent_samples': tasks['urgent'][:10],
            'pending_samples': tasks['pending'][:10],
            'completed_samples': tasks['completed'][:10],
            'dry_run': dry_run,
        }
