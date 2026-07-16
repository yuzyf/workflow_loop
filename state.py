"""
state.py：state.json 的读写模块。

职责：
- 把 workflow 的当前快照（current_stage、各 stage 的 gate 状态、topic 等）持久化到 state.json
- 每次命令调用都是新进程，state 必须落盘，下次进程启动时读回来
- state 和 journal 分离：state 是"现在在哪"（可重写），journal 是"发生过啥"（只追加）

设计模式：
- 用 dataclass 做 state 的数据模型，字段类型显式、可读
- 用类方法封装读写逻辑，调用方不用关心 JSON 序列化细节
"""
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class GateState:
    """单个 stage 的 3 道闸状态。3 道闸顺序硬性：discussion_complete → code_validated → user_confirmed。"""
    discussion_complete: bool = False  # 第 1 道闸：用户确认讨论完毕
    code_validated: bool = False       # 第 2 道闸：代码侧校验通过（文件存在等）
    user_confirmed: bool = False       # 第 3 道闸：用户确认产出写完了


@dataclass
class StageState:
    """单个 stage 的完整状态：产出路径、3 道闸、产出时间戳。"""
    status: str = "pending"                       # pending | in_progress | gated | done
    artifact_paths: list[str] = field(default_factory=list)  # 期望产出的文件路径列表（可能多个）
    artifact_produced_at: str | None = None      # 产出文件首次出现的时间戳（ISO 8601 UTC）
    gate: GateState = field(default_factory=GateState)  # 3 道闸状态，嵌套 dataclass


@dataclass
class WorkflowState:
    """整个 workflow 的当前快照。对应 state.json 的完整结构。"""
    workflow_id: str                              # 启动时生成，格式 YYYY-MM-DD-HHmm-<entry>
    entry: str                                    # 入口策略名（new_project / bugfix 等）
    scenario: str                                 # 场景策略名（穿刺中和 entry 相同）
    current_stage: str                            # 当前 stage 名（spec / plan / 验收 / qa / impl / ... / completed）
    started_at: str                               # 启动时间 ISO 8601 UTC
    completed_at: str | None = None              # 完成时间，未完成时为 None
    topic: str | None = None                     # 主题字符串，plan/fix_plan stage 定下后写入
    stages: dict[str, StageState] = field(default_factory=dict)  # 每个 stage 的细粒度状态
    meta: dict = field(default_factory=dict)     # 自由扩展口子（hooks 等后面用）


# ── 读写逻辑 ──────────────────────────────────────────────

# state.json 的存放路径：被管理项目的 .workflow_loop/state.json
STATE_FILE = os.path.join(".workflow_loop", "state.json")


def _now_iso() -> str:
    """生成 ISO 8601 UTC 时间戳，microsecond=0（和 Trellis 的 last_seen_at 格式一致）。"""
    # datetime.now(timezone.utc) 拿到 UTC 时间
    # .replace(microsecond=0) 去掉微秒，让时间戳更干净
    # .isoformat() 转 ISO 8601 字符串
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_to_dict(state: WorkflowState) -> dict:
    """把 WorkflowState dataclass 转成可 JSON 序列化的 dict。
    嵌套的 StageState 和 GateState 也要递归转成 dict。"""
    # asdict 会递归把 dataclass 转成 dict，包括嵌套的 StageState 和 GateState
    return asdict(state)


def state_from_dict(data: dict) -> WorkflowState:
    """从 dict 反序列化成 WorkflowState dataclass。
    手动重建嵌套的 StageState 和 GateState，因为 dataclass 不自动处理嵌套 dict→dataclass。"""
    # 先把 stages dict 里的每个 stage 从裸 dict 重建为 StageState dataclass
    stages = {}
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
            gate=gate,
        )
    # 重建最外层的 WorkflowState
    return WorkflowState(
        workflow_id=data["workflow_id"],
        entry=data["entry"],
        scenario=data["scenario"],
        current_stage=data["current_stage"],
        started_at=data["started_at"],
        completed_at=data.get("completed_at"),
        topic=data.get("topic"),
        stages=stages,
        meta=data.get("meta", {}),
    )


def load_state(project_root: str) -> WorkflowState | None:
    """从被管理项目的 .workflow_loop/state.json 读取 state。
    如果文件不存在（还没 start 过），返回 None。
    project_root 是被管理项目的根目录路径。"""
    # 拼出 state.json 的完整路径
    path = os.path.join(project_root, STATE_FILE)
    # 文件不存在说明还没 start，返回 None 让调用方处理
    if not os.path.exists(path):
        return None
    # 读文件、解析 JSON、反序列化成 WorkflowState
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return state_from_dict(data)


def save_state(project_root: str, state: WorkflowState) -> None:
    """把 WorkflowState 写到被管理项目的 .workflow_loop/state.json。
    ensure_ascii=False 让中文不被转义成 \\uXXXX。
    indent=2 让文件可读（人调试时看）。"""
    path = os.path.join(project_root, STATE_FILE)
    # 确保目录存在（第一次写时 .workflow_loop/ 可能还没建）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 序列化 + 写盘
    data = state_to_dict(state)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_iso() -> str:
    """对外暴露的 ISO 时间戳生成函数，供其他模块（journal.py 等）复用。"""
    return _now_iso()
