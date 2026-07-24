import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# state.json 的相对路径（相对于项目根）
# 放在 .workflow_loop/ 下，和 journal.jsonl、project.json 同级
STATE_FILE = os.path.join(".workflow_loop", "state.json")


# 单个 stage 的 3 道闸状态（门禁策略第一版：顺序硬性）
# 三道闸依次推进：讨论完毕 → 代码校验 → 用户确认
# 跳步直接报错，不能跳过前一道直接调后一道
@dataclass
class GateState:
    # 第 1 道闸：用户确认讨论完毕（AI 和用户已经用提示词充分讨论）
    discussion_complete: bool = False
    # 第 2 道闸：代码侧校验通过（文件存在 / 内容哈希匹配等）
    code_validated: bool = False
    # 第 3 道闸：用户确认产出写完了（最终由用户拍板，AI 不得代确认）
    user_confirmed: bool = False


# 单个 stage 的完整状态
# 嵌套在 WorkflowState.stages 字典里，key 是 stage 名（如 "spec" / "plan"）
@dataclass
class StageState:
    # stage 生命周期状态：pending（没开始）→ in_progress（AI 在做）→ gated（等门禁）→ done（过了门禁）
    status: str = "pending"
    # 期望产出的文件路径列表（相对项目根），可能多个（如 spec 的 product.md + feature_*.md）
    artifact_paths: list[str] = field(default_factory=list)
    # 产出文件首次出现的时间戳（ISO 8601 UTC），用于 journal 追溯
    artifact_produced_at: str | None = None
    # 用户确认讨论完成时保存的文件基线时间；用于判断本阶段是否真的修改了产物
    artifact_baseline_captured_at: str | None = None
    # 基线文件哈希，key 是项目根下的相对路径，value 是 SHA256；文件当时不存在时为 None
    artifact_baseline_hashes: dict[str, str | None] = field(default_factory=dict)
    # 该 stage 的 3 道闸状态，嵌套 dataclass
    gate: GateState = field(default_factory=GateState)


# 架构文档双阶段完成度标记（CONTEXT.md "Architecture Gate Marks"）
# 同一份 architecture_code_design.md 的两种完成度，不是两个无关文件
@dataclass
class ArchitectureState:
    # 初步架构完成：前段架构 stage（code_design/revise_code_design/project_design_init）--confirmed 后置 true
    preliminary_done: bool = False
    # 详细架构完成：末段 update_code_design --confirmed 后置 true
    # 文件存在只是必要条件，不得因已存在而自动跳过详细架构收尾
    detailed_done: bool = False


# Verification Invalidation 的哈希绑定（CONTEXT.md "Verification Invalidation"）
# 通过状态只对绑定的上游内容有效；上游变化时下游门禁清零
@dataclass
class VerificationState:
    # 实施代码 + impl/ 下全部实施记录的 SHA256 哈希
    # 在 gate topic_execution --confirmed 时记录；进入最终全量回归和整体验收前检查
    impl_hash: str | None = None
    # qa/<topic>_plan.md 内容的 SHA256 哈希
    # 在 gate test_plan --confirmed 时记录；变化时使主题执行、最终全量回归和整体验收失效
    test_plan_hash: str | None = None
    # acceptance/<topic>_plan.md 内容的 SHA256 哈希
    # 在 gate acceptance_plan --confirmed 时记录；变化时退回测试计划和后续阶段
    acceptance_plan_hash: str | None = None
    # qa/<topic>_result.md 内容的 SHA256 哈希
    # 在 gate topic_execution --confirmed 时记录；变化时使最终全量回归和整体验收失效
    test_result_hash: str | None = None
    # qa/final_regression_result.md 内容的 SHA256 哈希
    # 在 gate regression_test --confirmed 时记录；变化时清零 overall_acceptance
    regression_test_result_hash: str | None = None


