"""门禁校验的结构化诊断结果。

本模块只保存、排序和渲染已经得到的检查事实。它不读取项目文件、不执行命令，
也不修改工作流状态；具体校验器负责提供准确的位置、证据和修复动作。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal


DiagnosticKind = Literal["error", "not_checked"]

# 工作流阶段的固定次序。未知阶段排在已知阶段之后，再按阶段名排序，保证扩展
# 阶段也有确定结果。这里包含三类完整流程可能出现的阶段。
STAGE_ORDER = (
    "spec",
    "code_design",
    "revise_code_design",
    "project_design_init",
    "reproduce",
    "spike",
    "acceptance_plan",
    "impl",
    "qa",
    "test_plan",
    "test_code",
    "test_execution",
    "topic_acceptance",
    "regression_test",
    "overall_acceptance",
    "update_code_design",
    "completed",
)
_STAGE_RANK = {stage: index for index, stage in enumerate(STAGE_ORDER)}

_LINE_PATTERNS = (
    re.compile(r"第\s*(?P<line>\d+)\s*行"),
    re.compile(r"\bline\s+(?P<line>\d+)\b", re.IGNORECASE),
    re.compile(r":(?P<line>\d+)(?::\d+)?(?:\b|$)"),
)


def _required_text(value: object, field_name: str) -> str:
    """把必填展示字段规范为非空文字。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _normalize_location(location: str) -> str:
    """规范路径分隔符和空白，只用于稳定排序，不修改展示文字。"""
    return " ".join(location.replace("\\", "/").split())


def _location_line(location: str) -> int:
    """从常见的文件位置写法中提取行号；没有行号时排在有行号之后。"""
    normalized = _normalize_location(location)
    for pattern in _LINE_PATTERNS:
        matched = pattern.search(normalized)
        if matched:
            return int(matched.group("line"))
    return 2**31 - 1


def _location_path(location: str) -> str:
    """提取位置中的文件或状态路径部分，供行号之前的稳定排序使用。"""
    normalized = _normalize_location(location)
    backtick_path = re.search(r"`([^`]+)`", normalized)
    if backtick_path:
        return backtick_path.group(1)
    return re.split(
        r":(?=\d+(?::\d+)?(?:\b|$))|\s+(?=第\s*\d)|\s+(?=字段\b)",
        normalized,
        maxsplit=1,
    )[0]


