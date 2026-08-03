import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone

# importlib.resources 用于访问包内打包的数据文件（Template_Repository 等）
# Python 3.9+ 自带 importlib.resources.files；旧版本需要 importlib_resources 后备包
try:
    from importlib.resources import files as resource_files
except ImportError:
    from importlib_resources import files as resource_files

from . import PRODUCT_NAME, __version__ as PRODUCT_VERSION
from .project import (
    AGENTS_MD_FILENAME,
    STANDARDIZED_DIRNAME,
    TEMPLATE_DIRNAME,
    WORKFLOW_LOOP_DIRNAME,
    check_skeleton,
    create_project,
)

# AGENTS.md 的固定内容（最小契约 + 核心表达要求）
# 唯一契约文件名，告诉 AI "调 workflow start，跟着 stdout 走"，并约束聊天表达
# 安装时直接整份覆盖，不询问、不合并、不备份（CONTEXT.md "Agent Contract File"）
AGENTS_MD_CONTENT = """# Agent 契约

本项目由 workflow_loop 管理。

## workflow 入口

- 用户只需要提出需求，不需要知道或手动执行任何 `workflow` 命令。
- 用户提出需求后，由 AI 调 `workflow start`，之后严格按每条命令 stdout 打印的"下一步"执行。
- 日常 `workflow` 命令全部由 AI 执行。AI 每次执行或转述命令时，必须先用直白中文说明：
  这条命令要解决什么、会做什么和不会做什么、执行成功后进入哪一步、用户现在是否需要
  确认或操作；不能只把 stdout 中的英文命令原样转发给用户。

## 表达要求

AI 回复用户和编写正式文档时：

- 输出前先弄清实际问题、已知事实、限制和目标。
- 能用直白话就不用抽象词；必须使用专业词时，马上说明它具体指什么。
- 写清谁在什么情况下做什么，以及会得到什么结果。
- 删除空泛、重复，或者没有增加事实、决定、行动和理由的话。
"""

# 一次性安装事务目录：固定放在项目根下，安装脚本在确认前向用户披露
# 进程被强制终止时目录保留；下次安装先识别并恢复，再重新开始
TRANSACTION_DIRNAME = ".workflow_loop_install_tx"
# 事务清单文件名（记录状态、允许写入路径和备份项）
MANIFEST_FILENAME = "transaction.json"
# 原内容备份子目录
BACKUP_DIRNAME = "backup"
# 临时骨架准备子目录（先在这里搭好完整骨架，校验后才替换进项目）
STAGING_DIRNAME = "staging"

# 本次安装允许写入的项目相对路径（必须与安装脚本让用户确认的清单一致）
PROJECT_WRITE_PATHS = (
    AGENTS_MD_FILENAME,
    WORKFLOW_LOOP_DIRNAME,
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# 递归复制包内资源树到目标文件系统路径
# importlib.resources 的 Traversable 对象不能直接用 shutil.copytree
# 所以手动递归遍历，遇到目录就递归，遇到文件就复制
def _copy_resource_tree(src_root, dst_root: str) -> None:
    # 确保目标目录存在
    os.makedirs(dst_root, exist_ok=True)
    # 遍历源目录下的每个子项
    for child in src_root.iterdir():
        # 拼出目标路径
        dst_path = os.path.join(dst_root, child.name)
        # 子项是目录 → 递归复制
        if child.is_dir():
            _copy_resource_tree(child, dst_path)
        # 子项是文件 → 复制文件内容
        else:
            # 打开包内资源文件（二进制）
            with child.open("rb") as src_f:
                # 写到目标路径
                with open(dst_path, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)


def _transaction_dir(project_root: str) -> str:
    return os.path.join(project_root, TRANSACTION_DIRNAME)


def _manifest_path(project_root: str) -> str:
    return os.path.join(_transaction_dir(project_root), MANIFEST_FILENAME)


def _load_manifest(project_root: str) -> dict:
    path = _manifest_path(project_root)
    if not os.path.lexists(path):
        raise ValueError(f"缺少事务清单 {MANIFEST_FILENAME}")
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError(f"事务清单 {MANIFEST_FILENAME} 不是普通文件")
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"事务清单 {MANIFEST_FILENAME} 无法读取: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"事务清单 {MANIFEST_FILENAME} 的顶层必须是对象")
    return manifest


def _save_manifest(project_root: str, manifest: dict) -> None:
    path = _manifest_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}必须是非空相对路径")
    if "\x00" in value:
        raise ValueError(f"{label}包含空字符")

    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"{label}不能是绝对路径: {value!r}")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{label}包含不安全路径片段: {value!r}")
    return "/".join(parts)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def _resolve_inside(base: str, value: object, label: str) -> tuple[str, str]:
    normalized = _normalize_relative_path(value, label)
    base_real = os.path.realpath(base)
    candidate = os.path.abspath(os.path.join(base, *normalized.split("/")))
    parent_real = os.path.realpath(os.path.dirname(candidate))
    try:
        if not _same_path(os.path.commonpath((base_real, parent_real)), base_real):
            raise ValueError(f"{label}逃出了允许目录: {value!r}")
    except ValueError as exc:
        raise ValueError(f"{label}逃出了允许目录: {value!r}") from exc
    return normalized, candidate


