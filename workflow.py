"""
workflow.py：CLI 入口 + 命令 dispatch + stdout 驱动。

这是 AI 直接调用的入口。每条命令：
1. 读 state.json → 干一件事 → 写 state.json + 追加 journal.jsonl → 打印 stdout → 退出
2. stdout 末尾必须以 `───── 下一步：xxx ─────` 结尾（stdout 驱动原则，见 DESIGN.md 第 4.6 节）

8 条命令：
  overview / align / start / discuss / gate(--discuss-done/--confirmed) / status / done

AI 调用流程：
  AGENT.md（3 行）→ "先调 overview"
  → overview stdout 末尾 → "下一步：调 align"
  → align stdout 末尾 → "下一步：问用户，调 start --entry <回答>"
  → start stdout 末尾 → "下一步：调 discuss"
  → discuss stdout 末尾 → "下一步：和用户讨论，调 gate --discuss-done"
  → ... 循环到 done

设计模式：
- 命令模式：每条命令是一个 handler 函数，dispatch 用 if/elif 分发
- 策略模式：根据 state.current_stage 实例化对应 StageStrategy
- stdout 驱动：每条命令的 stdout 末尾告诉 AI 下一步，AI 不用记流程
"""
import argparse
import os
import sys

# 导入内部模块
import state as state_mod
import journal as journal_mod
import role_doc as role_doc_mod
from strategies.scenarios import SCENARIO_REGISTRY
from strategies.base import StageStrategy


# ── 常量 ─────────────────────────────────────────────────

# stdout 分隔线，用于分隔"命令输出"和"下一步指令"
NEXT_STEP_SEPARATOR = "─" * 42

# 被管理项目的根目录：穿刺阶段就是 workflow.py 所在目录
# 后面支持多项目管理时，可以改成从参数或环境变量传入
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# .workflow_loop 目录路径
WORKFLOW_LOOP_DIR = os.path.join(PROJECT_ROOT, ".workflow_loop")


# ── 工具函数 ────────────────────────────────────────────

def print_next_step(instruction: str) -> None:
    """打印 stdout 末尾的"下一步"指令。
    格式：分隔线 + 下一步：xxx
    这是 stdout 驱动原则的核心——每条命令结束前都调这个。"""
    # 打印分隔线 + 下一步指令
    print(f"\n{NEXT_STEP_SEPARATOR}\n下一步：{instruction}")


def load_doc_content(rel_path: str | None) -> str:
    """加载 .workflow_loop/ 下的 .md 文档内容。
    如果路径为 None 或文件不存在，返回占位文本。
    用于 discuss 命令加载提示词、规范词等。"""
    # 路径为 None → 返回占位
    if rel_path is None:
        return "（无文档配置）"
    # 拼完整路径
    full_path = os.path.join(WORKFLOW_LOOP_DIR, rel_path)
    # 文件不存在 → 返回占位（穿刺阶段文档都是空的）
    if not os.path.exists(full_path):
        return f"（文档 {rel_path} 不存在，请创建后重试）"
    # 读文件内容
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def get_stage_strategy(stage_name: str, stages: list) -> StageStrategy | None:
    """根据 stage 名从 scenario 的 stages 列表里找对应的 StageStrategy 实例。
    返回找到的实例，或 None（stage 名不在列表里）。"""
    # 遍历 stages 列表，找 name 匹配的
    for stage in stages:
        if stage.name() == stage_name:
            return stage
    # 没找到
    return None


def get_scenario_stages(state: state_mod.WorkflowState) -> list:
    """从 state 里记录的 scenario 名，实例化对应 ScenarioStrategy，拿 stages 列表。
    用于 discuss/gate 命令找当前 stage 对应的 StageStrategy。"""
    # 从 SCENARIO_REGISTRY 查 scenario 类
    # state.scenario 存的是 "new_project" 格式，registry 的 key 是 "new-project" 格式
    # 需要把 state.scenario 的下划线转成横线
    scenario_key = state.scenario.replace("_", "-")
    scenario_cls = SCENARIO_REGISTRY.get(scenario_key)
    # 场景没注册 → 返回空列表
    if scenario_cls is None:
        return []
    # 实例化场景，拿 stages 列表
    scenario = scenario_cls()
    return scenario.stages()


# ── 命令 handler ─────────────────────────────────────────

def cmd_overview(args) -> None:
    """overview 命令：打印文档概览给 AI 和用户看。
    AI 读完理解项目文档全貌，后面每个 stage 都基于这个理解工作。"""
    # 从 role_doc 拿文档概览文本
    overview = role_doc_mod.get_overview()
    # 打印概览
    print(overview)
    # 写 journal
    journal_mod.append_entry(PROJECT_ROOT, "文档概览加载", "workflow.py")
    # 打印下一步
    print_next_step("调 `python3 workflow.py align` 对齐场景")