@dataclass(frozen=True)
class Diagnostic:
    """一个可以单独处理的错误或因前置失败而未执行的检查。"""

    kind: DiagnosticKind
    check_id: str
    location: str
    expected: str
    actual: str
    evidence: str
    impact: str
    next_action: str
    depends_on: tuple[str, ...] | list[str] | str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"error", "not_checked"}:
            raise ValueError("kind 只能是 error（错误）或 not_checked（未检查）")
        for field_name in (
            "check_id",
            "location",
            "expected",
            "actual",
            "evidence",
            "impact",
            "next_action",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )

        dependencies = self.depends_on
        if dependencies is None:
            normalized_dependencies: tuple[str, ...] = ()
        elif isinstance(dependencies, str):
            normalized_dependencies = (_required_text(dependencies, "depends_on"),)
        else:
            normalized_dependencies = tuple(
                sorted({_required_text(item, "depends_on") for item in dependencies})
            )
        if self.kind == "not_checked" and not normalized_dependencies:
            raise ValueError("not_checked（未检查）诊断必须说明 depends_on（前置检查）")
        object.__setattr__(self, "depends_on", normalized_dependencies)

    def sort_key(self, stage: str = "") -> tuple[object, ...]:
        """返回不依赖插入、字典或文件遍历顺序的固定排序键。"""
        stage_rank = _STAGE_RANK.get(stage, len(STAGE_ORDER))
        kind_rank = 0 if self.kind == "error" else 1
        location = _normalize_location(self.location)
        return (
            stage_rank,
            stage,
            self.check_id,
            _location_path(location),
            _location_line(location),
            location,
            kind_rank,
            self.expected,
            self.actual,
            self.evidence,
            self.impact,
            self.next_action,
            self.depends_on,
        )

    def to_dict(self) -> dict[str, object]:
        """返回可写入日志摘要或用于哈希的确定字段。"""
        return {
            "kind": self.kind,
            "check_id": self.check_id,
            "location": self.location,
            "expected": self.expected,
            "actual": self.actual,
            "evidence": self.evidence,
            "impact": self.impact,
            "next_action": self.next_action,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class NextCommand:
    """门禁输出末尾唯一下一条完整命令及其执行边界。"""

    command: str
    executor: str
    side_effects: str
    success_condition: str
    next_stage: str

    def __post_init__(self) -> None:
        for field_name in (
            "command",
            "executor",
            "side_effects",
            "success_condition",
            "next_stage",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if "\n" in self.command or "\r" in self.command:
            raise ValueError("command 必须是一条单行完整命令")

    def to_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "executor": self.executor,
            "side_effects": self.side_effects,
            "success_condition": self.success_condition,
            "next_stage": self.next_stage,
        }


# 名称强调这是命令的元数据；保留短名称便于调用方阅读。
NextCommandMetadata = NextCommand


@dataclass
class ValidationReport:
    """一道门当前能够确定的全部诊断和唯一后续命令。"""

    stage: str
    gate: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    passed: bool | None = None
    next_command: NextCommand | None = None

    def __post_init__(self) -> None:
        self.stage = _required_text(self.stage, "stage")
        self.gate = _required_text(self.gate, "gate")
        self.diagnostics = list(self.diagnostics)
        for diagnostic in self.diagnostics:
            if not isinstance(diagnostic, Diagnostic):
                raise TypeError("diagnostics 中的每一项都必须是 Diagnostic")
        if self.next_command is not None and not isinstance(self.next_command, NextCommand):
            raise TypeError("next_command 必须是 NextCommand 或 None")
        if self.diagnostics:
            self.passed = False
        elif self.passed is None:
            self.passed = True
        else:
            self.passed = bool(self.passed)

    @property
    def sorted_diagnostics(self) -> list[Diagnostic]:
        """按固定键返回副本，不依赖调用方的追加顺序。"""
        return sorted(self.diagnostics, key=lambda item: item.sort_key(self.stage))

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.sorted_diagnostics if item.kind == "error"]

    @property
    def not_checked(self) -> list[Diagnostic]:
        return [item for item in self.sorted_diagnostics if item.kind == "not_checked"]

    def add(self, diagnostic: Diagnostic) -> Diagnostic:
        """追加一项检查事实，并立即保证报告不能被误判为通过。"""
        if not isinstance(diagnostic, Diagnostic):
            raise TypeError("diagnostic 必须是 Diagnostic")
        self.diagnostics.append(diagnostic)
        self.passed = False
        return diagnostic

    def add_error(
        self,
        *,
        check_id: str,
        location: str,
        expected: str,
        actual: str,
        evidence: str,
        impact: str,
        next_action: str,
    ) -> Diagnostic:
        diagnostic = Diagnostic(
            kind="error",
            check_id=check_id,
            location=location,
            expected=expected,
            actual=actual,
            evidence=evidence,
            impact=impact,
            next_action=next_action,
        )
        return self.add(diagnostic)

    def add_not_checked(
        self,
        *,
        check_id: str,
        location: str,
        expected: str,
        actual: str,
        evidence: str,
        impact: str,
        next_action: str,
        depends_on: tuple[str, ...] | list[str] | str,
    ) -> Diagnostic:
        diagnostic = Diagnostic(
            kind="not_checked",
            check_id=check_id,
            location=location,
            expected=expected,
            actual=actual,
            evidence=evidence,
            impact=impact,
            next_action=next_action,
            depends_on=depends_on,
        )
        return self.add(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic] | ValidationReport) -> None:
        """合并子校验器报告，不丢弃子项中的具体定位和证据。"""
        items = diagnostics.diagnostics if isinstance(diagnostics, ValidationReport) else diagnostics
        for diagnostic in items:
            self.add(diagnostic)

    def to_dict(self) -> dict[str, object]:
        """返回按稳定顺序排列的完整报告数据。"""
        return {
            "stage": self.stage,
            "gate": self.gate,
            "diagnostics": [item.to_dict() for item in self.sorted_diagnostics],
            "passed": bool(self.passed),
            "next_command": self.next_command.to_dict() if self.next_command else None,
        }

    @property
    def report_hash(self) -> str:
        """计算不含时间和随机值的确定性报告指纹。"""
        payload = self.to_dict()
        # passed 完全由诊断项决定，不单独参加哈希，避免重复表达同一事实。
        payload.pop("passed", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def render(self, *, include_hash: bool = True) -> str:
        return format_validation_report(self, include_hash=include_hash)

    def to_legacy_tuple(self) -> tuple[bool, str]:
        """供仍接收 ``tuple[bool, str]`` 的阶段接口逐步迁移。"""
        if self.passed:
            detail = "校验通过"
        else:
            detail = format_diagnostics(self)
        return (bool(self.passed), detail)


def stable_sort_diagnostics(
    diagnostics: Iterable[Diagnostic],
    *,
    stage: str = "",
) -> list[Diagnostic]:
    """给尚未创建 ValidationReport 的底层校验器提供相同排序规则。"""
    return sorted(diagnostics, key=lambda item: item.sort_key(stage))


def format_diagnostics(report: ValidationReport) -> str:
    """格式化问题清单；不附加命令，适合放进旧接口的“详情”字段。"""
    errors = len(report.errors)
    not_checked = len(report.not_checked)
    lines = [f"共发现 {errors + not_checked} 项：错误 {errors} 项，未检查 {not_checked} 项"]
    for index, diagnostic in enumerate(report.sorted_diagnostics, start=1):
        label = "错误" if diagnostic.kind == "error" else "未检查"
        lines.extend(
            [
                f"{index}. [{label}] {diagnostic.check_id}",
                f"   位置: {diagnostic.location}",
                f"   预期: {diagnostic.expected}",
                f"   实际: {diagnostic.actual}",
                f"   证据: {diagnostic.evidence}",
                f"   影响: {diagnostic.impact}",
                f"   下一动作: {diagnostic.next_action}",
            ]
        )
        if diagnostic.depends_on:
            lines.append(f"   前置检查: {', '.join(diagnostic.depends_on)}")
    if not report.passed:
        lines.append("请按上述每项“下一动作”处理；状态和内容未变化时不要重复执行同一条失败命令。")
    return "\n".join(lines)


def format_validation_report(
    report: ValidationReport,
    *,
    include_hash: bool = True,
) -> str:
    """把报告渲染成固定顺序的中文命令输出。"""
    result = "通过" if report.passed else "失败"
    lines = [
        f"阶段: {report.stage}",
        f"门禁: {report.gate}",
        f"校验结果: {result}",
        format_diagnostics(report),
    ]
    command = report.next_command
    if command is None:
        lines.extend(
            [
                "下一步命令: 未提供",
                "执行者: 未提供",
                "自动动作: 未提供",
                "成功条件: 未提供",
                "成功后阶段: 未提供",
            ]
        )
    else:
        lines.extend(
            [
                f"下一步命令: {command.command}",
                f"执行者: {command.executor}",
                f"自动动作: {command.side_effects}",
                f"成功条件: {command.success_condition}",
                f"成功后阶段: {command.next_stage}",
            ]
        )
    if include_hash:
        lines.append(f"报告哈希: {report.report_hash}")
    return "\n".join(lines)


def report_from_legacy_result(
    result: tuple[bool, str],
    *,
    stage: str,
    gate: str,
    next_command: NextCommand | None,
    check_id: str = "legacy_validation",
    location: str = "旧校验器返回值",
    expected: str = "校验通过",
    impact: str = "当前门禁不能通过",
    next_action: str = "根据实际信息修复后重新执行当前门禁",
) -> ValidationReport:
    """把现有 ``(是否通过, 详情)`` 包成报告，供调用方渐进迁移。

    旧文字通常没有精确位置，因此调用方应尽量显式传入 ``check_id``、
    ``location``、``impact`` 和 ``next_action``，而不是长期依赖默认值。
    """
    passed, detail = result
    report = ValidationReport(
        stage=stage,
        gate=gate,
        passed=bool(passed),
        next_command=next_command,
    )
    if not passed:
        actual = detail.strip() if isinstance(detail, str) and detail.strip() else "旧校验器未提供详情"
        report.add_error(
            check_id=check_id,
            location=location,
            expected=expected,
            actual=actual,
            evidence=actual,
            impact=impact,
            next_action=next_action,
        )
    return report


def legacy_result(report: ValidationReport) -> tuple[bool, str]:
    """函数形式的兼容出口，等价于 ``report.to_legacy_tuple()``。"""
    return report.to_legacy_tuple()


# 较直白的别名，方便命令层和领域校验器使用一致叫法。
render_validation_report = format_validation_report
from_legacy_result = report_from_legacy_result