# 校验安装脚本生成的一次性事务文件。
# 事务不存在、已经使用、产品身份或版本不符、项目路径不一致、允许写入路径与本次
# 安装的实际写入范围不同时，都在任何写入前失败。
def _validate_transaction_token(project_root: str, token_path: str) -> tuple[dict | None, str]:
    if not token_path:
        return None, "缺少一次性安装事务文件路径"
    if not os.path.isfile(token_path):
        return None, f"一次性安装事务文件不存在: {token_path}"
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            token = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"一次性安装事务文件无法读取: {exc}"
    if not isinstance(token, dict):
        return None, "一次性安装事务文件的顶层必须是对象"

    if token.get("product") != PRODUCT_NAME:
        return None, f"事务产品标识是 {token.get('product')!r}，本安装器只接受 {PRODUCT_NAME!r}"
    if token.get("version") != PRODUCT_VERSION:
        return None, f"事务版本是 {token.get('version')!r}，当前产品固定为 {PRODUCT_VERSION!r}"
    if token.get("used") is not False:
        return None, "这份安装事务已经使用过，不能再次写入项目"

    token_root = token.get("project_root", "")
    if (
        not isinstance(token_root, str)
        or not token_root
        or not _same_path(os.path.realpath(token_root), os.path.realpath(project_root))
    ):
        return None, (
            f"事务登记的项目路径是 {token_root!r}，与当前目录 {project_root!r} 不一致"
        )

    allowed = token.get("allowed_paths")
    if (
        not isinstance(allowed, list)
        or not all(isinstance(path, str) for path in allowed)
        or len(allowed) != len(PROJECT_WRITE_PATHS)
        or sorted(allowed) != sorted(PROJECT_WRITE_PATHS)
    ):
        return None, (
            f"事务允许写入的路径 {allowed!r} 与本次安装的实际写入范围 "
            f"{sorted(PROJECT_WRITE_PATHS)!r} 不一致"
        )
    return token, ""


# 把事务文件标记为已使用：从此这份事务不能再驱动任何项目写入
def _mark_token_used(token_path: str, token: dict) -> None:
    token["used"] = True
    token["used_at"] = _now_iso()
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(token, f, ensure_ascii=False, indent=2)


# 在事务目录内准备完整项目骨架并校验；此时项目本身未被修改
def _prepare_staging(project_root: str) -> tuple[str, list[str]]:
    staging_root = os.path.join(_transaction_dir(project_root), STAGING_DIRNAME)
    if os.path.exists(staging_root):
        shutil.rmtree(staging_root)
    os.makedirs(staging_root)

    # 定位包内 data/ 目录（importlib.resources）
    pkg_root = resource_files("workflow_loop")
    data_root = pkg_root.joinpath("data")

    wf_staging = os.path.join(staging_root, WORKFLOW_LOOP_DIRNAME)
    _copy_resource_tree(data_root.joinpath(TEMPLATE_DIRNAME), os.path.join(wf_staging, TEMPLATE_DIRNAME))
    _copy_resource_tree(
        data_root.joinpath(STANDARDIZED_DIRNAME), os.path.join(wf_staging, STANDARDIZED_DIRNAME)
    )
    with open(os.path.join(staging_root, AGENTS_MD_FILENAME), "w", encoding="utf-8") as f:
        f.write(AGENTS_MD_CONTENT)

    # 校验临时骨架完整：两个仓库非空、契约存在
    problems: list[str] = []
    for dirname in (TEMPLATE_DIRNAME, STANDARDIZED_DIRNAME):
        staged = os.path.join(wf_staging, dirname)
        if not os.path.isdir(staged) or not os.listdir(staged):
            problems.append(f"临时骨架缺少 {dirname}/ 或内容为空")
    if not os.path.isfile(os.path.join(staging_root, AGENTS_MD_FILENAME)):
        problems.append(f"临时骨架缺少 {AGENTS_MD_FILENAME}")
    return staging_root, problems