def cmd_align(args) -> None:
    """align 命令：加载场景对齐提示词，打印问题给 AI 拿去问用户。
    和 discuss 同构——都是"加载提示词 → 打印给 AI → AI 和用户交互"。"""
    # 加载场景对齐提示词
    prompt = load_doc_content("Template_Repository/align/align.md")
    # 打印提示词
    print("═══ 场景对齐 ═══\n")
    print(prompt)
    # 写 journal
    journal_mod.append_entry(PROJECT_ROOT, "场景对齐", "workflow.py")
    # 打印下一步：必须列出 entry 合法值 + 自然语言映射，让 AI 能把用户的回答翻译成 CLI 参数
    print_next_step(
        "拿这些问题问用户，根据用户回答调 `python3 workflow.py start --entry <entry>`\n"
        "  合法 entry 值（用户回答 → entry 参数）：\n"
        "    new-project          ← 用户说'新项目/空项目/从零开始'\n"
        "    existing-no-workflow ← 用户说'已有项目/有代码没接 workflow_loop'\n"
        "    bugfix              ← 用户说'修 bug/出问题了/复现问题'\n"
        "    product-mod          ← 用户说'改设计/加需求/改产品设计'"
    )


def cmd_start(args) -> None:
    """start 命令：初始化 state、加载 scenario、打印路线图。
    entry 参数来自用户在 align 阶段的回答。"""
    entry = args.entry  # 用户传入的 entry（如 new-project）
    # 查 SCENARIO_REGISTRY 找对应场景类
    scenario_cls = SCENARIO_REGISTRY.get(entry)
    # 场景没注册 → 报错
    if scenario_cls is None:
        print(f"错误：未知 entry '{entry}'，可选值：{list(SCENARIO_REGISTRY.keys())}")
        sys.exit(1)
    # 实例化场景
    scenario = scenario_cls()
    # 拿 stages 列表
    stages = scenario.stages()
    # stages 为空 → 场景还没实现（B/C/D stub）
    if not stages:
        print(f"错误：场景 '{entry}' 还没实现，stages() 返回空。穿刺只支持 new-project。")
        sys.exit(1)
    # 生成 workflow_id：YYYY-MM-DD-HHmm-<entry>
    now = state_mod.now_iso()
    # 从 ISO 时间戳提取日期+时间部分作为 id
    # ISO 格式 "2026-07-16T14:38:00+00:00" → "2026-07-16-1438"
    date_part = now[:10]  # "2026-07-16"
    time_part = now[11:16]  # "1438"
    workflow_id = f"{date_part}-{time_part}-{entry.replace('-', '_')}"
    # 初始化每个 stage 的状态
    stages_state = {}
    for stage in stages:
        stages_state[stage.name()] = state_mod.StageState(
            status="pending",  # 初始都是 pending
            artifact_paths=stage.artifact_paths(),  # 从策略拿期望产出路径
            artifact_produced_at=None,
            gate=state_mod.GateState(),  # 3 道闸都 False
        )
    # 第一个 stage 标记为 in_progress
    first_stage_name = stages[0].name()
    stages_state[first_stage_name].status = "in_progress"
    # 组装 WorkflowState
    wf_state = state_mod.WorkflowState(
        workflow_id=workflow_id,
        entry=entry.replace("-", "_"),  # state 里用下划线格式
        scenario=entry.replace("-", "_"),
        current_stage=first_stage_name,
        started_at=now,
        completed_at=None,
        topic=None,
        stages=stages_state,
        meta={},
    )
    # 保存 state
    state_mod.save_state(PROJECT_ROOT, wf_state)
    # 写 journal
    journal_mod.append_entry(PROJECT_ROOT, "工作流启动", "ai",
                            workflow_id=workflow_id, entry=wf_state.entry)
    journal_mod.append_entry(PROJECT_ROOT, "场景进入", "workflow.py",
                             scenario=wf_state.scenario)
    # 打印路线图
    print(f"═══ 工作流启动 ═══")
    print(f"workflow_id: {workflow_id}")
    print(f"场景: {scenario.name()}")
    print(f"路线图: {scenario.entry_instruction()}")
    print(f"当前阶段: {first_stage_name}")
    # 打印下一步
    print_next_step("调 `python3 workflow.py discuss` 加载第一个 stage 提示词")


