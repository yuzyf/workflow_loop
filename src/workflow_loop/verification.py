import configparser
import copy
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass

from .project import load_project
from . import artifact_paths as artifact_paths_mod
from .state import (
    RecoveryContext,
    RegressionTestState,
    WorkflowState,
    StageState,
    GateState,
    load_state,
    now_iso,
)
from .test_mapping import automated_topics, planned_test_source_paths
from . import test_entry as test_entry_mod
from .topic import candidate_topics, list_acceptance_index_topics, topic_paths
from . import traceability as traceability_mod
from . import acceptance_records as acceptance_records_mod
from . import snapshots as snapshots_mod
from . import diagnostics as diagnostics_mod


# 产品总说明 功能清单中的本地 Markdown 链接
# 只接受 spec/ 下的中文 功能_*.md，外部链接和其它文件不算产品功能文档
PRODUCT_FEATURE_LINK_RE = re.compile(
    r"\[[^\]]+\]\((?:\./)?(功能_[^/)#\s]+\.md)(?:#[^)]+)?\)"
)


def hash_text(content: str) -> str:
    """计算 UTF-8 文本的 SHA256，供阶段材料和状态内容绑定使用。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _hash_file_path(full_path: str) -> str:
    digest = hashlib.sha256()
    with open(full_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 计算单个文件的 SHA256 哈希
# 用于 Verification Invalidation：绑定上游内容，检测变化
# 文件不存在时返回 None（还没产出过的 stage）
def compute_file_hash(project_root: str, rel_path: str) -> str | None:
    # 拼出文件的完整路径（项目根 + 相对路径）
    full_path = os.path.join(project_root, rel_path)
    # 文件不存在 → 返回 None
    if not os.path.exists(full_path):
        return None
    return _hash_file_path(full_path)


def compute_file_hashes(
    project_root: str,
    rel_paths: list[str],
) -> dict[str, str | None]:
    """计算一组相对路径的文件哈希，保留当时不存在的文件。"""
    return {
        rel_path: compute_file_hash(project_root, rel_path)
        for rel_path in sorted(set(rel_paths))
    }


def compute_project_file_hashes(
    project_root: str,
    *,
    registered_paths: list[str] | None = None,
) -> dict[str, str]:
    """记录实施阶段可能修改的代码、脚本和配置，用于发现计划外改动。

    不把 IDE 工作区、说明文档等与实现无关的文件算作代码变化。实施计划明确
    列出的其它类型文件由回退清单单独比较，因此不会漏掉计划内的资源文件。
    """
    if registered_paths is None:
        active_paths = _active_registered_paths(project_root)
        if active_paths is not None:
            registered_paths = active_paths
    if registered_paths is not None:
        snapshot = snapshots_mod.collect_snapshot(project_root, registered_paths)
        return {
            item.path: item.content_hash
            for item in snapshot.files
            if item.exists and item.file_type == "file" and item.content_hash
        }

    excluded_roots = {
        ".git",
        ".workflow_loop",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        ".next",
        ".idea",
        ".vscode",
        "spec",
        "acceptance",
        "qa",
        "impl",
        "bug",
    }
    excluded_files = {artifact_paths_mod.TRACEABILITY_DOC}
    _, test_entry_path = _project_test_entry(project_root)
    hashes: dict[str, str] = {}
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in excluded_roots]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            normalized = relative_path.replace(os.sep, "/")
            if normalized in excluded_files:
                continue
            if not is_implementation_related_path(normalized, test_entry_path):
                continue
            full_path = os.path.join(project_root, relative_path)
            if os.path.islink(full_path) or not os.path.isfile(full_path):
                continue
            hashes[normalized] = _hash_file_path(full_path)
    return dict(sorted(hashes.items()))


def is_test_related_path(project_root: str, relative_path: str) -> bool:
    """判断文件是否需要在 test_code 前保存真实内容。"""
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized)
    _, test_entry_path = _project_test_entry(project_root)
    suffix = os.path.splitext(filename)[1].lower()
    return (
        _is_test_path(normalized)
        or _is_standalone_test_config(normalized, test_entry_path)
        or filename in CONFIG_NAMES
        or suffix in CONFIG_SUFFIXES
    )


def compute_test_related_file_hashes(project_root: str) -> dict[str, str]:
    return {
        path: content_hash
        for path, content_hash in compute_project_file_hashes(project_root).items()
        if is_test_related_path(project_root, path)
    }


def registered_code_design_paths(project_root: str) -> list[str]:
    """读取代码架构表中明确写在“代码位置”列的文件，不扫描项目。"""
    full_path = os.path.join(project_root, artifact_paths_mod.CODE_DESIGN_DOC)
    if not os.path.isfile(full_path):
        return []
    with open(full_path, "r", encoding="utf-8") as stream:
        lines = stream.read().splitlines()
    paths: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|"):
            index += 1
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        if "代码位置" not in headers:
            index += 1
            continue
        code_index = headers.index("代码位置")
        index += 1
        while index < len(lines) and lines[index].strip().startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            index += 1
            if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
                continue
            if len(cells) != len(headers):
                raise ValueError("代码架构设计的代码位置表列数与表头不一致")
            for reference in re.findall(r"`([^`]+)`", cells[code_index]):
                candidate = re.split(r"::|#L?\d+|:\d+$", reference.strip(), maxsplit=1)[0]
                if not candidate or candidate.startswith("-"):
                    continue
                if "/" not in candidate and candidate not in CONFIG_NAMES:
                    continue
                paths.extend(snapshots_mod.normalize_registered_paths(project_root, [candidate]))
        continue
    return sorted(set(paths))


def _active_registered_paths(project_root: str) -> list[str] | None:
    """返回活动轮次明确登记的路径；没有活动轮次时才允许旧式兼容扫描。"""
    state = load_state(project_root)
    if state is None or state.run_status != "active":
        return None
    registered: set[str] = set(registered_code_design_paths(project_root))
    planned = getattr(state.rollback, "planned_paths", None) or []
    if planned:
        registered.update(planned)
    elif state.topics:
        from .rollback import planned_code_paths

        try:
            registered.update(planned_code_paths(project_root, state.topics))
        except FileNotFoundError:
            pass
        except OSError:
            pass
        except ValueError:
            # 实施文档已经存在却无法解析时，不能悄悄回退到全项目扫描。
            if any(
                os.path.exists(os.path.join(project_root, topic_paths(project_root, topic)["impl_doc"]))
                for topic in state.topics
            ):
                raise
    if state.topics:
        try:
            registered.update(planned_test_source_paths(project_root, state.topics))
        except (FileNotFoundError, OSError, ValueError):
            # 测试计划尚未生成时没有测试登记范围；生成后由对应门禁报告格式错误。
            pass
    project = load_project(project_root)
    if project is not None and isinstance(project.test_entry, dict):
        registered.update(test_entry_mod.referenced_project_scripts(project.test_entry))
    return snapshots_mod.normalize_registered_paths(project_root, registered)


def compute_registered_file_snapshot(
    project_root: str,
    *,
    scope: str = "all",
) -> dict[str, object]:
    """保存登记路径的逐文件事实；scope 为 product/test/all。"""
    if scope not in {"product", "test", "all"}:
        raise ValueError(f"未知快照范围：{scope}")
    paths = _active_registered_paths(project_root) or []
    _, test_entry_path = _project_test_entry(project_root)
    if scope != "all":
        selected: list[str] = []
        for path in paths:
            is_test = _is_test_path(path) or _is_standalone_test_config(path, test_entry_path)
            filename = os.path.basename(path)
            suffix = os.path.splitext(filename)[1].lower()
            shared_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
            if (
                (scope == "test" and (is_test or shared_config))
                or (scope == "product" and (not is_test or shared_config))
            ):
                selected.append(path)
        paths = selected
    return snapshots_mod.collect_snapshot(project_root, paths).to_dict()


def compare_registered_file_snapshot(
    project_root: str,
    baseline: object,
    *,
    scope: str,
) -> dict[str, list[str]]:
    """比较当前登记文件与已保存逐文件基线。"""
    current = snapshots_mod.snapshot_from_dict(
        compute_registered_file_snapshot(project_root, scope=scope)
    )
    if baseline is None:
        return snapshots_mod.compare_snapshots(None, current)
    previous = snapshots_mod.snapshot_from_dict(baseline)
    return snapshots_mod.compare_snapshots(previous, current)


def format_registered_differences(differences: dict[str, list[str]]) -> str:
    """把逐文件差异变成稳定、可直接显示的中文证据。"""
    labels = {
        "added": "新增",
        "modified": "修改",
        "deleted": "删除",
        "type_changed": "类型变化",
        "not_checked": "未检查（缺少逐文件基线）",
    }
    parts = [
        f"{labels[key]}={sorted(differences.get(key, []))}"
        for key in ("added", "modified", "deleted", "type_changed", "not_checked")
        if differences.get(key)
    ]
    return "；".join(parts) if parts else "登记文件无变化"


def compute_document_snapshot(project_root: str, paths: list[str]) -> dict[str, object]:
    """保存一组明确登记的正式文档事实，不扫描目录。"""
    return snapshots_mod.collect_snapshot(project_root, paths).to_dict()


def _normalized_topic_index_content(
    project_root: str,
    relative_path: str,
    result_column_name: str,
    replacement: str,
) -> str | None:
    """屏蔽索引中由下游阶段回填的结果列，其余单元格仍参与绑定。"""
    full_path = os.path.join(project_root, relative_path)
    if not os.path.isfile(full_path):
        return None
    with open(full_path, "r", encoding="utf-8") as stream:
        lines = stream.read().splitlines(keepends=True)

    normalized: list[str] = []
    result_column: tuple[int, int] | None = None
    for line in lines:
        stripped = line.strip()
        cells = None
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]

        if (
            cells is not None
            and cells[:3] == ["展示顺序", "验收主题", "前置主题"]
            and result_column_name in cells
        ):
            result_column = (cells.index(result_column_name), len(cells))
            normalized.append(line)
            continue

        if result_column is None or cells is None:
            if cells is None:
                result_column = None
            normalized.append(line)
            continue

        column_index, column_count = result_column
        if len(cells) != column_count:
            result_column = None
            normalized.append(line)
            continue
        if all(re.fullmatch(r"[-:]+", cell) for cell in cells):
            normalized.append(line)
            continue

        cells[column_index] = replacement
        line_ending = line[len(line.rstrip("\r\n")) :]
        normalized.append("| " + " | ".join(cells) + " |" + line_ending)
    return "".join(normalized)


def _normalized_test_plan_index_content(project_root: str) -> str | None:
    """只屏蔽测试执行阶段才会更新的“测试结果”列。"""
    return _normalized_topic_index_content(
        project_root,
        artifact_paths_mod.QA_INDEX_DOC,
        "测试结果",
        "<下游测试结果>",
    )


def _normalized_acceptance_plan_index_content(project_root: str) -> str | None:
    """只屏蔽主题验收阶段才会更新的“主题验收结果”列。"""
    return _normalized_topic_index_content(
        project_root,
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        "主题验收结果",
        "<下游主题验收结果>",
    )


def compute_test_plan_document_snapshot(
    project_root: str,
    topics: str | list[str] | None,
) -> dict[str, object]:
    """保存测试计划事实，但不把下游测试结果链接当成计划内容。"""
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.QA_INDEX_DOC,
        *[topic_paths(project_root, topic)["test_plan"] for topic in topic_list],
    ]
    snapshot = snapshots_mod.collect_snapshot(project_root, paths)
    normalized_index = _normalized_test_plan_index_content(project_root)
    facts = []
    for fact in snapshot.files:
        if (
            fact.path == artifact_paths_mod.QA_INDEX_DOC
            and fact.exists
            and fact.file_type == "file"
            and normalized_index is not None
        ):
            facts.append(
                snapshots_mod.FileFact(
                    path=fact.path,
                    exists=True,
                    file_type="file",
                    content_hash=hash_text(normalized_index),
                )
            )
        else:
            facts.append(fact)
    return snapshots_mod.Snapshot(tuple(facts)).to_dict()


def compute_acceptance_plan_document_snapshot(
    project_root: str,
    topics: str | list[str] | None,
) -> dict[str, object]:
    """保存验收计划事实，但不把下游主题验收结果链接当成计划内容。"""
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        *[topic_paths(project_root, topic)["acceptance_plan"] for topic in topic_list],
    ]
    snapshot = snapshots_mod.collect_snapshot(project_root, paths)
    normalized_index = _normalized_acceptance_plan_index_content(project_root)
    facts = []
    for fact in snapshot.files:
        if (
            fact.path == artifact_paths_mod.ACCEPTANCE_INDEX_DOC
            and fact.exists
            and fact.file_type == "file"
            and normalized_index is not None
        ):
            facts.append(
                snapshots_mod.FileFact(
                    path=fact.path,
                    exists=True,
                    file_type="file",
                    content_hash=hash_text(normalized_index),
                )
            )
        else:
            facts.append(fact)
    return snapshots_mod.Snapshot(tuple(facts)).to_dict()


def _compare_test_plan_document_snapshot(
    project_root: str,
    baseline: object,
    topics: str | list[str] | None,
) -> dict[str, list[str]]:
    """用与测试计划哈希相同的规则生成逐文件诊断。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.snapshot_from_dict(
            compute_test_plan_document_snapshot(project_root, topics)
        )
        return snapshots_mod.compare_snapshots(previous, current)
    paths = [
        artifact_paths_mod.QA_INDEX_DOC,
        *[topic_paths(project_root, topic)["test_plan"] for topic in normalize_topics(topics)],
    ]
    return _compare_recorded_snapshot(project_root, baseline, paths)