# 第一次持久写入前，把将被覆盖的原内容和"原本不存在"记录保存进事务清单
def _record_backups(project_root: str) -> list[dict]:
    backup_root = os.path.join(_transaction_dir(project_root), BACKUP_DIRNAME)
    os.makedirs(backup_root, exist_ok=True)
    entries: list[dict] = []

    agents_path = os.path.join(project_root, AGENTS_MD_FILENAME)
    if os.path.lexists(agents_path):
        if os.path.islink(agents_path) or not os.path.isfile(agents_path):
            raise ValueError(f"{AGENTS_MD_FILENAME} 不是可安全覆盖的普通文件")
        backup_rel = f"{BACKUP_DIRNAME}/{AGENTS_MD_FILENAME}"
        backup_path = os.path.join(backup_root, AGENTS_MD_FILENAME)
        shutil.copy2(agents_path, backup_path)
        entries.append(
            {
                "path": AGENTS_MD_FILENAME,
                "existed": True,
                "backup": backup_rel,
                "sha256": _sha256_file(backup_path),
            }
        )
    else:
        entries.append(
            {
                "path": AGENTS_MD_FILENAME,
                "existed": False,
                "backup": None,
                "sha256": None,
            }
        )

    # 未安装项目 .workflow_loop/ 不应存在；记录"原本不存在"以便失败时整目录删除
    workflow_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME)
    if os.path.lexists(workflow_path):
        raise ValueError(f"{WORKFLOW_LOOP_DIRNAME} 在安装准备期间出现，已停止以免覆盖")
    entries.append(
        {
            "path": WORKFLOW_LOOP_DIRNAME,
            "existed": False,
            "backup": None,
            "sha256": None,
        }
    )
    return entries