def cmd_discuss(args) -> None:
    """discuss 命令：加载当前 stage 的提示词+规范+角色定义，打印给 AI。
    AI 用提示词里的问题/结构和用户讨论。"""
    # 读 state
    wf_state = state_mod.load_state(PROJECT_ROOT)
    # state 不存在 → 还没 start
    if wf_state is None:
        print("错误：还没启动工作流，请先调 `python3 workflow.py start --entry <entry>`")
        sys.exit(1)
    # 工作流已完成
    if wf_state.current_stage == "completed":
        print("错误：工作流已完成，无法再 discuss")
        sys.exit(1)
    # 从 scenario 拿 stages 列表
    stages = get_scenario_stages(wf_state)
    # 找当前 stage 对应的 StageStrategy
    stage = get_stage_strategy(wf_state.current_stage, stages)
    # stage 没找到
    if stage is None:
        print(f"错误：找不到 stage '{wf_state.current_stage}' 的策略实现")
        sys.exit(1)
    # 加载提示词
    prompt_content = load_doc_content(stage.prompt_doc_path())
    # 加载规范词
    standard_content = load_doc_content(stage.standard_doc_path())
    # 加载角色定义
    role_doc = role_doc_mod.get_role_doc(stage.name())
    # 打印
    print(f"═══ {stage.name()} stage ═══")
    print(f"\n【角色定义】")
    if role_doc:
        print(f"角色: {role_doc['role']}")
        print(f"描述: {role_doc['description']}")
    else:
        print("（无角色定义）")
    print(f"\n【提示词】")
    print(prompt_content)
    print(f"\n【规范词】")
    print(standard_content)
    print(f"\n【指令】")
    print(stage.instruction())
    print(f"\n【期望产出】")
    print(f"文件: {stage.artifact_paths()}")
    # 写 journal
    journal_mod.append_entry(PROJECT_ROOT, "提示词加载", "workflow.py",
                            stage=stage.name(), prompt_doc=stage.prompt_doc_path(),
                            standard_doc=stage.standard_doc_path())
    journal_mod.append_entry(PROJECT_ROOT, "角色文档加载", "workflow.py",
                            stage=stage.name())
    # 打印下一步
    print_next_step(
        f"用这个提示词和用户讨论。讨论完用户说'完毕'后，"
        f"调 `python3 workflow.py gate {stage.name()} --discuss-done`"
    )


