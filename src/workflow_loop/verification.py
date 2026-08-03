import configparser
import copy
import hashlib
import json
import os
import re
import tomllib

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
from .test_mapping import automated_topics
from .topic import candidate_topics, topic_paths
from . import traceability as traceability_mod
from . import acceptance_records as acceptance_records_mod


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


def compute_project_file_hashes(project_root: str) -> dict[str, str]:
    """记录实施阶段可能修改的代码、脚本和配置，用于发现计划外改动。

    不把 IDE 工作区、说明文档等与实现无关的文件算作代码变化。实施计划明确
    列出的其它类型文件由回退清单单独比较，因此不会漏掉计划内的资源文件。
    """
    excluded_roots = {
        ".git",
        ".workflow_loop",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
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


def _snapshot_parts(project_root: str) -> tuple[list[str], list[str]]:
    """返回测试部分和产品部分的稳定哈希输入。"""
    test_parts: list[str] = []
    product_parts: list[str] = []
    test_entry, test_entry_path = _project_test_entry(project_root)
    test_parts.append(f".workflow_loop/project.json#test_entry:{hashlib.sha256(test_entry.encode('utf-8')).hexdigest()}")

    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_CODE_DIRS]
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
    # 收集哈希的各部分
    parts = []
    # 实施任务与验收主题不一定一一对应，因此绑定 impl/ 下全部实施记录。
    impl_dir = os.path.join(project_root, "impl")
    if os.path.isdir(impl_dir):
        impl_paths = [
            os.path.join("impl", filename)
            for filename in os.listdir(impl_dir)
            if filename.endswith(".md")
        ]
        if impl_paths:
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
    paths = [topic_paths(project_root, topic)["test_plan"] for topic in topic_list]
    return compute_document_set_hash(project_root, paths)


# 计算验收计划文件和验收主题索引的 SHA256
# 在 gate acceptance_plan --confirmed 时记录
# acceptance_plan 或主题关系变化时把 test_plan 和后续阶段退回待检查
def compute_acceptance_plan_hash(project_root: str, topics: str | list[str] | None) -> str | None:
    topic_list = normalize_topics(topics)
    if not topic_list:
        return None
    paths = [
        artifact_paths_mod.ACCEPTANCE_INDEX_DOC,
        *[topic_paths(project_root, topic)["acceptance_plan"] for topic in topic_list],
    ]
    return compute_document_set_hash(project_root, paths)


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
        stage_state.test_tasks = {}
    for topic in topics:
        paths = topic_paths(project_root, topic)
        for kind in ("test_result", "acceptance_result"):
            result_path = os.path.join(project_root, paths[kind])
            if os.path.isfile(result_path):
                os.remove(result_path)
    acceptance_records_mod.clear_topic_records(project_root, state, topics)
    state.regression_test = RegressionTestState()