# 穿刺阶段开始时的设计文档基线
# 门2用它判断穿刺结论要求修改设计时，相关文档是否真的发生了变化
@dataclass
class SpikeBaselineState:
    # 记录基线的时间；非空表示已经完成基线记录，即使某个文件当时不存在
    captured_at: str | None = None
    # spec/product.md 及其功能清单链接文档的整体 SHA256 哈希
    product_design_hash: str | None = None
    # 参与产品设计整体哈希的相对路径，便于状态检查和问题定位
    product_design_paths: list[str] = field(default_factory=list)
    # spec/architecture_code_design.md 的 SHA256 哈希
    code_design_hash: str | None = None
    # 旧工作流已经进入 spike，但旧 state.json 没有保存入场基线
    # True 表示无法可靠还原穿刺开始前的设计内容，不能假装当前文件就是旧基线
    legacy_unavailable: bool = False


# 整个 workflow Run 的当前快照，对应 state.json 的完整结构
# 每次 CLI 调用都是新进程，state 必须落盘，下次进程启动时读回来
@dataclass
class WorkflowState:
    # 启动时生成，格式 YYYY-MM-DD-HHmm-<intent>，用于 journal 追溯和文件名
    workflow_id: str
    # 工作意图：from_scratch / product_change / bugfix（替代旧 entry/scenario）
    intent: str
    # Run 生命周期：active（进行中）/ completed（done 收工）/ aborted（abort 作废）
    # 替代用 current_stage=completed 推断 Run 状态的旧模型
    run_status: str = "active"
    # 当前 stage 名（如 "spec" / "plan" / ...）；末段 --confirmed 后临时置 "completed"，由 done 确认
    current_stage: str = ""
    # 启动时间 ISO 8601 UTC
    started_at: str = ""
    # done 时写结束时间（run_status=completed）；abort 时为 None
    ended_at: str | None = None
    # abort 时写作废时间（run_status=aborted）；done 时为 None
    aborted_at: str | None = None
    # 旧版单主题字段。只用于读取旧 state.json；新流程使用 topics。
    topic: str | None = None
    # 本次需求的全部验收主题。主题在 acceptance_plan 确认时确定。
    topics: list[str] = field(default_factory=list)
    # 从零做清场确认标记：workflow start --intent from_scratch --confirm-clean 时置 true
    clean_confirmed: bool = False
    # spike 跳过标记：gate spike --skip 时置 true
    spike_skipped: bool = False
    # PathComposer 在 start 时解析出的完整 stage 名顺序，固定不再变
    # 后续命令（discuss/gate）读这个列表找当前 stage 对应的策略类
    stage_path: list[str] = field(default_factory=list)
    # 每个 stage 的细粒度状态，key 是 stage 名
    stages: dict[str, StageState] = field(default_factory=dict)
    # 架构门禁标记（初步/详细），见 ArchitectureState
    architecture: ArchitectureState = field(default_factory=ArchitectureState)
    # 验证绑定哈希，见 VerificationState
    verification: VerificationState = field(default_factory=VerificationState)
    # 穿刺进入时的产品设计和代码设计基线
    spike_baseline: SpikeBaselineState = field(default_factory=SpikeBaselineState)
    # 自由扩展口子（hooks 等后面用，第一版为空）
    meta: dict = field(default_factory=dict)


# 生成 ISO 8601 UTC 时间戳，microsecond=0 让时间戳更干净
# 供 state 的 started_at/ended_at/aborted_at 和 journal 的 ts 字段复用
def now_iso() -> str:
    # datetime.now(timezone.utc) 拿到 UTC 时间
    # .replace(microsecond=0) 去掉微秒
    # .isoformat() 转 ISO 8601 字符串
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# 把 WorkflowState dataclass 转成可 JSON 序列化的 dict
# asdict 会递归把 dataclass 转成 dict，包括嵌套的 StageState 和 GateState
def state_to_dict(state: WorkflowState) -> dict:
    return asdict(state)


