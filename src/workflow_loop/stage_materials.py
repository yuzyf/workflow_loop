"""阶段材料清单：检查必读文件、生成有序清单和内容指纹。

材料的消费者是 AI：`workflow discuss` 只输出经过存在性和可读性检查的绝对路径、
用途和读取顺序，不在 stdout 重复正文。程序保存内容指纹，用于发现讨论后材料
又被修改的情况；指纹和清单记录都只证明程序给出过当时有效的完整清单，
不能冒充 AI 已经阅读或理解的证明。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

# .workflow_loop 目录名（材料相对路径都以它为根）
WORKFLOW_LOOP_DIRNAME = ".workflow_loop"

# 所有阶段共同的全局必读材料，按顺序排在阶段材料之前。
# 每项是 (相对 .workflow_loop/ 的路径, 用途说明)。
GLOBAL_MATERIALS: list[tuple[str, str]] = [
    (
        "Standardized_Repository/global/document_writing.md",
        "全局写作规范：所有阶段的正式文档和回复共同遵守的表达规则",
    ),
    (
        "Standardized_Repository/global/workflow_lifecycle.md",
        "全局工作流生命周期规范：返回、作废与收工的统一规则",
    ),
]


class MaterialError(ValueError):
    """材料缺失、不是普通文件或不可读时抛出；调用方不得登记本次清单。"""


@dataclass
class StageMaterial:
    """清单中的一份必读材料。"""

    order: int
    # 相对 .workflow_loop/ 的路径；None 表示该项没有对应文件（明示"无"）
    relative_path: str | None
    # 当前操作系统的原生绝对路径；None 表示没有文件
    absolute_path: str | None
    # 这份文件的用途
    purpose: str
    # 没有文件时的明示说明
    note: str = ""


@dataclass
class MaterialChecklist:
    """一个阶段的完整材料清单。"""

    stage_name: str
    role_title: str
    role_description: str
    # 程序按当前状态生成的短阶段任务说明
    task_text: str
    # 按读取顺序排列的真实必读文件
    materials: list[StageMaterial] = field(default_factory=list)
    # 明示"无"的占位项（该阶段没有对应模板或规范）
    placeholders: list[StageMaterial] = field(default_factory=list)
    # 清单内容指纹：覆盖角色说明、阶段任务、全部材料路径与正文
    fingerprint: str = ""


def _validate_material_file(absolute_path: str, relative_path: str) -> str:
    """检查真实存在、是普通文件且可读；返回文件内容。"""
    if not os.path.exists(absolute_path):
        raise MaterialError(f"必读材料不存在: {relative_path}（{absolute_path}）")
    if not os.path.isfile(absolute_path):
        raise MaterialError(f"必读材料不是普通文件: {relative_path}（{absolute_path}）")
    try:
        with open(absolute_path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError as exc:
        raise MaterialError(f"必读材料无法读取: {relative_path}（{exc}）") from exc
    except UnicodeDecodeError as exc:
        raise MaterialError(f"必读材料不是可读文本: {relative_path}（{exc}）") from exc


def build_checklist(
    project_root: str,
    stage_name: str,
    role_doc: dict | None,
    task_text: str,
    stage_specs: list,
) -> MaterialChecklist:
    """组装并校验当前阶段的材料清单，计算内容指纹。

    stage_specs 是阶段策略 `materials()` 返回的 MaterialSpec 列表
    （relative_path 为 None 表示该阶段没有对应材料，明示"无"）。
    任一文件不满足存在、普通文件、可读时抛 MaterialError，调用方不得登记清单。
    """
    role_title = (role_doc or {}).get("role", "")
    role_description = (role_doc or {}).get("description", "")

    checklist = MaterialChecklist(
        stage_name=stage_name,
        role_title=role_title,
        role_description=role_description,
        task_text=task_text,
    )

    # 指纹覆盖：阶段名、角色说明、内置阶段任务、全部材料的路径与正文、占位项
    digest = hashlib.sha256()
    digest.update(f"stage:{stage_name}\n".encode("utf-8"))
    digest.update(f"role:{role_title}\n{role_description}\n".encode("utf-8"))
    digest.update(f"task:{task_text}\n".encode("utf-8"))

    order = 0
    all_specs = [
        (relative_path, purpose, "")
        for relative_path, purpose in GLOBAL_MATERIALS
    ] + [
        (spec.relative_path, spec.purpose, spec.missing_note)
        for spec in stage_specs
    ]
    for relative_path, purpose, missing_note in all_specs:
        if relative_path is None:
            checklist.placeholders.append(
                StageMaterial(
                    order=-1,
                    relative_path=None,
                    absolute_path=None,
                    purpose=purpose,
                    note=missing_note or "无",
                )
            )
            digest.update(f"none:{purpose}:{missing_note}\n".encode("utf-8"))
            continue
        order += 1
        # 绝对路径使用当前操作系统的原生格式，可直接交给文件读取工具
        absolute_path = os.path.abspath(
            os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, relative_path)
        )
        content = _validate_material_file(absolute_path, relative_path)
        checklist.materials.append(
            StageMaterial(
                order=order,
                relative_path=relative_path,
                absolute_path=absolute_path,
                purpose=purpose,
            )
        )
        digest.update(f"file:{relative_path}\n".encode("utf-8"))
        digest.update(content.encode("utf-8"))
        digest.update(b"\n")

    checklist.fingerprint = digest.hexdigest()
    return checklist


def compute_fingerprint(
    project_root: str,
    stage_name: str,
    role_doc: dict | None,
    task_text: str,
    stage_specs: list,
) -> str:
    """只计算当前材料指纹；文件缺失或不可读时同样抛 MaterialError。"""
    return build_checklist(
        project_root,
        stage_name,
        role_doc,
        task_text,
        stage_specs,
    ).fingerprint