# 检查 Verification Invalidation：上游内容是否变化，变化则清零下游
# 在进入下游 stage 的第 2 道闸（gate 无 flag）时调用
# 返回失效列表：[(变化的源头, 被清零的下游), ...]
def check_invalidation(state: WorkflowState, project_root: str) -> list[tuple[str, str]]:
    invalidations: list[tuple[str, str]] = []
    topics = state.topics or ([state.topic] if state.topic else [])

    # 验收计划决定后续全部工作。内容、主题新增或主题删除后，从验收计划重新开始。
    if state.verification.acceptance_plan_hash is not None:
        current_topics = candidate_topics(project_root)
        current_ap = compute_acceptance_plan_hash(project_root, current_topics)
        if current_ap != state.verification.acceptance_plan_hash:
            affected_stages = [
                "acceptance_plan",
                "test_plan",
                "impl",
                "test_code",
                "test_execution",
                "topic_acceptance",
                "regression_test",
                "overall_acceptance",
                "update_code_design",
            ]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "acceptance_plan",
                affected_stages,
                "验收主题或验收条件已经改变，后续计划、代码和结果必须重新核对",
            )
            state.verification.acceptance_plan_hash = None
            state.verification.test_plan_hash = None
            state.verification.impl_hash = None
            state.verification.test_code_hash = None
            state.verification.test_result_hash = None
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            traceability_mod.reset_after_upstream_invalidation(
                project_root,
                state.workflow_id,
                topics,
                "acceptance_plan",
            )
            _invalidate_test_execution_outputs(project_root, state, topics)
            invalidations.append(("acceptance_plan", "acceptance_plan 及全部后续阶段"))
            return invalidations

    # 测试计划变化后，测试计划本身、实施计划和执行结果都必须重新确认。
    if state.verification.test_plan_hash is not None:
        current_tp = compute_test_plan_hash(project_root, topics)
        if current_tp != state.verification.test_plan_hash:
            affected_stages = [
                "test_plan",
                "impl",
                "test_code",
                "test_execution",
                "topic_acceptance",
                "regression_test",
                "overall_acceptance",
                "update_code_design",
            ]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "test_plan",
                affected_stages,
                "测试项、测试方式或测试范围已经改变，后续实施和测试必须重新核对",
            )
            state.verification.test_plan_hash = None
            state.verification.impl_hash = None
            state.verification.test_code_hash = None
            state.verification.test_result_hash = None
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            traceability_mod.reset_after_upstream_invalidation(
                project_root,
                state.workflow_id,
                topics,
                "test_plan",
            )
            _invalidate_test_execution_outputs(project_root, state, topics)
            invalidations.append(("test_plan", "test_plan 及全部后续阶段"))
            return invalidations

    # 实施代码或实施记录变化后，必须返回实施阶段重新确认。
    if state.verification.impl_hash is not None:
        current_impl = compute_impl_hash(project_root, topics)
        if current_impl != state.verification.impl_hash:
            affected_stages = [
                "impl",
                "test_code",
                "test_execution",
                "topic_acceptance",
                "regression_test",
                "overall_acceptance",
                "update_code_design",
            ]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "impl",
                affected_stages,
                "实施代码或实施记录已经改变，原测试和验收结果不能继续代表当前实现",
            )
            state.verification.impl_hash = None
            state.verification.test_code_hash = None
            state.verification.test_result_hash = None
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            _invalidate_test_execution_outputs(project_root, state, topics)
            invalidations.append(("impl", "impl 及全部后续阶段"))
            return invalidations

    # 已确认测试代码或测试配置变化后，返回测试代码阶段。
    if state.verification.test_code_hash is not None:
        current_test_code = compute_test_code_snapshot_hash(project_root)
        if current_test_code != state.verification.test_code_hash:
            affected_stages = [
                "test_code",
                "test_execution",
                "topic_acceptance",
                "regression_test",
                "overall_acceptance",
                "update_code_design",
            ]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "test_code",
                affected_stages,
                "测试代码、测试配置或统一测试入口已经改变，旧执行记录必须作废",
            )
            state.verification.test_code_hash = None
            state.verification.test_result_hash = None
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            _invalidate_test_execution_outputs(project_root, state, topics)
            invalidations.append(("test_code", "test_code 及全部后续阶段"))
            return invalidations

    # 某个主题的测试结果变化后，从主题验收重新确认。
    if state.verification.test_result_hash is not None:
        current_test_result = compute_test_result_hash(project_root, topics)
        if current_test_result != state.verification.test_result_hash:
            affected_stages = [
                "topic_acceptance",
                "regression_test",
                "overall_acceptance",
                "update_code_design",
            ]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "test_execution",
                affected_stages,
                "主题测试结果已经改变，旧主题验收和后续结论必须重新确认",
            )
            state.verification.test_result_hash = None
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            acceptance_records_mod.clear_topic_records(project_root, state, topics)
            invalidations.append(("test_execution", "topic_acceptance 及全部后续阶段"))
            return invalidations

    # 某个主题的验收结果变化后，从最终全量回归重新确认。
    if state.verification.acceptance_result_hash is not None:
        current_acceptance_result = compute_acceptance_result_hash(project_root, topics)
        if current_acceptance_result != state.verification.acceptance_result_hash:
            affected_stages = ["regression_test", "overall_acceptance", "update_code_design"]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            set_recovery_context(
                state,
                "topic_acceptance",
                affected_stages,
                "主题验收结果已经改变，旧全量回归和整体验收结论不能继续使用",
            )
            state.verification.acceptance_result_hash = None
            state.verification.regression_test_result_hash = None
            invalidations.append(("topic_acceptance", "regression_test、overall_acceptance 和 update_code_design"))
            return invalidations

    # 最终全量回归结果或代码变化后，从最终全量回归重新开始。
    # 回归结果现在保存在 state.json，不再通过结果 Markdown 文件判断。
    if state.verification.regression_test_result_hash is not None:
        current_regression = compute_regression_test_result_hash(project_root)
        regression_code_changed = (
            state.regression_test.code_snapshot_hash != compute_code_snapshot_hash(project_root)
        )
        if current_regression != state.verification.regression_test_result_hash or regression_code_changed:
            affected_stages = ["regression_test", "overall_acceptance", "update_code_design"]
            reset_stages_and_move_current(
                state,
                affected_stages,
            )
            reason = (
                "全量回归后代码又发生变化，必须重新执行全量回归"
                if regression_code_changed
                else "全量回归状态已经改变，后续整体验收不能继续使用旧结论"
            )
            set_recovery_context(
                state,
                "regression_test",
                affected_stages,
                reason,
            )
            state.verification.regression_test_result_hash = None
            invalidations.append(("regression_test", "regression_test、overall_acceptance 和 update_code_design"))
            return invalidations

    return invalidations