# 从 dict 反序列化成 WorkflowState dataclass
# 手动重建嵌套的 StageState 和 GateState，因为 dataclass 不自动处理嵌套 dict→dataclass
def state_from_dict(data: dict) -> WorkflowState:
    # 先把 stages dict 里的每个 stage 从裸 dict 重建为 StageState dataclass
    stages = {}
    # 遍历 state.json 里的 stages 字典，逐个重建
    for stage_name, stage_data in data.get("stages", {}).items():
        # 从 stage_data 重建 GateState（3 道闸）
        gate_data = stage_data.get("gate", {})
        gate = GateState(
            discussion_complete=gate_data.get("discussion_complete", False),
            code_validated=gate_data.get("code_validated", False),
            user_confirmed=gate_data.get("user_confirmed", False),
        )
        # 从 stage_data 重建 StageState
        stages[stage_name] = StageState(
            status=stage_data.get("status", "pending"),
            artifact_paths=stage_data.get("artifact_paths", []),
            artifact_produced_at=stage_data.get("artifact_produced_at"),
            artifact_baseline_captured_at=stage_data.get("artifact_baseline_captured_at"),
            artifact_baseline_hashes=stage_data.get("artifact_baseline_hashes", {}),
            gate=gate,
        )
    # 读 architecture 字段（架构门禁标记）
    arch_data = data.get("architecture", {})
    # 读 verification 字段（验证绑定哈希）
    verification_data = data.get("verification", {})
    # 读 spike_baseline 字段；旧 state.json 没有时按未记录处理
    spike_baseline_data = data.get("spike_baseline", {})
    # 兼容旧版单主题 state.json：没有 topics 时把 topic 转成单元素列表。
    legacy_topic = data.get("topic")
    topics = data.get("topics", [])
    if not topics and legacy_topic:
        topics = [legacy_topic]

    # 重建最外层的 WorkflowState
    return WorkflowState(
        workflow_id=data["workflow_id"],
        intent=data["intent"],
        run_status=data.get("run_status", "active"),
        current_stage=data.get("current_stage", ""),
        started_at=data.get("started_at", ""),
        ended_at=data.get("ended_at"),
        aborted_at=data.get("aborted_at"),
        topic=legacy_topic,
        topics=topics,
        clean_confirmed=data.get("clean_confirmed", False),
        spike_skipped=data.get("spike_skipped", False),
        stage_path=data.get("stage_path", []),
        stages=stages,
        architecture=ArchitectureState(
            preliminary_done=arch_data.get("preliminary_done", False),
            detailed_done=arch_data.get("detailed_done", False),
        ),
        verification=VerificationState(
            impl_hash=verification_data.get("impl_hash"),
            test_plan_hash=verification_data.get("test_plan_hash"),
            acceptance_plan_hash=verification_data.get("acceptance_plan_hash"),
            test_result_hash=verification_data.get("test_result_hash"),
            regression_test_result_hash=verification_data.get("regression_test_result_hash"),
        ),
        spike_baseline=SpikeBaselineState(
            captured_at=spike_baseline_data.get("captured_at"),
            product_design_hash=spike_baseline_data.get("product_design_hash"),
            product_design_paths=spike_baseline_data.get("product_design_paths", []),
            code_design_hash=spike_baseline_data.get("code_design_hash"),
            legacy_unavailable=spike_baseline_data.get("legacy_unavailable", False),
        ),
        meta=data.get("meta", {}),
    )


# 从被管理项目的 .workflow_loop/state.json 读取 state
# 如果文件不存在（还没 start 过），返回 None 让调用方处理
# project_root 是被管理项目的根目录路径
def load_state(project_root: str) -> WorkflowState | None:
    # 拼出 state.json 的完整路径（项目根 + .workflow_loop/state.json）
    path = os.path.join(project_root, STATE_FILE)
    # 文件不存在说明还没 start，返回 None
    if not os.path.exists(path):
        return None
    # 读文件、解析 JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 反序列化成 WorkflowState
    return state_from_dict(data)


# 把 WorkflowState 写到被管理项目的 .workflow_loop/state.json
# ensure_ascii=False 让中文不被转义成 \uXXXX；indent=2 让文件可读
def save_state(project_root: str, state: WorkflowState) -> None:
    # 拼出 state.json 的完整路径
    path = os.path.join(project_root, STATE_FILE)
    # 确保目录存在（第一次写时 .workflow_loop/ 可能还没建）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 序列化 dataclass → dict
    data = state_to_dict(state)
    # 写盘，ensure_ascii=False 保留中文可读性
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 判断当前项目是否有进行中的 Run（Active Run Guard 用）
# state.json 存在且 run_status=active → True（禁止再 start）
# state.json 不存在 / completed / aborted → False（允许新 start）
def is_active_run(project_root: str) -> bool:
    # 读 state
    state = load_state(project_root)
    # state 存在且 run_status 是 active 才返回 True
    return state is not None and state.run_status == "active"
