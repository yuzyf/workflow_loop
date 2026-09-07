"""受管正式 Markdown 文档的本地链接检查与受控定位修复。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Callable, Iterable
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from .artifact_paths import managed_artifact_paths
from .project import load_project
from .state import load_state


TRANSACTION_DIR = ".workflow_loop/link_repair"
MANIFEST_FILE = "transaction.json"


@dataclass(frozen=True, order=True)
class MarkdownLink:
    source: str
    line: int
    href: str


@dataclass(frozen=True, order=True)
class LinkIssue:
    source: str
    line: int
    href: str
    target: str
    reason: str

    def render(self) -> str:
        return (
            f"来源 {self.source}:{self.line}；链接 {self.href!r}；"
            f"目标 {self.target or '无法确定'}；原因：{self.reason}"
        )


@dataclass(frozen=True)
class LinkScanResult:
    links: tuple[MarkdownLink, ...]
    issues: tuple[LinkIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True, order=True)
class AnchorRepair:
    source: str
    line: int
    href: str
    target: str
    fragment: str
    heading_line: int


@dataclass(frozen=True)
class RepairPlan:
    preview_hash: str
    file_hashes: tuple[tuple[str, str], ...]
    repairs: tuple[AnchorRepair, ...]
    unresolved: tuple[LinkIssue, ...]


@dataclass(frozen=True)
class LinkRepairResult:
    success: bool
    repaired_files: tuple[str, ...]
    detail: str
    unresolved: tuple[LinkIssue, ...] = ()


class LinkRepairError(RuntimeError):
    """历史链接修复未能整批完成，并且已经尝试恢复原文。"""


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._collect(attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._collect(attrs)

    def _collect(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() == "id" and value is not None:
                self.ids.append(value)


def _parser() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": True})


class _DocumentCache:
    """一次检查内共享文件内容和解析结果；写入复查仍独立核对磁盘字节。"""

    def __init__(self, project_root: str) -> None:
        self.root = Path(project_root)
        self.raw: dict[str, bytes] = {}
        self.errors: dict[str, OSError] = {}
        self.parsed: dict[str, list] = {}

    def read(self, relative: str) -> bytes:
        if relative in self.errors:
            raise self.errors[relative]
        if relative not in self.raw:
            try:
                self.raw[relative] = (self.root / relative).read_bytes()
            except OSError as exc:
                self.errors[relative] = exc
                raise
        return self.raw[relative]

    def content(self, relative: str) -> str:
        return self.read(relative).decode("utf-8")

    def tokens(self, relative: str) -> list:
        if relative not in self.parsed:
            self.parsed[relative] = _parser().parse(self.content(relative))
        return self.parsed[relative]

    def overlay(self, contents: dict[str, str]) -> _DocumentCache:
        result = _DocumentCache(str(self.root))
        result.raw = self.raw.copy()
        result.errors = self.errors.copy()
        result.parsed = self.parsed.copy()
        for relative, content in contents.items():
            raw = content.encode("utf-8")
            if result.raw.get(relative) != raw:
                result.parsed.pop(relative, None)
            result.errors.pop(relative, None)
            result.raw[relative] = raw
        return result


def _sha256_bytes(content: bytes) -> str:
    return sha256(content).hexdigest()


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _managed_existing_markdown(
    project_root: str,
    source_paths: Iterable[str] | None = None,
) -> list[str]:
    project = load_project(project_root)
    state = load_state(project_root)
    result: list[str] = []
    managed = managed_artifact_paths(project, state, project_root)
    if source_paths is not None:
        requested = {
            PurePosixPath(str(path).replace("\\", "/")).as_posix()
            for path in source_paths
            if isinstance(path, str) and path.strip()
        }
        managed = [relative for relative in managed if relative in requested]
    for relative in managed:
        if not relative.lower().endswith(".md"):
            continue
        full = os.path.join(project_root, relative)
        if os.path.isfile(full) and not os.path.islink(full):
            result.append(PurePosixPath(relative).as_posix())
    return sorted(set(result))


def _token_links(content: str, source: str, tokens: list | None = None) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    lines = content.splitlines()
    for token in tokens if tokens is not None else _parser().parse(content):
        if token.type != "inline" or not token.children:
            continue
        start = token.map[0] if token.map else 0
        raw_destinations = [
            (match.group(1) or match.group(2) or "").replace("\\)", ")")
            for match in re.finditer(
                r"(?<!!)\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|((?:\\.|[^)\s])+))",
                token.content,
            )
        ]
        raw_index = 0
        for child in token.children:
            if child.type != "link_open":
                continue
            parsed_href = child.attrGet("href") or ""
            href = parsed_href
            while raw_index < len(raw_destinations):
                candidate = raw_destinations[raw_index]
                raw_index += 1
                if unquote(candidate) == unquote(parsed_href):
                    href = candidate
                    break
            line = start + 1
            for offset, text in enumerate(lines[start : token.map[1] if token.map else start + 1]):
                if href in text or unquote(href) in text:
                    line = start + offset + 1
                    break
            links.append(MarkdownLink(source=source, line=line, href=href))
    return links


def _explicit_ids(content: str, tokens: list | None = None) -> tuple[str, ...]:
    collector = _IdCollector()
    for token in tokens if tokens is not None else _parser().parse(content):
        if token.type in {"html_block", "html_inline"}:
            collector.feed(token.content)
        if token.type == "inline" and token.children:
            for child in token.children:
                if child.type == "html_inline":
                    collector.feed(child.content)
    return tuple(collector.ids)


def _has_symlink_component(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _local_target(
    project_root: str, link: MarkdownLink
) -> tuple[str | None, str | None, str | None]:
    parsed = urlsplit(link.href)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() == "file":
            return None, parsed.path, "不允许绝对本地路径或 file: 链接"
        return None, None, None
    raw_path = unquote(parsed.path)
    fragment = unquote(parsed.fragment)
    if not raw_path:
        relative = link.source
    else:
        if raw_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[/\\]", raw_path):
            return None, raw_path, "本地目标必须使用项目内相对路径"
        source_dir = PurePosixPath(link.source).parent
        relative = PurePosixPath(source_dir, raw_path).as_posix()

    root = Path(project_root).absolute()
    lexical = Path(os.path.abspath(os.path.join(root, relative)))
    try:
        normalized = lexical.relative_to(root).as_posix()
    except ValueError:
        return None, relative, "本地目标越出项目根目录"
    if _has_symlink_component(root, lexical):
        return None, normalized, "本地目标经过符号链接"
    return normalized, fragment, None


def scan_managed_markdown_links(
    project_root: str,
    *,
    content_overrides: dict[str, str] | None = None,
    source_paths: Iterable[str] | None = None,
) -> LinkScanResult:
    """扫描现有受管文档，并一次返回全部本地链接问题。"""

    documents = _DocumentCache(project_root).overlay(content_overrides or {})
    return _scan_links(project_root, documents, content_overrides, source_paths)


def _scan_links(
    project_root: str,
    documents: _DocumentCache,
    content_overrides: dict[str, str] | None = None,
    source_paths: Iterable[str] | None = None,
) -> LinkScanResult:

    links: list[MarkdownLink] = []
    issues: list[LinkIssue] = []
    ids: dict[str, Counter] = {}
    for source in _managed_existing_markdown(project_root, source_paths):
        try:
            content = documents.content(source)
            source_tokens = documents.tokens(source)
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(
                LinkIssue(source, 1, "", source, f"受管 Markdown 文档无法读取：{exc}")
            )
            continue
        for link in _token_links(content, source, source_tokens):
            target, fragment, path_error = _local_target(project_root, link)
            if target is None and path_error is None:
                continue
            links.append(link)
            if path_error is not None:
                issues.append(LinkIssue(link.source, link.line, link.href, target or "", path_error))
                continue
            assert target is not None
            full_target = Path(project_root, target)
            if target in (content_overrides or {}):
                target_exists = True
            else:
                target_exists = full_target.is_file() and not full_target.is_symlink()
            if not target_exists:
                issues.append(LinkIssue(link.source, link.line, link.href, target, "目标不是现有普通文件"))
                continue
            if fragment:
                try:
                    if target not in ids:
                        target_content = documents.content(target)
                        ids[target] = Counter(_explicit_ids(target_content, documents.tokens(target)))
                except (OSError, UnicodeDecodeError) as exc:
                    issues.append(
                        LinkIssue(
                            link.source,
                            link.line,
                            link.href,
                            target,
                            f"带定位的目标无法作为 UTF-8 Markdown 文档读取：{exc}",
                        )
                    )
                    continue
                count = ids[target][fragment]
                if count != 1:
                    reason = "缺少完全一致的显式 HTML id" if count == 0 else f"显式 HTML id 重复 {count} 次"
                    issues.append(LinkIssue(link.source, link.line, link.href, target, reason))

    return LinkScanResult(
        links=tuple(sorted(set(links))),
        issues=tuple(sorted(set(issues))),
    )


def validate_managed_markdown_links(
    project_root: str,
    *,
    source_paths: Iterable[str] | None = None,
) -> tuple[bool, str]:
    """返回适合门禁展示的稳定、一次聚合链接校验结果。"""

    result = scan_managed_markdown_links(project_root, source_paths=source_paths)
    if result.ok:
        return True, f"受管正式文档本地链接可导航：已检查 {len(result.links)} 个链接"
    detail = "\n".join(
        f"{index}. {issue.render()}" for index, issue in enumerate(result.issues, start=1)
    )
    return False, f"受管正式文档存在 {len(result.issues)} 个链接问题：\n{detail}"


def _heading_anchor_ids(text: str) -> set[str]:
    normalized = re.sub(r"[^\w\u3400-\u9fff -]+", "", text.lower())
    slug = re.sub(r"[\s-]+", "-", normalized).strip("-")
    first_id = re.match(r"([A-Za-z]+-\d+)", text)
    candidates = {slug} if slug else set()
    if first_id:
        candidates.add(first_id.group(1).lower())
    return candidates


def _heading_candidates(content: str, fragment: str, tokens: list | None = None) -> list[int]:
    matches: list[int] = []
    tokens = tokens if tokens is not None else _parser().parse(content)
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open" or token.map is None:
            continue
        inline = tokens[index + 1]
        if inline.type != "inline":
            continue
        text = inline.content.strip()
        candidates = _heading_anchor_ids(text)
        if fragment.lower() in candidates:
            matches.append(token.map[0] + 1)
    return matches


def _standard_heading_anchors(content: str, tokens: list) -> dict[int, str]:
    headings = [
        (token.map[0], _heading_anchor_ids(tokens[index + 1].content.strip()))
        for index, token in enumerate(tokens[:-1])
        if token.type == "heading_open" and token.map is not None
        and tokens[index + 1].type == "inline"
    ]
    counts = Counter(anchor for _, anchors in headings for anchor in anchors)
    ids = Counter(_explicit_ids(content, tokens))
    html_lines = {
        line for token in tokens if token.map and (token.type == "html_block" or
        (token.type == "inline" and any(child.type == "html_inline" for child in token.children or [])))
        for line in range(*token.map)
    }
    lines = content.splitlines(keepends=True)
    anchors: dict[int, str] = {}
    for heading_line, candidates in headings:
        line = heading_line - 1
        while line >= 0:
            match = re.fullmatch(r'[ \t]*<a id="([^"]+)"></a>[ \t]*(?:\r?\n)?', lines[line])
            if match is None or line not in html_lines:
                break
            anchor = match.group(1)
            if anchor.lower() in candidates and counts[anchor.lower()] == 1 and ids[anchor] == 1:
                anchors[line] = anchor
            line -= 1
    return anchors


def with_heading_anchors(content: str, *, previous_content: str = "") -> str:
    """生成与历史修复同源的唯一标题定位；已有显式定位不重复插入。"""
    tokens = _parser().parse(content)
    headings = [
        (token.map[0], _heading_anchor_ids(tokens[index + 1].content.strip()))
        for index, token in enumerate(tokens[:-1])
        if token.type == "heading_open" and token.map is not None
        and tokens[index + 1].type == "inline"
    ]
    counts = Counter(anchor for _, anchors in headings for anchor in anchors)
    existing = set(_explicit_ids(content, tokens))
    aliases = set(_standard_heading_anchors(previous_content, _parser().parse(previous_content)).values()) if previous_content else set()
    lines = content.splitlines(keepends=True)
    # 文档第一个标题（正式文档标题行）不插独立锚点行：正式文件标识登记把首行当标题解析，
    # 标题前的独立锚点行会让标识推导出错（2026-09-07 缺陷复现环节实测）。
    body_headings = headings[1:]
    for line, anchors in reversed(body_headings):
        candidates = anchors | {alias for alias in aliases if alias.lower() in anchors}
        additions = sorted(anchor for anchor in candidates if counts[anchor.lower()] == 1 and anchor not in existing)
        if additions:
            lines.insert(line, "".join(f'<a id="{anchor}"></a>\n' for anchor in additions))
            existing.update(additions)
    return "".join(lines)


def without_generated_anchors(content: str) -> str:
    """仅忽略能唯一对应现有标题的标准定位，正文或未知定位仍参与手改检查。"""
    tokens = _parser().parse(content)
    anchors = _standard_heading_anchors(content, tokens)
    return "".join(line for index, line in enumerate(content.splitlines(keepends=True)) if index not in anchors)


def _repair_file_hashes(project_root: str, scan: LinkScanResult, documents: _DocumentCache) -> tuple[tuple[str, str], ...]:
    paths = set(_managed_existing_markdown(project_root))
    for link in scan.links:
        target, _fragment, error = _local_target(project_root, link)
        if target is not None and error is None and Path(project_root, target).is_file():
            paths.add(target)
    return tuple(
        (relative, _sha256_bytes(documents.read(relative)))
        for relative in sorted(paths)
    )


def _plan_payload(
    file_hashes: tuple[tuple[str, str], ...],
    repairs: tuple[AnchorRepair, ...],
    unresolved: tuple[LinkIssue, ...],
) -> dict:
    return {
        "file_hashes": list(file_hashes),
        "repairs": [asdict(item) for item in repairs],
        "unresolved": [asdict(item) for item in unresolved],
    }


def plan_legacy_anchor_repairs(project_root: str) -> RepairPlan:
    """只读规划能够唯一对应到旧式隐式标题定位的修复。"""

    return _plan_repairs(project_root, _DocumentCache(project_root))


def _plan_repairs(project_root: str, documents: _DocumentCache) -> RepairPlan:

    scan = _scan_links(project_root, documents)
    repairs: list[AnchorRepair] = []
    unresolved: list[LinkIssue] = []
    candidates: dict[tuple[str, str], list[int]] = {}
    for issue in scan.issues:
        if issue.reason != "缺少完全一致的显式 HTML id" or "#" not in issue.href:
            unresolved.append(issue)
            continue
        fragment = unquote(urlsplit(issue.href).fragment)
        key = (issue.target, fragment.lower())
        if key not in candidates:
            content = documents.content(issue.target)
            candidates[key] = _heading_candidates(content, fragment, documents.tokens(issue.target))
        headings = candidates[key]
        if len(headings) != 1:
            unresolved.append(issue)
            continue
        repairs.append(
            AnchorRepair(
                source=issue.source,
                line=issue.line,
                href=issue.href,
                target=issue.target,
                fragment=fragment,
                heading_line=headings[0],
            )
        )
    repair_tuple = tuple(sorted(set(repairs)))
    unresolved_tuple = tuple(sorted(set(unresolved)))
    file_hashes = _repair_file_hashes(project_root, scan, documents)
    preview_hash = _canonical_hash(_plan_payload(file_hashes, repair_tuple, unresolved_tuple))
    return RepairPlan(preview_hash, file_hashes, repair_tuple, unresolved_tuple)


def _render_repairs(project_root: str, plan: RepairPlan, documents: _DocumentCache) -> dict[str, str]:
    grouped: dict[str, list[AnchorRepair]] = {}
    for repair in plan.repairs:
        grouped.setdefault(repair.target, []).append(repair)
    rendered: dict[str, str] = {}
    for relative, repairs in sorted(grouped.items()):
        lines = documents.content(relative).splitlines(keepends=True)
        existing = set(_explicit_ids(documents.content(relative), documents.tokens(relative)))
        for repair in sorted(repairs, key=lambda item: (item.heading_line, item.fragment), reverse=True):
            anchor = f'<a id="{repair.fragment}"></a>\n'
            insert_at = repair.heading_line - 1
            if insert_at < 0 or insert_at >= len(lines):
                raise LinkRepairError(f"{relative}:{repair.heading_line} 的标题位置已经失效")
            if repair.fragment not in existing:
                lines.insert(insert_at, anchor)
                existing.add(repair.fragment)
        rendered[relative] = "".join(lines)
    return rendered


def _issue_counts(issues: Iterable[LinkIssue]) -> Counter[tuple[str, str, str, str]]:
    """比较问题本身；插入定位后同一问题的来源行号允许顺移。"""

    return Counter(
        (issue.source, issue.href, issue.target, issue.reason) for issue in issues
    )


def _transaction_path(project_root: str) -> Path:
    return Path(project_root, TRANSACTION_DIR)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recover_pending_link_repair(project_root: str) -> LinkRepairResult:
    """按事务原文副本恢复中断修复；重复调用不会改动已恢复文件。"""

    tx_root = _transaction_path(project_root)
    manifest_path = tx_root / MANIFEST_FILE
    if not tx_root.exists() and not tx_root.is_symlink():
        return LinkRepairResult(True, (), "没有待恢复的链接修复事务")
    if tx_root.is_symlink() or not tx_root.is_dir():
        return LinkRepairResult(False, (), f"{TRANSACTION_DIR} 不是项目内普通事务目录")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return LinkRepairResult(False, (), "链接修复事务目录存在但缺少普通事务清单")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["entries"]
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) for entry in entries
        ):
            raise TypeError("entries 必须是对象数组")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return LinkRepairResult(False, (), f"链接修复事务资料无法读取：{exc}")

    failures: list[str] = []
    restored: list[str] = []
    root = Path(project_root).absolute()
    for entry in entries:
        relative = entry.get("path", "")
        relative_parts = PurePosixPath(relative)
        if (
            not relative
            or relative_parts.is_absolute()
            or ".." in relative_parts.parts
            or "\\" in relative
        ):
            failures.append(f"{relative or '<空路径>'}：事务目标不是安全的项目相对路径")
            continue
        target = Path(os.path.abspath(os.path.join(root, relative)))
        backup = tx_root / "backup" / relative
        try:
            target.relative_to(root)
            if _has_symlink_component(root, target):
                raise ValueError("目标经过符号链接")
            if _has_symlink_component(tx_root, backup):
                raise ValueError("原文副本经过符号链接")
            content = backup.read_bytes()
            if _sha256_bytes(content) != entry.get("before_hash"):
                raise ValueError("原文副本哈希不匹配")
            if not target.is_file() or _sha256_bytes(target.read_bytes()) != entry.get("before_hash"):
                _atomic_write(target, content)
            if _sha256_bytes(target.read_bytes()) != entry.get("before_hash"):
                raise ValueError("恢复后哈希不匹配")
            restored.append(relative)
        except (OSError, ValueError) as exc:
            failures.append(f"{relative}：{exc}")
    if failures:
        return LinkRepairResult(False, tuple(sorted(restored)), "恢复不完整：" + "；".join(sorted(failures)))
    try:
        shutil.rmtree(tx_root)
    except OSError as exc:
        return LinkRepairResult(
            False,
            tuple(sorted(restored)),
            f"原文已恢复，但事务资料清理失败：{exc}",
        )
    return LinkRepairResult(True, tuple(sorted(restored)), "链接修复事务已恢复原文")


def apply_legacy_anchor_repairs(
    project_root: str,
    preview: RepairPlan | str,
    *,
    replace_file: Callable[[Path, bytes], None] | None = None,
) -> LinkRepairResult:
    """应用仍与预览一致的确定修复；失败或中断时整批恢复。"""

    pending = recover_pending_link_repair(project_root)
    if not pending.success:
        raise LinkRepairError(pending.detail)
    expected_hash = preview.preview_hash if isinstance(preview, RepairPlan) else preview
    documents = _DocumentCache(project_root)
    current = _plan_repairs(project_root, documents)
    if current.preview_hash != expected_hash:
        raise LinkRepairError(
            f"修复预览已经漂移：预期 {expected_hash}，实际 {current.preview_hash}；整批零写入"
        )
    if not current.repairs:
        return LinkRepairResult(True, (), "预览中没有可确定修复，未写入文件", current.unresolved)

    rendered = _render_repairs(project_root, current, documents)
    baseline_issues = _issue_counts(current.unresolved)
    preview_documents = documents.overlay(rendered)
    preview_scan = _scan_links(project_root, preview_documents, rendered)
    if _issue_counts(preview_scan.issues) != baseline_issues:
        raise LinkRepairError("待写内容复查没有精确保留不可自动修复项；整批零写入")

    expected_file_hashes = dict(current.file_hashes)
    drifted = [
        relative
        for relative, expected in current.file_hashes
        if not Path(project_root, relative).is_file()
        or _has_symlink_component(Path(project_root).absolute(), Path(project_root, relative).absolute())
        or _sha256_bytes(Path(project_root, relative).read_bytes()) != expected
    ]
    if drifted:
        raise LinkRepairError(f"预览文件在写入前再次漂移：{sorted(drifted)}；整批零写入")

    tx_root = _transaction_path(project_root)
    entries: list[dict[str, str]] = []
    manifest_written = False
    try:
        for relative, new_content in sorted(rendered.items()):
            target_path = Path(project_root, relative)
            if target_path.is_symlink() or _has_symlink_component(
                Path(project_root).absolute(), target_path.absolute()
            ):
                raise LinkRepairError(f"{relative} 在准备事务时变成了符号链接")
            before = target_path.read_bytes()
            if _sha256_bytes(before) != expected_file_hashes[relative]:
                raise LinkRepairError(f"{relative} 在准备事务时发生漂移")
            backup = tx_root / "backup" / relative
            staged = tx_root / "staged" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            staged.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(backup, before)
            _atomic_write(staged, new_content.encode("utf-8"))
            entries.append(
                {
                    "path": relative,
                    "before_hash": _sha256_bytes(before),
                    "after_hash": _sha256_bytes(new_content.encode("utf-8")),
                }
            )
        _write_json(
            tx_root / MANIFEST_FILE,
            {"preview_hash": current.preview_hash, "status": "prepared", "entries": entries},
        )
        manifest_written = True
        writer = replace_file or _atomic_write
        for entry in entries:
            relative = entry["path"]
            target = Path(project_root, relative)
            writer(target, (tx_root / "staged" / relative).read_bytes())
            if not target.is_file() or _sha256_bytes(target.read_bytes()) != entry["after_hash"]:
                raise LinkRepairError(f"{relative} 写入后的内容哈希与预览不一致")
        # 磁盘原文仍逐文件核对；只有与已检查内容完全一致时才复用解析结果。
        for relative, original_hash in current.file_hashes:
            target = Path(project_root, relative)
            expected_hash = _sha256_bytes(rendered[relative].encode("utf-8")) if relative in rendered else original_hash
            if (_has_symlink_component(Path(project_root).absolute(), target.absolute())
                    or not target.is_file() or _sha256_bytes(target.read_bytes()) != expected_hash):
                raise LinkRepairError(f"{relative} 在写入后复查时发生变化")
        actual = _scan_links(project_root, preview_documents)
        if _issue_counts(actual.issues) != baseline_issues:
            raise LinkRepairError("写入后复查没有精确保留不可自动修复项")
        shutil.rmtree(tx_root)
        return LinkRepairResult(True, tuple(sorted(rendered)), "历史标准定位已整批修复并复查通过", actual.issues)
    except BaseException as exc:
        if manifest_written:
            recovery = recover_pending_link_repair(project_root)
        else:
            shutil.rmtree(tx_root, ignore_errors=True)
            recovery = LinkRepairResult(True, (), "目标文件尚未开始替换，临时资料已清理")
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            if not recovery.success:
                raise LinkRepairError(f"修复被中断；{recovery.detail}") from exc
            raise
        if not recovery.success:
            raise LinkRepairError(f"链接修复失败：{exc}；{recovery.detail}") from exc
        raise LinkRepairError(f"链接修复失败，已恢复全部原文：{exc}") from exc