def cmd_gate(args) -> None:
    """gate 命令：3 道闸的总入口，根据 flag 分发到不同处理。
    --discuss-done：第 1 道闸（讨论完毕）
    无 flag：第 2 道闸（代码校验）
    --confirmed：第 3 道闸（用户确认 + 推进）"""
    stage_name = args.stage  # 要过门禁的 stage 名
    # 读 state
    wf_state = state_mod.load_state(PROJECT_ROOT)
    # state 不存在
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # stage 不在 state 里
    if stage_name not in wf_state.stages:
        print(f"错误：stage '{stage_name}' 不在当前工作流的 stages 里")
        sys.exit(1)
    # 拿 stage 的 gate 状态
    stage_state = wf_state.stages[stage_name]
    gate = stage_state.gate

    # ── 第 1 道闸：--discuss-done ──
    if args.discuss_done:
        # 前置检查：必须先 discuss（journal 里有提示词加载记录）
        # 穿刺简化：只检查 discussion_complete 还没 True
        if gate.discussion_complete:
            print(f"提示：{stage_name} 的讨论已经标记完毕了")
        else:
            # 标记讨论完毕
            gate.discussion_complete = True
            # 保存 state
            state_mod.save_state(PROJECT_ROOT, wf_state)
            # 写 journal
            journal_mod.append_entry(PROJECT_ROOT, "门禁讨论完毕", "user",
                                    stage=stage_name, passed=True)
        # 打印
        print(f"═══ {stage_name} 讨论完毕 ═══")
        print(f"可以写产出文件了")
        # 打印下一步
        print_next_step(
            f"写产出文件 {stage_state.artifact_paths}。"
            f"写完调 `python3 workflow.py gate {stage_name}`"
        )

    # ── 第 2 道闸：无 flag（代码校验）──
    elif not args.confirmed:
        # 前置检查：discussion_complete 必须为 True
        if not gate.discussion_complete:
            print(f"错误：{stage_name} 还没标记讨论完毕，请先调 "
                  f"`python3 workflow.py gate {stage_name} --discuss-done`")
            sys.exit(1)
        # 从 scenario 拿 stages 列表
        stages = get_scenario_stages(wf_state)
        # 找 StageStrategy
        stage = get_stage_strategy(stage_name, stages)
        if stage is None:
            print(f"错误：找不到 stage '{stage_name}' 的策略实现")
            sys.exit(1)
        # 跑 code_validate
        passed, details = stage.code_validate(PROJECT_ROOT)
        # 写 journal
        journal_mod.append_entry(PROJECT_ROOT, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=passed, details=details)
        # 检查产出文件是否存在（写 journal: 产出文件检查）
        for artifact in stage_state.artifact_paths:
            full_path = os.path.join(PROJECT_ROOT, artifact)
            exists = os.path.exists(full_path)
            journal_mod.append_entry(PROJECT_ROOT, "产出文件检查", "workflow.py",
                                    stage=stage_name, artifact=artifact, exists=exists)
        # 不通过
        if not passed:
            print(f"═══ {stage_name} 代码校验失败 ═══")
            print(f"详情: {details}")
            print_next_step(f"产出文件未就绪，补完后再调 `python3 workflow.py gate {stage_name}`")
            return
        # 通过
        gate.code_validated = True
        # 标记产出时间
        if stage_state.artifact_produced_at is None:
            stage_state.artifact_produced_at = state_mod.now_iso()
        # 保存 state
        state_mod.save_state(PROJECT_ROOT, wf_state)
        # 写 journal
        journal_mod.append_entry(PROJECT_ROOT, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=True, details=details)
        # 打印
        print(f"═══ {stage_name} 代码校验通过 ═══")
        print(f"详情: {details}")
        # 打印下一步
        print_next_step(
            f"问用户'{stage_name} 写完了？'，用户确认后调 "
            f"`python3 workflow.py gate {stage_name} --confirmed`"
        )

    # ── 第 3 道闸：--confirmed（用户确认 + 推进）──
    else:
        # 前置检查：code_validated 必须为 True
        if not gate.code_validated:
            print(f"错误：{stage_name} 还没跑代码校验，请先调 "
                  f"`python3 workflow.py gate {stage_name}`")
            sys.exit(1)
        # 标记用户确认
        gate.user_confirmed = True
        # stage 状态改为 done
        stage_state.status = "done"
        # 从 scenario 拿 stages 列表
        stages = get_scenario_stages(wf_state)
        # 找 StageStrategy
        stage = get_stage_strategy(stage_name, stages)
        # 调 on_advance 钩子（spike stage 清理 throwaway 代码）
        if stage is not None:
            stage.on_advance(PROJECT_ROOT)
        # 写 journal
        journal_mod.append_entry(PROJECT_ROOT, "门禁用户确认", "user",
                                stage=stage_name, passed=True)
        # 找下一个 stage
        stage_names = list(wf_state.stages.keys())
        current_idx = stage_names.index(stage_name)
        # 有下一个 stage
        if current_idx + 1 < len(stage_names):
            next_stage = stage_names[current_idx + 1]
            wf_state.current_stage = next_stage
            # 下一个 stage 状态改 in_progress
            wf_state.stages[next_stage].status = "in_progress"
            # 保存 state
            state_mod.save_state(PROJECT_ROOT, wf_state)
            # 写 journal
            journal_mod.append_entry(PROJECT_ROOT, "阶段推进", "workflow.py",
                                    from_=stage_name, to=next_stage)
            # 打印
            print(f"═══ {stage_name} 完成 ═══")
            print(f"进入 {next_stage}")
            # 打印下一步
            print_next_step(f"调 `python3 workflow.py discuss` 加载 {next_stage} stage 提示词")
        # 没有下一个 stage → 这是最后一个 stage
        else:
            wf_state.current_stage = "completed"
            # 保存 state（completed_at 在 done 命令里写）
            state_mod.save_state(PROJECT_ROOT, wf_state)
            # 写 journal
            journal_mod.append_entry(PROJECT_ROOT, "阶段推进", "workflow.py",
                                    from_=stage_name, to="completed")
            # 打印
            print(f"═══ {stage_name} 完成 ═══")
            print(f"所有 stage 已完成")
            # 打印下一步
            print_next_step("调 `python3 workflow.py done` 标记完成")