def _validate_recovery_manifest(project_root: str, manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("事务清单顶层必须是对象")

    tx_dir = _transaction_dir(project_root)
    if not os.path.lexists(tx_dir):
        raise ValueError("事务目录不存在")
    if os.path.islink(tx_dir) or not os.path.isdir(tx_dir):
        raise ValueError("事务目录不是项目根下的普通目录")

    project_real = os.path.realpath(project_root)
    tx_real = os.path.realpath(tx_dir)
    if not _same_path(os.path.dirname(tx_real), project_real):
        raise ValueError("事务目录实际位置不在项目根目录下")

    if manifest.get("product") != PRODUCT_NAME:
        raise ValueError(
            f"事务产品标识是 {manifest.get('product')!r}，期望 {PRODUCT_NAME!r}"
        )
    if manifest.get("version") != PRODUCT_VERSION:
        raise ValueError(
            f"事务版本是 {manifest.get('version')!r}，期望 {PRODUCT_VERSION!r}"
        )

    manifest_root = manifest.get("project_root")
    if (
        not isinstance(manifest_root, str)
        or not manifest_root
        or not _same_path(os.path.realpath(manifest_root), project_real)
    ):
        raise ValueError(
            f"事务登记的项目路径 {manifest_root!r} 与当前项目 {project_root!r} 不一致"
        )
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"]:
        raise ValueError("事务缺少创建时间")

    status = manifest.get("status")
    if status not in ("prepared", "committed"):
        raise ValueError(f"事务状态 {status!r} 不允许恢复或清理")

    allowed = manifest.get("allowed_paths")
    if (
        not isinstance(allowed, list)
        or not all(isinstance(path, str) for path in allowed)
        or len(allowed) != len(PROJECT_WRITE_PATHS)
        or sorted(allowed) != sorted(PROJECT_WRITE_PATHS)
    ):
        raise ValueError(
            f"事务允许路径 {allowed!r} 与固定范围 {sorted(PROJECT_WRITE_PATHS)!r} 不一致"
        )
    for path in allowed:
        if _normalize_relative_path(path, "事务允许路径") != path:
            raise ValueError(f"事务允许路径不是规范相对路径: {path!r}")

    entries = manifest.get("backups")
    if not isinstance(entries, list) or len(entries) != len(PROJECT_WRITE_PATHS):
        raise ValueError("事务备份清单必须逐项覆盖全部固定写入路径")

    backup_root = os.path.join(tx_dir, BACKUP_DIRNAME)
    targets: dict[str, str] = {}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("事务备份项必须是对象")

        raw_path = entry.get("path")
        normalized_path, target = _resolve_inside(project_root, raw_path, "事务备份目标")
        if normalized_path != raw_path or normalized_path not in PROJECT_WRITE_PATHS:
            raise ValueError(f"事务备份目标不在固定写入范围内: {raw_path!r}")
        if normalized_path in seen:
            raise ValueError(f"事务备份目标重复: {normalized_path}")
        seen.add(normalized_path)
        targets[normalized_path] = target

        existed = entry.get("existed")
        if not isinstance(existed, bool):
            raise ValueError(f"{normalized_path} 的 existed 必须是布尔值")
        if "backup" not in entry or "sha256" not in entry:
            raise ValueError(f"{normalized_path} 的备份路径或 SHA-256 缺失")

        if normalized_path == WORKFLOW_LOOP_DIRNAME and existed:
            raise ValueError(f"{WORKFLOW_LOOP_DIRNAME} 在本类安装事务中不应登记为原本存在")

        if existed:
            if normalized_path != AGENTS_MD_FILENAME:
                raise ValueError(f"{normalized_path} 不允许从文件备份恢复")
            expected_backup = f"{BACKUP_DIRNAME}/{AGENTS_MD_FILENAME}"
            backup_relative, backup_path = _resolve_inside(
                tx_dir, entry.get("backup"), f"{normalized_path} 的备份路径"
            )
            if backup_relative != expected_backup:
                raise ValueError(
                    f"{normalized_path} 的备份路径 {backup_relative!r} 不是 {expected_backup!r}"
                )
            if os.path.islink(backup_root):
                raise ValueError("事务备份目录不能是符号链接")
            expected_backup_root_real = os.path.join(tx_real, BACKUP_DIRNAME)
            if not _same_path(os.path.realpath(backup_root), expected_backup_root_real):
                raise ValueError("事务备份目录实际位置异常")
            if os.path.islink(backup_path) or not os.path.isfile(backup_path):
                raise ValueError(f"{normalized_path} 的备份不是普通文件")
            expected_backup_real = os.path.join(
                expected_backup_root_real, AGENTS_MD_FILENAME
            )
            if not _same_path(os.path.realpath(backup_path), expected_backup_real):
                raise ValueError(f"{normalized_path} 的备份实际位置异常")

            expected_hash = entry.get("sha256")
            if not isinstance(expected_hash, str) or not SHA256_PATTERN.fullmatch(
                expected_hash
            ):
                raise ValueError(f"{normalized_path} 的备份 SHA-256 格式错误")
            actual_hash = _sha256_file(backup_path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"{normalized_path} 的备份 SHA-256 不一致，备份可能已损坏或被替换"
                )
        elif entry.get("backup") is not None or entry.get("sha256") is not None:
            raise ValueError(f"{normalized_path} 原本不存在，却登记了备份文件或 SHA-256")

    if seen != set(PROJECT_WRITE_PATHS):
        raise ValueError("事务备份清单没有完整覆盖固定写入路径")

    # prepared 会恢复项目，所以先一次性检查所有目标类型和实际位置。
    # committed 只删除已校验的事务目录，不接触这些目标。
    if status == "prepared":
        for relative_path, target in targets.items():
            if not os.path.lexists(target):
                continue
            if os.path.islink(target):
                raise ValueError(f"{relative_path} 是符号链接，拒绝恢复")
            expected_real = os.path.join(project_real, *relative_path.split("/"))
            if not _same_path(os.path.realpath(target), expected_real):
                raise ValueError(f"{relative_path} 的实际位置逃出了项目固定路径")
            if relative_path == AGENTS_MD_FILENAME and not os.path.isfile(target):
                raise ValueError(f"{AGENTS_MD_FILENAME} 不是普通文件，拒绝恢复")
            if relative_path == WORKFLOW_LOOP_DIRNAME and not os.path.isdir(target):
                raise ValueError(f"{WORKFLOW_LOOP_DIRNAME} 不是普通目录，拒绝恢复")


# 按事务清单恢复项目：删除本次新建内容、写回原内容。
# 返回未能恢复的路径列表；为空表示恢复完整。
def _restore_from_manifest(project_root: str, manifest: dict) -> list[str]:
    try:
        _validate_recovery_manifest(project_root, manifest)
    except (OSError, ValueError) as exc:
        return [f"事务清单未通过恢复前校验（{exc}）"]

    failures: list[str] = []
    tx_dir = _transaction_dir(project_root)
    for entry in manifest["backups"]:
        relative_path = entry["path"]
        target = os.path.join(project_root, relative_path)
        try:
            if entry["existed"]:
                backup = os.path.join(tx_dir, *entry["backup"].split("/"))
                if os.path.islink(target) or (
                    os.path.lexists(target) and not os.path.isfile(target)
                ):
                    failures.append(f"{relative_path}（目标不再是可安全恢复的普通文件）")
                    continue
                shutil.copy2(backup, target)
            else:
                # 原本不存在 → 删除本次安装新建的文件或目录
                if not os.path.lexists(target):
                    continue
                if os.path.islink(target):
                    failures.append(f"{relative_path}（目标变成了符号链接）")
                    continue
                if relative_path == WORKFLOW_LOOP_DIRNAME:
                    if not os.path.isdir(target):
                        failures.append(f"{relative_path}（目标不再是普通目录）")
                        continue
                    shutil.rmtree(target)
                else:
                    if not os.path.isfile(target):
                        failures.append(f"{relative_path}（目标不再是普通文件）")
                        continue
                    os.remove(target)
        except OSError as exc:
            failures.append(f"{relative_path}（{exc}）")
    return failures


# 识别并处理上一次没有完成的安装事务。
# 已提交但没来得及清理 → 只清理临时内容；未提交 → 恢复项目后清理。
# 返回 (是否可以继续本次安装, 说明文字)。
def recover_pending_transaction(project_root: str) -> tuple[bool, str]:
    tx_dir = _transaction_dir(project_root)
    if not os.path.lexists(tx_dir):
        return True, ""

    try:
        manifest = _load_manifest(project_root)
        _validate_recovery_manifest(project_root, manifest)
    except (OSError, ValueError) as exc:
        return (
            False,
            "检测到安装事务残留，但恢复前校验失败；项目文件未修改，事务目录已保留：\n"
            f"  {exc}",
        )

    if manifest.get("status") == "committed":
        # 上次安装已成功，只是清理被打断 → 只完成清理，不回退成功的安装
        try:
            shutil.rmtree(tx_dir)
        except OSError as exc:
            return False, f"上一笔安装已成功，但事务临时目录清理失败：\n  {exc}"
        return True, "上一笔安装事务已成功，清理了遗留的临时内容。"

    failures = _restore_from_manifest(project_root, manifest)
    if failures:
        return False, "上一笔未完成安装事务恢复失败，未恢复路径：\n  " + "\n  ".join(failures)
    try:
        shutil.rmtree(tx_dir)
    except OSError as exc:
        return False, f"上一笔安装事务已恢复，但事务临时目录清理失败：\n  {exc}"
    return True, "恢复了上一笔未完成的安装事务，项目已回到安装前状态。"


# 安装当前项目（由官方安装脚本通过内部 _install-project 入口调用，非日常命令）。
# 一次性事务驱动：校验事务 → 识别遗留事务 → 重复安装零修改 → 残缺骨架停止 →
# 临时骨架准备 → 保存原内容 → 原子替换 → 复核 → 清理。
def install_project_transaction(project_root: str, token_path: str) -> int:
    # 先识别遗留事务：未恢复完成前不能开始新安装
    ok, message = recover_pending_transaction(project_root)
    if message:
        print(message)
    if not ok:
        print("请先解决上述问题，再重新运行官方安装脚本。")
        return 1

    # 校验一次性事务文件
    token, error = _validate_transaction_token(project_root, token_path)
    if token is None:
        print(f"安装事务校验失败：{error}")
        print("项目文件未修改。请通过官方安装脚本重新发起安装。")
        return 1

    # 骨架状态分流
    skeleton = check_skeleton(project_root)
    if skeleton.state == "installed":
        _mark_token_used(token_path, token)
        print("当前项目已经安装，未修改任何文件。")
        print("启动 Codex/OpenCode 并提出需求即可。")
        return 0
    if skeleton.state == "broken":
        print("当前项目的 workflow 安装骨架不完整或版本异常，安装已停止：")
        for problem in skeleton.problems:
            print(f"  - {problem}")
        print("未修改任何文件。请先人工确认这些内容后再处理，不能当作未安装项目覆盖。")
        return 1

    # 事务生效：从这里开始该事务不能再用于第二次写入
    _mark_token_used(token_path, token)

    # 在事务目录内准备并校验完整骨架
    staging_root, problems = _prepare_staging(project_root)
    if problems:
        print("安装包内的骨架资源不完整，安装已停止：")
        for problem in problems:
            print(f"  - {problem}")
        shutil.rmtree(_transaction_dir(project_root), ignore_errors=True)
        return 1

    # 先写可恢复的事务清单，再做第一次持久写入
    try:
        backups = _record_backups(project_root)
        manifest = {
            "product": PRODUCT_NAME,
            "version": PRODUCT_VERSION,
            "project_root": os.path.realpath(project_root),
            "created_at": _now_iso(),
            "status": "prepared",
            "allowed_paths": sorted(PROJECT_WRITE_PATHS),
            "backups": backups,
        }
        _save_manifest(project_root, manifest)
        _validate_recovery_manifest(project_root, manifest)
    except (OSError, ValueError) as exc:
        print(f"安装事务准备失败：{exc}")
        shutil.rmtree(_transaction_dir(project_root), ignore_errors=True)
        print("项目文件未修改。")
        return 1

    try:
        # 原子替换：把临时骨架移动进项目
        wf_dst = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME)
        os.makedirs(wf_dst, exist_ok=True)
        for dirname in (TEMPLATE_DIRNAME, STANDARDIZED_DIRNAME):
            src = os.path.join(staging_root, WORKFLOW_LOOP_DIRNAME, dirname)
            dst = os.path.join(wf_dst, dirname)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)
        shutil.move(
            os.path.join(staging_root, AGENTS_MD_FILENAME),
            os.path.join(project_root, AGENTS_MD_FILENAME),
        )
        # 精简项目级状态（installer_version + installed_at + project_design_initialized=false）
        create_project(project_root)

        # 复核：安装后骨架必须完整
        final = check_skeleton(project_root)
        if final.state != "installed":
            raise RuntimeError("安装后骨架复核失败: " + "; ".join(final.problems))
    except (OSError, RuntimeError) as exc:
        print(f"安装失败：{exc}")
        failures = _restore_from_manifest(project_root, manifest)
        if failures:
            print("回退不完整，以下路径未恢复（事务目录已保留，下次安装会先恢复）：")
            for item in failures:
                print(f"  - {item}")
            return 1
        shutil.rmtree(_transaction_dir(project_root), ignore_errors=True)
        print("本次安装的全部修改已恢复，项目回到安装前状态。")
        return 1

    # 事务提交并清理：不留下永久备份
    manifest["status"] = "committed"
    manifest["committed_at"] = _now_iso()
    _save_manifest(project_root, manifest)
    shutil.rmtree(_transaction_dir(project_root), ignore_errors=True)

    # 打印安装完成信息
    print("项目安装完成。")
    print(f"  .workflow_loop/{TEMPLATE_DIRNAME}/")
    print(f"  .workflow_loop/{STANDARDIZED_DIRNAME}/")
    print(f"  {AGENTS_MD_FILENAME}")
    print("  .workflow_loop/project.json")
    print("启动 Codex/OpenCode 并提出需求即可。")
    return 0