def _compare_acceptance_plan_document_snapshot(
    project_root: str,
    baseline: object,
    topics: str | list[str] | None,
) -> dict[str, list[str]]:
    """用与验收计划哈希相同的规则生成逐文件诊断。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.snapshot_from_dict(
            compute_acceptance_plan_document_snapshot(project_root, topics)
        )
        return snapshots_mod.compare_snapshots(previous, current)
    topic_list = normalize_topics(topics)
    paths = [
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        *[topic_paths(project_root, topic)["acceptance_plan"] for topic in topic_list],
    ]
    return _compare_recorded_snapshot(project_root, baseline, paths)


def _compare_recorded_snapshot(
    project_root: str,
    baseline: object,
    current_paths: list[str],
) -> dict[str, list[str]]:
    """比较新逐文件快照，并兼容旧版的“路径到哈希”记录。"""
    if isinstance(baseline, dict) and isinstance(baseline.get("files"), list):
        previous = snapshots_mod.snapshot_from_dict(baseline)
        current = snapshots_mod.collect_snapshot(project_root, current_paths)
        return snapshots_mod.compare_snapshots(previous, current)
    if isinstance(baseline, dict) and all(isinstance(path, str) for path in baseline):
        current = compute_file_hashes(project_root, current_paths)
        result = {
            "added": [],
            "modified": [],
            "deleted": [],
            "type_changed": [],
            "not_checked": [],
        }
        for path in sorted(set(baseline) | set(current)):
            before = baseline.get(path)
            after = current.get(path)
            if path not in baseline or (before is None and after is not None):
                result["added"].append(path)
            elif path not in current or (before is not None and after is None):
                result["deleted"].append(path)
            elif before != after:
                result["modified"].append(path)
        return result
    current = snapshots_mod.collect_snapshot(project_root, current_paths)
    return snapshots_mod.compare_snapshots(None, current)


# 读取 产品总说明.md 中真实链接的功能文档路径
# 产品设计整体哈希以这里返回的文件为准，不扫描目录里的废弃功能文档
# 已移除历史功能文档只要不再被链接，就不参与当前哈希
def get_linked_product_design_paths(project_root: str) -> list[str]:
    product_rel = artifact_paths_mod.PRODUCT_OVERVIEW_DOC
    product_path = os.path.join(project_root, product_rel)
    paths = [product_rel]
    if not os.path.exists(product_path):
        return paths

    with open(product_path, "r", encoding="utf-8") as f:
        content = f.read()

    for filename in PRODUCT_FEATURE_LINK_RE.findall(content):
        paths.append(os.path.join("spec", filename))
    return sorted(set(paths))


# 对一组文档计算稳定的整体 SHA256
# 路径也参与哈希，所以新增、删除或替换链接都会改变结果
def compute_document_set_hash(project_root: str, rel_paths: list[str]) -> str:
    parts = []
    for rel_path in sorted(set(rel_paths)):
        file_hash = compute_file_hash(project_root, rel_path)
        parts.append(f"{rel_path}:{file_hash or '<missing>'}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def normalize_topics(topics: str | list[str] | None) -> list[str]:
    """兼容旧版单主题参数，并统一返回主题列表。"""
    if topics is None:
        return []
    if isinstance(topics, str):
        return [topics] if topics else []
    return [topic for topic in topics if topic]


# 计算产品总说明及其功能清单链接文档的整体哈希
def compute_product_design_hash(project_root: str) -> tuple[str | None, list[str]]:
    paths = get_linked_product_design_paths(project_root)
    if compute_file_hash(project_root, artifact_paths_mod.PRODUCT_OVERVIEW_DOC) is None:
        return (None, paths)
    return (compute_document_set_hash(project_root, paths), paths)


# 计算代码设计文档哈希
def compute_code_design_hash(project_root: str) -> str | None:
    return compute_file_hash(project_root, artifact_paths_mod.CODE_DESIGN_DOC)


# 代码文件后缀；文档、状态和日志不属于代码快照。
CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".ets",
    ".rb", ".php", ".cs", ".fs", ".fsx", ".m", ".mm", ".qml",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
}
CONFIG_NAMES = {
    "pyproject.toml", "uv.lock", "package.json", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "CMakeLists.txt", "CMakePresets.json", "Makefile", "justfile",
    "setup.py", "setup.cfg", "requirements.txt",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", "Gemfile", "Gemfile.lock", "composer.json",
    "composer.lock",
}
CONFIG_SUFFIXES = {".pro", ".pri", ".cmake", ".yml", ".yaml"}
EXCLUDED_CODE_DIRS = {
    ".git", ".workflow_loop", "__pycache__", ".venv", "node_modules",
    ".pytest_cache", "dist", "build",
}


STANDALONE_TEST_CONFIG_NAMES = {
    "pytest.ini", "tox.ini", ".coveragerc", "conftest.py",
    "requirements-test.txt", "requirements-dev.txt", "dev-requirements.txt",
}
TEST_CONFIG_PREFIXES = (
    "jest.config.", "vitest.config.", "playwright.config.", "cypress.config.",
    "karma.conf.",
)


def _is_test_path(relative_path: str) -> bool:
    """判断相对路径是否属于测试代码。"""
    parts = [part.lower() for part in relative_path.replace(os.sep, "/").split("/")]
    filename = parts[-1].lower()
    stem = os.path.splitext(filename)[0]
    test_directories = {
        "tests", "test", "__tests__", "testdata", "test_data",
        "integration_tests", "e2e",
    }
    if any(part in test_directories for part in parts[:-1]):
        return True
    if stem.endswith(("_test", "_spec", ".test", ".spec")):
        return True
    return "src" not in parts[:-1] and filename.startswith(("test_", "tst_"))


def _stable_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _split_pyproject_config(full_path: str) -> tuple[str, str]:
    """把 pyproject.toml 的测试专用配置和产品配置分开。"""
    with open(full_path, "rb") as stream:
        data = tomllib.load(stream)
    product_data = copy.deepcopy(data)
    test_data: dict = {}

    tool_data = data.get("tool", {})
    selected_tools = {
        key: value
        for key, value in tool_data.items()
        if key in {"pytest", "coverage", "tox"}
    }
    if selected_tools:
        test_data["tool"] = selected_tools
        product_tool = product_data.get("tool", {})
        for key in selected_tools:
            product_tool.pop(key, None)
        if not product_tool:
            product_data.pop("tool", None)

    optional_dependencies = data.get("project", {}).get("optional-dependencies", {})
    selected_dependencies = {
        key: value
        for key, value in optional_dependencies.items()
        if key.lower() in {"dev", "test", "tests"}
    }
    if selected_dependencies:
        test_data.setdefault("project", {})["optional-dependencies"] = selected_dependencies
        product_optional = (
            product_data.get("project", {}).get("optional-dependencies", {})
        )
        for key in selected_dependencies:
            product_optional.pop(key, None)
        if not product_optional:
            product_data.get("project", {}).pop("optional-dependencies", None)

    dependency_groups = data.get("dependency-groups", {})
    selected_groups = {
        key: value
        for key, value in dependency_groups.items()
        if key.lower() in {"dev", "test", "tests"}
    }
    if selected_groups:
        test_data["dependency-groups"] = selected_groups
        product_groups = product_data.get("dependency-groups", {})
        for key in selected_groups:
            product_groups.pop(key, None)
        if not product_groups:
            product_data.pop("dependency-groups", None)

    return _stable_payload(test_data), _stable_payload(product_data)


def _split_package_json_config(full_path: str) -> tuple[str, str]:
    """把 package.json 中的测试脚本、测试工具配置和测试依赖分开。"""
    with open(full_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    product_data = copy.deepcopy(data)
    test_data: dict = {}

    scripts = data.get("scripts", {})
    selected_scripts = {
        key: value
        for key, value in scripts.items()
        if key == "test" or key.startswith("test:")
    }
    if selected_scripts:
        test_data["scripts"] = selected_scripts
        product_scripts = product_data.get("scripts", {})
        for key in selected_scripts:
            product_scripts.pop(key, None)
        if not product_scripts:
            product_data.pop("scripts", None)

    for key in ("jest", "vitest", "playwright", "cypress"):
        if key in data:
            test_data[key] = data[key]
            product_data.pop(key, None)

    dev_dependencies = data.get("devDependencies", {})
    selected_dev_dependencies = {
        key: value
        for key, value in dev_dependencies.items()
        if any(
            token in key.lower()
            for token in (
                "test", "jest", "vitest", "mocha", "chai", "sinon", "ava", "tap",
                "playwright", "cypress", "testing-library", "nyc", "coverage",
            )
        )
    }
    if selected_dev_dependencies:
        test_data["devDependencies"] = selected_dev_dependencies
        product_dev_dependencies = product_data.get("devDependencies", {})
        for key in selected_dev_dependencies:
            product_dev_dependencies.pop(key, None)
        if not product_dev_dependencies:
            product_data.pop("devDependencies", None)

    return _stable_payload(test_data), _stable_payload(product_data)


def _split_setup_cfg(full_path: str) -> tuple[str, str]:
    parser = configparser.ConfigParser()
    parser.read(full_path, encoding="utf-8")
    test_sections = {
        section: dict(parser[section])
        for section in parser.sections()
        if section.startswith(("tool:pytest", "coverage:", "tox:"))
    }
    product_sections = {
        section: dict(parser[section])
        for section in parser.sections()
        if section not in test_sections
    }
    return _stable_payload(test_sections), _stable_payload(product_sections)


def _project_test_entry(project_root: str) -> tuple[str, str | None]:
    """返回 (稳定编码后的入口配置, 入口脚本相对路径)。

    入口配置是操作系统到参数数组的完整映射，稳定编码进测试代码快照；
    入口脚本路径用于识别测试相关文件（脚本内容变化 → 测试快照变化）。
    """
    project = load_project(project_root)
    raw_config = project.test_entry if project is not None else {}
    if isinstance(raw_config, str):
        raw_config = {"default": [raw_config]} if raw_config.strip() else {}
    if not isinstance(raw_config, dict):
        raw_config = {}
    encoded = json.dumps(raw_config, ensure_ascii=False, sort_keys=True)

    # 在任一平台参数中找项目内脚本路径（含 / 或常见脚本后缀的参数）
    entry_path = None
    for argv in raw_config.values():
        if not isinstance(argv, list):
            continue
        for part in argv:
            if not isinstance(part, str) or part.startswith("-"):
                continue
            if "/" in part or "\\" in part or part.endswith(
                (".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".ps1", ".bat", ".cmd")
            ):
                entry_path = part.replace("\\", "/")
                break
        if entry_path:
            break
    if entry_path is not None:
        entry_path = os.path.normpath(entry_path).replace(os.sep, "/")
        if os.path.isabs(entry_path):
            try:
                relative_entry = os.path.relpath(entry_path, project_root)
            except ValueError:
                relative_entry = entry_path
            if relative_entry != ".." and not relative_entry.startswith(f"..{os.sep}"):
                entry_path = relative_entry.replace(os.sep, "/")
    return encoded, entry_path


def _is_standalone_test_config(relative_path: str, test_entry_path: str | None) -> bool:
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized).lower()
    return (
        normalized == test_entry_path
        or filename in STANDALONE_TEST_CONFIG_NAMES
        or filename.startswith(TEST_CONFIG_PREFIXES)
    )


def is_implementation_related_path(
    relative_path: str,
    test_entry_path: str | None = None,
) -> bool:
    """判断路径是否属于实施代码、脚本、测试或项目配置。"""
    normalized = relative_path.replace(os.sep, "/")
    filename = os.path.basename(normalized)
    suffix = os.path.splitext(filename)[1].lower()
    return (
        _is_test_path(normalized)
        or _is_standalone_test_config(normalized, test_entry_path)
        or suffix in CODE_SUFFIXES
        or filename in CONFIG_NAMES
        or suffix in CONFIG_SUFFIXES
    )


def _snapshot_parts_registered(
    project_root: str,
    registered_paths: list[str],
    test_entry_path: str | None,
    test_parts: list[str],
    product_parts: list[str],
) -> tuple[list[str], list[str]]:
    """按登记路径生成快照输入；此函数不调用 os.walk。"""
    for relative_path in sorted(set(registered_paths)):
        full_path = os.path.join(project_root, *relative_path.split("/"))
        if os.path.islink(full_path) or not os.path.isfile(full_path):
            continue
        filename = os.path.basename(relative_path)
        suffix = os.path.splitext(filename)[1].lower()
        is_test_path = _is_test_path(relative_path)
        is_test_config = _is_standalone_test_config(relative_path, test_entry_path)
        if not (is_test_path or is_test_config or suffix in CODE_SUFFIXES or filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES):
            continue
        raw_hash = _hash_file_path(full_path)
        if relative_path == "pyproject.toml":
            try:
                test_payload, product_payload = _split_pyproject_config(full_path)
            except (OSError, tomllib.TOMLDecodeError):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        if relative_path == "package.json":
            try:
                test_payload, product_payload = _split_package_json_config(full_path)
            except (OSError, json.JSONDecodeError):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        if relative_path == "setup.cfg":
            try:
                test_payload, product_payload = _split_setup_cfg(full_path)
            except (OSError, configparser.Error):
                test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
            else:
                test_parts.append(f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}")
                product_parts.append(f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}")
            continue
        is_shared_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
        if is_shared_config and not (is_test_path or is_test_config):
            test_parts.append(f"{relative_path}#test-config:{raw_hash}")
            product_parts.append(f"{relative_path}#product-config:{raw_hash}")
        else:
            target = test_parts if is_test_path or is_test_config else product_parts
            target.append(f"{relative_path}:{raw_hash}")
    return sorted(test_parts), sorted(product_parts)


def _snapshot_parts(project_root: str) -> tuple[list[str], list[str]]:
    """返回测试部分和产品部分的稳定哈希输入。"""
    test_parts: list[str] = []
    product_parts: list[str] = []
    test_entry, test_entry_path = _project_test_entry(project_root)
    test_parts.append(f".workflow_loop/project.json#test_entry:{hashlib.sha256(test_entry.encode('utf-8')).hexdigest()}")

    registered_paths = _active_registered_paths(project_root)
    if registered_paths is not None:
        return _snapshot_parts_registered(
            project_root,
            registered_paths,
            test_entry_path,
            test_parts,
            product_parts,
        )

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_CODE_DIRS and directory != ".next"]
        for filename in files:
            relative_path = os.path.relpath(os.path.join(root, filename), project_root)
            is_test_path = _is_test_path(relative_path)
            is_test_config = _is_standalone_test_config(relative_path, test_entry_path)
            suffix = os.path.splitext(filename)[1].lower()
            is_project_config = filename in CONFIG_NAMES or suffix in CONFIG_SUFFIXES
            if (
                not is_test_path
                and not is_test_config
                and suffix not in CODE_SUFFIXES
                and not is_project_config
            ):
                continue
            full_path = os.path.join(project_root, relative_path)
            try:
                raw_hash = _hash_file_path(full_path)
            except OSError:
                continue

            if relative_path == "pyproject.toml":
                try:
                    test_payload, product_payload = _split_pyproject_config(full_path)
                except (OSError, tomllib.TOMLDecodeError):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue
            if relative_path == "package.json":
                try:
                    test_payload, product_payload = _split_package_json_config(full_path)
                except (OSError, json.JSONDecodeError):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue
            if relative_path == "setup.cfg":
                try:
                    test_payload, product_payload = _split_setup_cfg(full_path)
                except (OSError, configparser.Error):
                    test_parts.append(f"{relative_path}#test-fallback:{raw_hash}")
                    product_parts.append(f"{relative_path}#product-fallback:{raw_hash}")
                else:
                    test_parts.append(
                        f"{relative_path}#test:{hashlib.sha256(test_payload.encode('utf-8')).hexdigest()}"
                    )
                    product_parts.append(
                        f"{relative_path}#product:{hashlib.sha256(product_payload.encode('utf-8')).hexdigest()}"
                    )
                continue

            target = test_parts if is_test_path or is_test_config else product_parts
            target.append(f"{relative_path}:{raw_hash}")
    return sorted(test_parts), sorted(product_parts)


def _compute_code_snapshot_hash(project_root: str, *, test_only: bool | None) -> str:
    """按范围计算代码快照：全部、仅测试或排除测试。"""
    test_parts, product_parts = _snapshot_parts(project_root)
    if test_only is True:
        parts = test_parts
    elif test_only is False:
        parts = product_parts
    else:
        parts = [*test_parts, *product_parts]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算项目全部代码的快照哈希（impl_hash 和全量测试基线使用）
def compute_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=None)


# 计算测试代码快照哈希（test_code 阶段确认是否真的写了测试代码）
def compute_test_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=True)


# 计算排除测试代码后的产品代码快照哈希（阻止 test_code 阶段修改产品代码）
def compute_non_test_code_snapshot_hash(project_root: str) -> str:
    return _compute_code_snapshot_hash(project_root, test_only=False)


# 计算实施阶段使用的实施综合哈希（impl_hash）
# 包含两部分：impl/ 下全部实施记录内容哈希 + 非测试代码快照哈希
# test_code 阶段后续修改测试代码，不应让已经确认的实施结果失效。
def compute_impl_hash(project_root: str, topics: str | list[str] | None = None) -> str:
    # 只绑定当前工作流明确登记的实施索引和主题记录，历史记录和目录内其它文件
    # 不得因为文件名后缀相同而影响当前实施状态。
    topic_list = normalize_topics(topics)
    parts = []
    if topic_list:
        impl_paths = [
            artifact_paths_mod.IMPL_INDEX_DOC,
            *[topic_paths(project_root, topic)["impl_doc"] for topic in topic_list],
        ]
        parts.append(f"impl_docs:{compute_document_set_hash(project_root, impl_paths)}")
    # 只加入非测试代码快照，测试代码由 test_code 阶段单独校验。
    parts.append(f"code_snapshot:{compute_non_test_code_snapshot_hash(project_root)}")
    # 合并所有部分算最终 SHA256
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


# 计算测试计划文件 qa/<主题文件标识>_测试计划.md 的 SHA256
# 在 gate test_plan --confirmed 时记录；变化时使主题执行及其后续结果失效
def compute_test_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    snapshot = compute_test_plan_document_snapshot(project_root, topic_list)
    return str(snapshot["aggregate_hash"])


# 计算验收计划文件和验收主题索引的 SHA256
# 在 gate acceptance_plan --confirmed 时记录
# acceptance_plan 或主题关系变化时把 test_plan 和后续阶段退回待检查
def compute_acceptance_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    snapshot = compute_acceptance_plan_document_snapshot(project_root, topic_list)
    return str(snapshot["aggregate_hash"])


# 计算测试结果文件 qa/<主题文件标识>_测试结果.md 的 SHA256
# 在 gate test_execution --confirmed 时记录；变化时使主题验收及后续阶段失效
def compute_test_result_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [
        topic_paths(project_root, topic)["test_result"]
        for topic in automated_topics(project_root, topic_list)
    ]
    if not paths:
        return hashlib.sha256(b"<no-automated-test-results>").hexdigest()
    return compute_document_set_hash(project_root, paths)


# 计算主题验收结果文件 acceptance/<主题文件标识>_验收结果.md 的 SHA256
# 在 gate topic_acceptance --confirmed 时记录；变化时使最终回归及后续阶段失效
def compute_acceptance_result_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [topic_paths(project_root, topic)["acceptance_result"] for topic in topic_list]
    document_hash = compute_document_set_hash(project_root, paths)
    state = load_state(project_root)
    records = (
        acceptance_records_mod.acceptance_records_payload(state, topic_list)
        if state is not None
        else {}
    )
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(
        f"documents:{document_hash}\nrecords:{payload}".encode("utf-8")
    ).hexdigest()


def compute_regression_test_result_hash(project_root: str) -> str | None:
    state = load_state(project_root)
    if state is None:
        return None
    payload = json.dumps(state.regression_test.__dict__, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 清零单个 stage 的所有门禁状态（3 道闸全清，状态回 pending）
# 用于 Verification Invalidation：上游变化时清零下游
def clear_stage_gates(stage: StageState) -> None:
    # 重置 3 道闸为全新 GateState（全 False）
    stage.gate = GateState()
    # stage 状态回到 pending（需要重新走 7 步模式）
    stage.status = "pending"
    # 下游失效后，旧产物基线和 impl 代码基线也不能继续复用。
    stage.artifact_produced_at = None
    stage.artifact_baseline_captured_at = None
    stage.artifact_baseline_hashes = {}
    stage.code_baseline_hash = None
    stage.test_code_baseline_hash = None
    stage.non_test_code_baseline_hash = None
    stage.existing_code_accepted_hash = None
    stage.existing_test_code_accepted_hash = None
    stage.plan_confirmed_hash = None


def set_recovery_context(
    state: WorkflowState,
    source_stage: str,
    affected_stages: list[str],
    reason: str,
) -> None:
    """保存退回原因，让后续命令能解释当前阶段是复核还是重做。"""
    state.recovery = RecoveryContext(
        source_stage=source_stage,
        reason=reason,
        affected_stages=list(affected_stages),
        created_at=now_iso(),
    )


def clear_completed_material_recovery(state: WorkflowState) -> bool:
    """引发恢复的阶段重新确认完成后，清除当前提示，历史留在 Journal。"""
    recovery = state.recovery
    if not recovery.source_stage or not recovery.reason:
        return False
    source_state = state.stages.get(recovery.source_stage)
    if source_state is None or source_state.status != "done":
        return False
    state.recovery = RecoveryContext()
    return True


def recovery_stage_action(state: WorkflowState, stage_name: str) -> str | None:
    """返回当前恢复阶段的具体动作，避免把复核误说成重新开发。"""
    recovery = state.recovery
    if not recovery.source_stage or stage_name not in recovery.affected_stages:
        return None

    if recovery.reason and "流程模板或规范" in recovery.reason:
        return (
            "重新阅读更新后的流程材料，并按新规则核对当前产出；"
            "只有新规则使现有产出不合格时才修改"
        )

    if stage_name in {"spec", "reproduce", "code_design", "revise_code_design", "spike"}:
        return "重新核对上游事实和设计；只有内容确实不一致时才修改文档"
    if stage_name in {"acceptance_plan", "test_plan"}:
        return "重新核对上游文档和当前计划；已有内容仍正确时不需要为了门禁重写"
    if stage_name == "impl":
        return (
            "重新核对实施计划、实施记录和现有代码是否符合最新上游计划；"
            "一致时确认既有代码，不一致时才修改代码"
        )
    if stage_name == "test_code":
        return (
            "重新核对测试计划与现有测试代码的对应关系；一致时确认既有测试代码，"
            "不一致时才修改测试代码"
        )
    if stage_name == "test_execution":
        return "旧测试结果不能继续使用，重新登记并执行需要测试的主题"
    if stage_name == "topic_acceptance":
        return "使用新的主题测试结果重新逐条验收；不能直接沿用旧验收结果"
    if stage_name == "regression_test":
        return "重新执行全量回归；旧回归状态不能代表当前代码"
    if stage_name == "overall_acceptance":
        return "根据最新主题验收和全量回归结果重新做整体验收"
    if stage_name == "update_code_design":
        return "根据重新确认后的真实代码和验收结果更新详细代码设计"
    return "重新核对当前阶段产出是否仍符合上游结果"


def recovery_summary(state: WorkflowState) -> str | None:
    """返回一行可直接显示给用户的恢复原因。"""
    recovery = state.recovery
    if not recovery.source_stage or not recovery.reason:
        return None
    return f"{recovery.source_stage} 相关内容需要重新处理：{recovery.reason}"


def reset_stages_and_move_current(state: WorkflowState, stage_names: list[str]) -> None:
    """清零指定阶段，并把当前阶段退回到路径中最早的受影响阶段。"""
    affected = []
    for stage_name in stage_names:
        if stage_name in state.stages:
            clear_stage_gates(state.stages[stage_name])
            affected.append(stage_name)

    if not affected:
        return

    order = {stage_name: index for index, stage_name in enumerate(state.stage_path)}
    earliest = min(affected, key=lambda stage_name: order.get(stage_name, len(order)))
    state.current_stage = earliest
    state.stages[earliest].status = "in_progress"


def _invalidate_test_execution_outputs(
    project_root: str,
    state: WorkflowState,
    topics: list[str],
) -> None:
    """上游内容变化时，清掉不能继续使用的主题测试状态和结果文件。"""
    stage_state = state.stages.get("test_execution")
    if stage_state is not None:
        for topic in topics:
            stage_state.test_tasks.pop(topic, None)
    for topic in topics:
        paths = topic_paths(project_root, topic)
        for kind in ("test_result", "acceptance_result"):
            result_path = os.path.join(project_root, paths[kind])
            if os.path.isfile(result_path):
                os.remove(result_path)
    acceptance_records_mod.clear_topic_records(project_root, state, topics)
    state.regression_test = RegressionTestState()


@dataclass(frozen=True)
class InvalidationInspection:
    """一次只读失效检查得到的完整事实。"""

    source_stage: str | None = None
    affected_stages: tuple[str, ...] = ()
    affected_topics: tuple[str, ...] = ()
    affected_description: str = ""
    reason: str = ""
    diagnostics: tuple[diagnostics_mod.Diagnostic, ...] = ()

    @property
    def changed(self) -> bool:
        return self.source_stage is not None


_INVALIDATION_ORDER = (
    ("acceptance_plan", "acceptance_plan_hash"),
    ("impl", "impl_hash"),
    ("test_plan", "test_plan_hash"),
    ("test_code", "test_code_hash"),
    ("test_execution", "test_result_hash"),
    ("topic_acceptance", "acceptance_result_hash"),
    ("regression_test", "regression_test_result_hash"),
)

_INVALIDATION_AFFECTED = {
    "acceptance_plan": (
        "acceptance_plan", "impl", "test_plan", "test_code", "test_execution",
        "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design",
    ),
    "impl": (
        "impl", "test_plan", "test_code", "test_execution", "topic_acceptance",
        "regression_test", "overall_acceptance", "update_code_design",
    ),
    "test_plan": (
        "test_plan", "test_code", "test_execution", "topic_acceptance",
        "regression_test", "overall_acceptance", "update_code_design",
    ),
    "test_code": (
        "test_code", "test_execution", "topic_acceptance", "regression_test",
        "overall_acceptance", "update_code_design",
    ),
    "test_execution": (
        "topic_acceptance", "regression_test", "overall_acceptance", "update_code_design",
    ),
    "topic_acceptance": ("regression_test", "overall_acceptance", "update_code_design"),
    "regression_test": ("regression_test", "overall_acceptance", "update_code_design"),
}

_INVALIDATION_DESCRIPTIONS = {
    "acceptance_plan": "acceptance_plan 及全部后续阶段",
    "impl": "impl 及全部后续阶段",
    "test_plan": "test_plan 及全部后续阶段（保留 impl）",
    "test_code": "test_code 及全部后续阶段",
    "test_execution": "topic_acceptance 及全部后续阶段",
    "topic_acceptance": "regression_test、overall_acceptance 和 update_code_design",
    "regression_test": "regression_test、overall_acceptance 和 update_code_design",
}


def _change_diagnostics(
    *,
    source_stage: str,
    scope_name: str,
    differences: dict[str, list[str]],
    parent_check_id: str,
) -> list[diagnostics_mod.Diagnostic]:
    labels = {
        "added": "新增或进入登记范围",
        "modified": "内容修改",
        "deleted": "删除或移出登记范围",
        "type_changed": "文件类型变化",
    }
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    for kind in ("added", "modified", "deleted", "type_changed"):
        for path in sorted(differences.get(kind, [])):
            diagnostics.append(
                diagnostics_mod.Diagnostic(
                    kind="error",
                    check_id=f"invalidation.{source_stage}.{scope_name}.{kind}:{path}",
                    location=path,
                    expected=f"与 {source_stage} 确认时登记的{scope_name}逐文件事实一致",
                    actual=labels[kind],
                    evidence=f"逐文件快照比较结果：{kind}={path}",
                    impact=f"{_INVALIDATION_DESCRIPTIONS[source_stage]}不能继续沿用",
                    next_action=f"核对 {path} 的真实变化，并在 {source_stage} 阶段更新或恢复对应内容",
                )
            )
    for path in sorted(differences.get("not_checked", [])):
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="not_checked",
                check_id=f"invalidation.{source_stage}.{scope_name}.not_checked:{path}",
                location=path,
                expected=f"存在 {source_stage} 确认时保存的{scope_name}逐文件基线",
                actual="未检查：旧状态没有该路径的逐文件基线",
                evidence="只有聚合哈希发生变化，无法从旧状态还原该路径修改前事实",
                impact="不能精确断言该路径属于新增、修改、删除还是类型变化",
                next_action=f"返回 {source_stage} 重新确认并保存新的逐文件基线",
                depends_on=parent_check_id,
            )
        )
    return diagnostics


_CHANGE_KINDS = ("added", "modified", "deleted", "type_changed")


def _changed_paths(*differences: dict[str, list[str]]) -> set[str]:
    """汇总逐文件差异中的真实变化路径，不丢失任一变化类型。"""
    return {
        path
        for difference in differences
        for kind in _CHANGE_KINDS
        for path in difference.get(kind, [])
    }


def _topic_owned_paths(
    project_root: str,
    topics: list[str],
    source_stage: str,
) -> dict[str, set[str]] | None:
    """返回路径到主题的归属；计划无法解析时返回 None，调用方按整轮处理。"""
    ownership: dict[str, set[str]] = {}

    def register(topic: str, paths: list[str]) -> None:
        for path in paths:
            normalized = path.replace(os.sep, "/")
            ownership.setdefault(normalized, set()).add(topic)

    try:
        for topic in topics:
            paths = topic_paths(project_root, topic)
            if source_stage == "acceptance_plan":
                register(topic, [paths["acceptance_plan"]])
            elif source_stage == "impl":
                # rollback（回退模块）会反向引用本模块，只能在运行检查时局部导入。
                from .rollback import planned_code_paths

                register(topic, [paths["impl_doc"]])
                register(topic, planned_code_paths(project_root, [topic]))
            elif source_stage == "test_plan":
                register(topic, [paths["test_plan"]])
            elif source_stage == "test_code":
                register(topic, planned_test_source_paths(project_root, [topic]))
            elif source_stage == "test_execution":
                register(topic, [paths["test_result"]])
            elif source_stage == "topic_acceptance":
                register(topic, [paths["acceptance_result"]])
    except (FileNotFoundError, OSError, ValueError):
        return None
    return ownership


def _affected_topics_from_changes(
    project_root: str,
    topics: list[str],
    source_stage: str,
    *differences: dict[str, list[str]],
) -> tuple[str, ...]:
    """由逐文件变化反推直接受影响主题；证据不足时保守返回全部主题。"""
    ordered_topics = tuple(dict.fromkeys(topics))
    if not ordered_topics:
        return ()
    if source_stage == "regression_test":
        return ordered_topics

    # 旧状态没有逐文件基线时，无法证明具体是哪个主题变化，不能猜测归属。
    if any(difference.get("not_checked") for difference in differences):
        return ordered_topics
    changed_paths = _changed_paths(*differences)
    if not changed_paths:
        return ordered_topics

    global_paths = {
        "acceptance_plan": {artifact_paths_mod.ACCEPTANCE_INDEX_DOC},
        "impl": {artifact_paths_mod.IMPL_INDEX_DOC},
        "test_plan": {artifact_paths_mod.QA_INDEX_DOC},
    }.get(source_stage, set())
    if changed_paths & global_paths:
        return ordered_topics

    ownership = _topic_owned_paths(project_root, list(ordered_topics), source_stage)
    if ownership is None:
        return ordered_topics
    affected: set[str] = set()
    for path in changed_paths:
        owners = ownership.get(path.replace(os.sep, "/"))
        if not owners:
            # 计划外核心代码、共享配置或无法识别的正式文档都可能影响整轮。
            return ordered_topics
        affected.update(owners)
    return tuple(topic for topic in ordered_topics if topic in affected)


def _dependent_not_checked(
    state: WorkflowState,
    source_stage: str,
    parent_check_id: str,
) -> list[diagnostics_mod.Diagnostic]:
    """最上游已经失效时，明确列出本次没有继续判断的下游绑定。"""
    source_index = [name for name, _ in _INVALIDATION_ORDER].index(source_stage)
    diagnostics: list[diagnostics_mod.Diagnostic] = []
    for stage_name, field_name in _INVALIDATION_ORDER[source_index + 1 :]:
        if getattr(state.verification, field_name) is None:
            continue
        diagnostics.append(
            diagnostics_mod.Diagnostic(
                kind="not_checked",
                check_id=f"invalidation.{stage_name}.not_checked",
                location=f".workflow_loop/state.json#verification.{field_name}",
                expected=f"在有效的上游结果上检查 {stage_name} 绑定是否变化",
                actual=f"未检查：更上游的 {source_stage} 已经失效",
                evidence=f"前置检查 {parent_check_id} 已确认变化",
                impact=f"{stage_name} 的旧结果随上游一起失效，单独比较没有判定意义",
                next_action=f"先完成并确认 {source_stage}，再按流程重新检查 {stage_name}",
                depends_on=parent_check_id,
            )
        )
    return diagnostics


def _make_invalidation_inspection(
    state: WorkflowState,
    *,
    source_stage: str,
    expected_hash: str,
    actual_hash: str | None,
    reason: str,
    exact_diagnostics: list[diagnostics_mod.Diagnostic],
    affected_topics: tuple[str, ...],
) -> InvalidationInspection:
    field_name = dict(_INVALIDATION_ORDER)[source_stage]
    parent_check_id = f"invalidation.{source_stage}.binding"
    diagnostics = [
        diagnostics_mod.Diagnostic(
            kind="error",
            check_id=parent_check_id,
            location=f".workflow_loop/state.json#verification.{field_name}",
            expected=f"当前 {source_stage} 绑定哈希等于确认值 {expected_hash}",
            actual=f"当前绑定哈希为 {actual_hash}",
            evidence=f"saved={expected_hash}; current={actual_hash}",
            impact=f"{_INVALIDATION_DESCRIPTIONS[source_stage]}的旧确认不能继续使用",
            next_action=f"先核对下面列出的具体变化，再返回 {source_stage} 处理",
        ),
        *exact_diagnostics,
        *_dependent_not_checked(state, source_stage, parent_check_id),
    ]
    return InvalidationInspection(
        source_stage=source_stage,
        affected_stages=_INVALIDATION_AFFECTED[source_stage],
        affected_topics=affected_topics,
        affected_description=_INVALIDATION_DESCRIPTIONS[source_stage],
        reason=reason,
        diagnostics=tuple(diagnostics),
    )


def inspect_invalidation(state: WorkflowState, project_root: str) -> InvalidationInspection:
    """只读检查最上游变化，并一次返回具体差异和所有下游未检查项。"""
    topics = state.topics or ([state.topic] if state.topic else [])
    stored = state.meta.get("registered_snapshots", {})

    expected = state.verification.acceptance_plan_hash
    if expected is not None:
        current_topics = list_acceptance_index_topics(project_root, state.workflow_id)
        current = compute_acceptance_plan_hash(project_root, current_topics)
        if current != expected:
            paths = [
                artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
                *[topic_paths(project_root, topic)["acceptance_plan"] for topic in current_topics],
            ]
            differences = _compare_acceptance_plan_document_snapshot(
                project_root,
                stored.get("acceptance_plan_documents"),
                current_topics,
            )
            parent = "invalidation.acceptance_plan.binding"
            return _make_invalidation_inspection(
                state,
                source_stage="acceptance_plan",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "验收主题或验收条件已经改变："
                    f"{format_registered_differences(differences)}。"
                    "后续计划、代码和结果必须重新核对"
                ),
                exact_diagnostics=_change_diagnostics(
                    source_stage="acceptance_plan",
                    scope_name="验收计划文档",
                    differences=differences,
                    parent_check_id=parent,
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "acceptance_plan", differences
                ),
            )

    expected = state.verification.impl_hash
    if expected is not None:
        current = compute_impl_hash(project_root, topics)
        if current != expected:
            parent = "invalidation.impl.binding"
            try:
                code_differences = compare_registered_file_snapshot(
                    project_root, stored.get("impl"), scope="product"
                )
            except ValueError:
                code_differences = {
                    "added": [], "modified": [], "deleted": [], "type_changed": [],
                    "not_checked": _active_registered_paths(project_root) or [],
                }
            document_paths = [
                artifact_paths_mod.IMPL_INDEX_DOC,
                *[topic_paths(project_root, topic)["impl_doc"] for topic in topics],
            ]
            document_differences = _compare_recorded_snapshot(
                project_root, stored.get("impl_documents"), document_paths
            )
            details = (
                f"核心代码：{format_registered_differences(code_differences)}；"
                f"实施文档：{format_registered_differences(document_differences)}"
            )
            return _make_invalidation_inspection(
                state,
                source_stage="impl",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    f"实施绑定内容变化。{details}。"
                    "原测试计划、测试和验收结果不能继续代表当前实现"
                ),
                exact_diagnostics=[
                    *_change_diagnostics(
                        source_stage="impl",
                        scope_name="核心代码",
                        differences=code_differences,
                        parent_check_id=parent,
                    ),
                    *_change_diagnostics(
                        source_stage="impl",
                        scope_name="实施文档",
                        differences=document_differences,
                        parent_check_id=parent,
                    ),
                ],
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "impl", code_differences, document_differences
                ),
            )

    expected = state.verification.test_plan_hash
    if expected is not None:
        current = compute_test_plan_hash(project_root, topics)
        if current != expected:
            differences = _compare_test_plan_document_snapshot(
                project_root,
                stored.get("test_plan_documents"),
                topics,
            )
            parent = "invalidation.test_plan.binding"
            return _make_invalidation_inspection(
                state,
                source_stage="test_plan",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "测试计划内容已经改变："
                    f"{format_registered_differences(differences)}；"
                    "已确认实施保持有效，测试代码、执行和验收必须重新核对"
                ),
                exact_diagnostics=_change_diagnostics(
                    source_stage="test_plan",
                    scope_name="测试计划文档",
                    differences=differences,
                    parent_check_id=parent,
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "test_plan", differences
                ),
            )

    expected = state.verification.test_code_hash
    if expected is not None:
        current = compute_test_code_snapshot_hash(project_root)
        if current != expected:
            parent = "invalidation.test_code.binding"
            try:
                differences = compare_registered_file_snapshot(
                    project_root, stored.get("test_code"), scope="test"
                )
            except ValueError:
                differences = {
                    "added": [], "modified": [], "deleted": [], "type_changed": [],
                    "not_checked": _active_registered_paths(project_root) or [],
                }
            return _make_invalidation_inspection(
                state,
                source_stage="test_code",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "登记的测试文件或统一测试入口已经改变："
                    f"{format_registered_differences(differences)}。旧执行记录必须作废；"
                    "未登记的构建、依赖和缓存文件不参与判断"
                ),
                exact_diagnostics=_change_diagnostics(
                    source_stage="test_code",
                    scope_name="测试代码",
                    differences=differences,
                    parent_check_id=parent,
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "test_code", differences
                ),
            )

    expected = state.verification.test_result_hash
    if expected is not None:
        current = compute_test_result_hash(project_root, topics)
        if current != expected:
            paths = [
                topic_paths(project_root, topic)["test_result"]
                for topic in automated_topics(project_root, topics)
            ]
            differences = _compare_recorded_snapshot(
                project_root, stored.get("test_result_documents"), paths
            )
            parent = "invalidation.test_execution.binding"
            return _make_invalidation_inspection(
                state,
                source_stage="test_execution",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "主题测试结果已经改变："
                    f"{format_registered_differences(differences)}。"
                    "旧主题验收和后续结论必须重新确认"
                ),
                exact_diagnostics=_change_diagnostics(
                    source_stage="test_execution",
                    scope_name="测试结果文档",
                    differences=differences,
                    parent_check_id=parent,
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "test_execution", differences
                ),
            )

    expected = state.verification.acceptance_result_hash
    if expected is not None:
        current = compute_acceptance_result_hash(project_root, topics)
        if current != expected:
            paths = [topic_paths(project_root, topic)["acceptance_result"] for topic in topics]
            differences = _compare_recorded_snapshot(
                project_root, stored.get("acceptance_result_documents"), paths
            )
            parent = "invalidation.topic_acceptance.binding"
            return _make_invalidation_inspection(
                state,
                source_stage="topic_acceptance",
                expected_hash=expected,
                actual_hash=current,
                reason=(
                    "主题验收结果或验收机器记录已经改变："
                    f"{format_registered_differences(differences)}。"
                    "旧全量回归和整体验收结论不能继续使用"
                ),
                exact_diagnostics=_change_diagnostics(
                    source_stage="topic_acceptance",
                    scope_name="验收结果文档",
                    differences=differences,
                    parent_check_id=parent,
                ),
                affected_topics=_affected_topics_from_changes(
                    project_root, topics, "topic_acceptance", differences
                ),
            )

    expected = state.verification.regression_test_result_hash
    if expected is not None:
        current = compute_regression_test_result_hash(project_root)
        code_changed = state.regression_test.code_snapshot_hash != compute_code_snapshot_hash(project_root)
        if current != expected or code_changed:
            parent = "invalidation.regression_test.binding"
            if code_changed:
                try:
                    differences = compare_registered_file_snapshot(
                        project_root, stored.get("regression_test"), scope="all"
                    )
                except ValueError:
                    differences = {
                        "added": [], "modified": [], "deleted": [], "type_changed": [],
                        "not_checked": _active_registered_paths(project_root) or [],
                    }
                exact = _change_diagnostics(
                    source_stage="regression_test",
                    scope_name="回归绑定代码",
                    differences=differences,
                    parent_check_id=parent,
                )
                reason = (
                    "全量回归后登记文件发生变化："
                    f"{format_registered_differences(differences)}；必须重新执行全量回归"
                )
            else:
                exact = []
                reason = "全量回归状态字段已经改变，后续整体验收不能继续使用旧结论"
            return _make_invalidation_inspection(
                state,
                source_stage="regression_test",
                expected_hash=expected,
                actual_hash=current,
                reason=reason,
                exact_diagnostics=exact,
                affected_topics=_affected_topics_from_changes(
                    project_root,
                    topics,
                    "regression_test",
                    differences if code_changed else {},
                ),
            )

    return InvalidationInspection()


def apply_invalidation(
    state: WorkflowState,
    project_root: str,
    inspection: InvalidationInspection,
) -> list[tuple[str, str]]:
    """按只读检查选出的最上游来源，一次应用全部清零和结果作废。"""
    if not inspection.changed or inspection.source_stage is None:
        return []
    source = inspection.source_stage
    topics = list(inspection.affected_topics)
    reset_stages_and_move_current(state, list(inspection.affected_stages))
    set_recovery_context(state, source, list(inspection.affected_stages), inspection.reason)
    state.recovery.affected_topics = list(topics)

    if source == "acceptance_plan":
        state.verification.acceptance_plan_hash = None
        state.verification.impl_hash = None
        state.verification.test_plan_hash = None
        state.verification.test_code_hash = None
        state.verification.test_result_hash = None
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        traceability_mod.reset_after_upstream_invalidation(
            project_root, state.workflow_id, topics, "acceptance_plan"
        )
        _invalidate_test_execution_outputs(project_root, state, topics)
    elif source == "impl":
        state.verification.impl_hash = None
        state.verification.test_plan_hash = None
        state.verification.test_code_hash = None
        state.verification.test_result_hash = None
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        traceability_mod.reset_after_upstream_invalidation(
            project_root, state.workflow_id, topics, "impl"
        )
        _invalidate_test_execution_outputs(project_root, state, topics)
    elif source == "test_plan":
        state.verification.test_plan_hash = None
        state.verification.test_code_hash = None
        state.verification.test_result_hash = None
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        traceability_mod.reset_after_upstream_invalidation(
            project_root, state.workflow_id, topics, "test_plan"
        )
        _invalidate_test_execution_outputs(project_root, state, topics)
    elif source == "test_code":
        state.verification.test_code_hash = None
        state.verification.test_result_hash = None
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        if os.path.isfile(os.path.join(project_root, artifact_paths_mod.TRACEABILITY_DOC)):
            traceability_mod.reset_topics_for_return(
                project_root, state.workflow_id, topics, "test_code"
            )
        _invalidate_test_execution_outputs(project_root, state, topics)
    elif source == "test_execution":
        state.verification.test_result_hash = None
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        if os.path.isfile(os.path.join(project_root, artifact_paths_mod.TRACEABILITY_DOC)):
            traceability_mod.reset_topics_for_return(
                project_root, state.workflow_id, topics, "test_execution"
            )
        acceptance_records_mod.clear_topic_records(project_root, state, topics)
    elif source == "topic_acceptance":
        state.verification.acceptance_result_hash = None
        state.verification.regression_test_result_hash = None
        if os.path.isfile(os.path.join(project_root, artifact_paths_mod.TRACEABILITY_DOC)):
            traceability_mod.reset_topics_for_return(
                project_root, state.workflow_id, topics, "topic_acceptance"
            )
    elif source == "regression_test":
        state.verification.regression_test_result_hash = None
        if os.path.isfile(os.path.join(project_root, artifact_paths_mod.TRACEABILITY_DOC)):
            traceability_mod.reset_topics_for_return(
                project_root, state.workflow_id, topics, "regression_test"
            )

    return [(source, inspection.affected_description)]


# 兼容原调用：先只读检查，再一次应用。需要展示完整诊断的命令层应分别调用
# inspect_invalidation（检查失效）和 apply_invalidation（应用失效）。
def check_invalidation(state: WorkflowState, project_root: str) -> list[tuple[str, str]]:
    inspection = inspect_invalidation(state, project_root)
    return apply_invalidation(state, project_root, inspection)