def cmd_status(args) -> None:
    """status 命令：打印 state + journal 摘要。纯只读，无副作用。"""
    # 读 state
    wf_state = state_mod.load_state(PROJECT_ROOT)
    # state 不存在
    if wf_state is None:
        print("还没启动工作流。调 `python3 workflow.py overview` 开始。")
        return
    # 打印 state 摘要
    print(f"═══ 工作流状态 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"场景: {wf_state.scenario}")
    print(f"当前阶段: {wf_state.current_stage}")
    print(f"主题: {wf_state.topic or '（未定）'}")
    print(f"启动时间: {wf_state.started_at}")
    print(f"完成时间: {wf_state.completed_at or '（未完成）'}")
    # 打印每个 stage 的 gate 状态
    print(f"\n各阶段门禁状态：")
    for name, stage_state in wf_state.stages.items():
        gate = stage_state.gate
        # 3 道闸的状态用 ✓/✗ 显示
        d = "✓" if gate.discussion_complete else "✗"
        c = "✓" if gate.code_validated else "✗"
        u = "✓" if gate.user_confirmed else "✗"
        # stage 状态标记
        marker = "→" if name == wf_state.current_stage else " "
        print(f"  {marker} {name:12s} [{stage_state.status:12s}] 讨论完毕:{d} 代码校验:{c} 用户确认:{u}")
    # 打印 journal 最近 10 条
    print(f"\n最近 journal 记录：")
    recent = journal_mod.read_recent(PROJECT_ROOT, count=10)
    for entry in recent:
        # 每条显示时间 + action + actor
        print(f"  [{entry.get('ts', '')}] {entry.get('action', '')} ({entry.get('actor', '')})")
    # status 是纯只读命令，不打印"下一步"
    # 但打印一个友好提示
    print(f"\n（status 是只读命令，不改变状态。按之前命令打印的'下一步'继续。）")


def cmd_done(args) -> None:
    """done 命令：标记 completed + bug 册沉淀（若 bugfix）。
    在最后一个 stage 的 gate --confirmed 之后调用。"""
    # 读 state
    wf_state = state_mod.load_state(PROJECT_ROOT)
    # state 不存在
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # 前置检查：current_stage 必须是 completed
    if wf_state.current_stage != "completed":
        print(f"错误：还有未完成的 stage（当前: {wf_state.current_stage}），"
              f"请先完成所有 stage 的 gate --confirmed")
        sys.exit(1)
    # 标记完成时间
    wf_state.completed_at = state_mod.now_iso()
    # 保存 state
    state_mod.save_state(PROJECT_ROOT, wf_state)
    # 写 journal
    journal_mod.append_entry(PROJECT_ROOT, "工作流完成", "workflow.py",
                            workflow_id=wf_state.workflow_id)
    # 打印
    print(f"═══ 工作流完成 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"完成时间: {wf_state.completed_at}")
    # 打印下一步（实际是终态）
    print_next_step("工作流完成。本次 workflow 结束。")


# ── CLI 入口 ────────────────────────────────────────────

def main() -> None:
    """CLI 入口：解析参数、分发到对应 handler。
    每条命令 handler 干完事 + 打印 stdout + 打印"下一步"。"""
    # 创建 argparse 解析器
    parser = argparse.ArgumentParser(
        description="workflow_loop 工作流管理 CLI",
        prog="python3 workflow.py",
    )
    # 子命令（positional argument）
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # overview 命令：无参数
    subparsers.add_parser("overview", help="打印文档概览")

    # align 命令：无参数
    subparsers.add_parser("align", help="加载场景对齐提示词")

    # start 命令：需要 --entry 参数
    start_parser = subparsers.add_parser("start", help="启动工作流")
    start_parser.add_argument("--entry", required=True,
                             choices=list(SCENARIO_REGISTRY.keys()),
                             help="入口场景名")

    # discuss 命令：无参数（读 state.current_stage）
    subparsers.add_parser("discuss", help="加载当前 stage 提示词")

    # gate 命令：需要 stage 名 + 可选 flag
    gate_parser = subparsers.add_parser("gate", help="过门禁")
    gate_parser.add_argument("stage", help="stage 名")
    gate_parser.add_argument("--discuss-done", action="store_true",
                             help="标记讨论完毕（第 1 道闸）")
    gate_parser.add_argument("--confirmed", action="store_true",
                             help="用户确认 + 推进（第 3 道闸）")

    # status 命令：无参数
    subparsers.add_parser("status", help="打印状态摘要")

    # done 命令：无参数
    subparsers.add_parser("done", help="标记完成")

    # 解析参数
    args = parser.parse_args()

    # 没传命令 → 打印 help
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # 分发到对应 handler
    if args.command == "overview":
        cmd_overview(args)
    elif args.command == "align":
        cmd_align(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "discuss":
        cmd_discuss(args)
    elif args.command == "gate":
        cmd_gate(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "done":
        cmd_done(args)
    else:
        # 未知命令（argparse 应该已经拦了，这是兜底）
        print(f"未知命令: {args.command}")
        parser.print_help()
        sys.exit(1)


# 脚本直接运行时调 main
if __name__ == "__main__":
    main()
