from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from workflow_loop import PRODUCT_NAME, __version__
from workflow_loop import installer as installer_mod
from workflow_loop import records as records_mod
from workflow_loop.artifact_validation import validate_product_design_documents
from workflow_loop.state import StageState, WorkflowState, load_state


def _run_cli(args: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "workflow_loop.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _install_project(root: Path) -> None:
    token_path = root / ".install-token.json"
    token_path.write_text(
        json.dumps(
            {
                "product": PRODUCT_NAME,
                "version": __version__,
                "project_root": str(root.resolve()),
                "allowed_paths": sorted(installer_mod.PROJECT_WRITE_PATHS),
                "used": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    code, out, err = _run_cli(
        ["_install-project", "--transaction", str(token_path)],
        root,
    )
    assert code == 0, f"installation failed: {out} {err}"


def _write_custom_spec(root: Path) -> tuple[Path, Path]:
    spec_dir = root / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    overview = spec_dir / "产品总说明.md"
    overview.write_text(
        """# 示例工具 — 产品总说明

## 1. 产品背景与目标

说明背景与目标。

<a id="6-产品通用规则"></a>
## 6. 产品通用规则

| 规则 | 适用范围 | 具体说明 |
|---|---|---|
| 规则一 | 全部 | 不删原仓 |

<a id="7-产品功能"></a>
## 7. 产品功能

全套按操作对象分 1 大类，列出技术文档索引：

| 操作对象 | 功能 | 一句话说明 | 对应场景 | 对应技术文档 | 详细功能文档 |
|---|---|---|---|---|---|
| 一、面向工具 | 工具安装 | 命令行引导安装 | 安装场景 | [技 1](./tech/t1.md) | [01 工具安装](./功能_01_工具安装.md) |

---

## 8. 相关文档

| 编号 | 说明 |
|---|---|
| 技 1 | 内部调用 `OsRuntimePort.chunk_command_args()` 与 `defaults.build_system` |

## 9. 修改记录

| 日期 | 工作流编号 | 修改内容 |
|---|---|---|
| 2026-11-26 | init | 同步 `session.json.task_states` 与 `sign(auth_preflight)` |
""",
        encoding="utf-8",
    )
    tech_dir = spec_dir / "tech"
    tech_dir.mkdir(parents=True, exist_ok=True)
    (tech_dir / "t1.md").write_text("# 技 1\n", encoding="utf-8")
    feature = spec_dir / "功能_01_工具安装.md"
    feature.write_text(
        """# 【功能】工具安装

总表入口：[产品总说明 · 第 7 章](./产品总说明.md#7-产品功能)

## 1. 背景

用户安装后可见版本提示 `vX.Y.Z`，通过 `project_migrate(full)` 发起任务，或调用 `POST /api/shutdown` 关闭本机服务。

## 2. 场景

查看 `session.json.stale_steps` 与 `errors.json(BUG-nnn)`。

```text
· src/export/pdf_worker.cpp:142 示例输出路径
```
""",
        encoding="utf-8",
    )
    return overview, feature


def test_from_scratch_prompts_keep_spec_when_only_spec_exists(tmp_path: Path) -> None:
    _install_project(tmp_path)
    _write_custom_spec(tmp_path)

    code, out, err = _run_cli(["start", "--intent", "from_scratch"], tmp_path)

    assert code == 0, err
    assert "--confirm-clean" in out
    assert "--keep-spec" in out
    assert (tmp_path / "spec" / "产品总说明.md").is_file()
    assert load_state(str(tmp_path)) is None


def test_keep_spec_rejects_invalid_combinations_and_other_artifacts(tmp_path: Path) -> None:
    _install_project(tmp_path)
    _write_custom_spec(tmp_path)

    # 与 --confirm-clean 互斥
    code, out, _ = _run_cli(
        ["start", "--intent", "from_scratch", "--confirm-clean", "--keep-spec"],
        tmp_path,
    )
    assert code != 0
    assert "互斥" in out

    # 非 from_scratch 不可用
    code, out, _ = _run_cli(["start", "--intent", "product_change", "--keep-spec"], tmp_path)
    assert code != 0
    assert "仅适用于 from_scratch" in out

    # 存在除 spec/ 外的旧下游目录时报错
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "old.md").write_text("old", encoding="utf-8")
    code, out, _ = _run_cli(["start", "--intent", "from_scratch", "--keep-spec"], tmp_path)
    assert code != 0
    assert "qa/" in out
    assert (tmp_path / "spec" / "产品总说明.md").is_file()


def test_keep_spec_preserves_custom_chapter7_and_passes_spec_gates(tmp_path: Path) -> None:
    _install_project(tmp_path)
    overview, _feature = _write_custom_spec(tmp_path)
    original_overview = overview.read_text(encoding="utf-8")

    # 启动 --keep-spec：不删 spec/，状态记录 keep_existing_spec=True
    code, out, err = _run_cli(["start", "--intent", "from_scratch", "--keep-spec"], tmp_path)
    assert code == 0, f"{out}\n{err}"
    assert "承接已有设计: spec/" in out
    state = load_state(str(tmp_path))
    assert state is not None
    assert state.keep_existing_spec is True
    assert state.clean_confirmed is False
    assert overview.read_text(encoding="utf-8") == original_overview

    # 跑 discuss 并过门 1
    code, out, err = _run_cli(["discuss"], tmp_path)
    assert code == 0, f"{out}\n{err}"
    code, out, err = _run_cli(["gate", "spec", "--discuss-done"], tmp_path)
    assert code == 0, f"{out}\n{err}"

    # 填 product_features，但不填核对结论 -> 应提示补填核对结论且不改写第 7 章
    wf_id = state.workflow_id
    pf_path = tmp_path / ".workflow_loop" / "records" / wf_id / "product_features_product_features.json"
    table = json.loads(pf_path.read_text(encoding="utf-8"))
    table["功能"] = [
        {
            "功能名称": "工具安装",
            "一句话说明": "命令行引导安装",
            "对应场景": "安装场景",
            "功能文档路径": "./功能_01_工具安装.md",
        }
    ]
    pf_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    code, out, err = _run_cli(["gate", "spec"], tmp_path)
    assert code == 0, err
    assert "核对结论" in out
    assert overview.read_text(encoding="utf-8") == original_overview

    # 补填实质性的核对结论后，再跑门 2 -> 必须通过，且原第 7 章 6 列表与导语一字未改
    table = json.loads(pf_path.read_text(encoding="utf-8"))
    table["核对结论"] = [
        {
            "核对对象": "spec/产品总说明.md 及全部既有功能文档",
            "核对依据": "已逐份核对既有定稿 1 份功能文档及技术文档索引，本轮直接承接进入下游阶段",
        }
    ]
    pf_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    code, out, err = _run_cli(["gate", "spec"], tmp_path)
    assert code == 0, err
    assert "代码校验通过" in out or "门 2" in out or "通过" in out
    assert "校验结果: 失败" not in out
    assert overview.read_text(encoding="utf-8") == original_overview

    # 门 3 确认进入 spike
    code, out, err = _run_cli(["gate", "spec", "--confirmed"], tmp_path)
    assert code == 0, f"{out}\n{err}"
    next_state = load_state(str(tmp_path))
    assert next_state is not None
    assert next_state.current_stage == "spike"

    # 作废后仍完整保留原有 spec/
    code, out, err = _run_cli(["abort"], tmp_path)
    assert code == 0, f"{out}\n{err}"
    assert overview.read_text(encoding="utf-8") == original_overview


def test_preserved_custom_feature_table_detects_mismatch_without_overwriting(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    overview, _ = _write_custom_spec(root)
    original_overview = overview.read_text(encoding="utf-8")

    relative = records_mod.create_or_complete_table(str(root), "wf-1", "product_features", "")
    table_path = root / relative
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["功能"] = [
        {
            "功能名称": "工具安装",
            "一句话说明": "命令行引导安装",
            "对应场景": "安装场景",
            "功能文档路径": "./功能_02_不存在.md",
        }
    ]
    table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

    wf_state = WorkflowState(
        workflow_id="wf-1",
        intent="from_scratch",
        keep_existing_spec=True,
        current_stage="spec",
        stage_path=["spec"],
        stages={"spec": StageState(status="in_progress")},
        table_format_version=records_mod.TABLE_FORMAT_VERSION,
    )
    problems, _docs = records_mod.sync_stage_tables(str(root), wf_state)
    assert any("路径不一致" in msg for _cat, msg in problems), problems
    assert overview.read_text(encoding="utf-8") == original_overview


def test_product_doc_boundary_eliminates_false_positives_and_keeps_true_positives(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir(parents=True)
    (spec_dir / "产品总说明.md").write_text(
        """# 示例产品 — 产品总说明

## 1. 产品背景与目标

支持 `project_migrate(full)`、`project_migrate(eval/plan)` 与 `sign(auth_preflight)`。

## 7. 产品功能

| 功能 | 一句话说明 | 对应场景 | 详细文档 |
|---|---|---|---|
| 示例功能 | 说明 | 场景 | [示例功能](./功能_示例.md) |

## 8. 相关文档

- 技 1：`OsRuntimePort.chunk_command_args()` 与 `defaults.build_system`、`POST /api/shutdown`。

## 9. 修改记录

| 日期 | 编号 | 内容 |
|---|---|---|
| 2026-11-26 | wf-1 | 记录 `session.json.task_states` 历史变更 |
""",
        encoding="utf-8",
    )
    feature = spec_dir / "功能_示例.md"
    feature.write_text(
        """# 【功能】示例功能

提示“已自动更新至 vX.Y.Z”，支持 `project_migrate(unsigned)`、查看 `session.json.stale_steps` 与 `errors.json(BUG-nnn)`。

```text
· src/export/pdf_worker.cpp:142 被测项目输出示例
```
""",
        encoding="utf-8",
    )

    ok, detail = validate_product_design_documents(str(tmp_path))
    assert ok is True, detail

    # 真正的内部实现引用仍须严格拦截
    feature.write_text(
        feature.read_text(encoding="utf-8")
        + "\n内部位于 `app/api/chat/route.ts`，调用 `GET /api/internal/docs`、"
        + "`documents.source_path`、`SyncService.runClearAll` 与 `detect_machine()`。\n",
        encoding="utf-8",
    )
    ok, detail = validate_product_design_documents(str(tmp_path))
    assert ok is False
    assert "app/api/chat/route.ts" in detail
    assert "GET /api/internal/docs" in detail
    assert "documents.source_path" in detail
    assert "SyncService.runClearAll" in detail
    assert "detect_machine()" in detail
