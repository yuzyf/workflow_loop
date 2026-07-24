import argparse
import os
import shutil
import sys

from . import state as state_mod
from . import journal as journal_mod
from . import role_doc as role_doc_mod
from . import project as project_mod
from . import verification as verification_mod
from . import installer as installer_mod
from . import topic as topic_mod
from .path_composer import build_stage_path, INTENT_CHOICES
from .stages import ProjectDesignInitStage
from .stages.base import StageStrategy, clean_spike_tmp

# stdout 分隔线，用于分隔"命令输出"和"下一步指令"
NEXT_STEP_SEPARATOR = "─" * 42
# .workflow_loop 目录名
WORKFLOW_LOOP_DIRNAME = ".workflow_loop"
# 所有 stage 共用的写作规范路径（相对 .workflow_loop/）
GLOBAL_WRITING_STANDARD_PATH = "Standardized_Repository/global/document_writing.md"
# from_scratch 清场时探测的过程产物目录列表（Clean Detect List）
# 这些目录下有文件时需要 --confirm-clean 才能删除
CLEAN_DETECT_DIRS = ["spec", "plan", "acceptance", "qa", "impl", "bug"]


# 打印 stdout 末尾的"下一步"指令（stdout 驱动原则的核心）
# 每条命令结束前都调这个，AI 读 stdout 知道下一步干啥
def print_next_step(instruction: str) -> None:
    # 分隔线 + 下一步指令
    print(f"\n{NEXT_STEP_SEPARATOR}\n下一步：{instruction}")


# 根据当前阶段的门禁状态，给出不会跨阶段的下一步
def current_stage_next_instruction(wf_state) -> str:
    stage_name = wf_state.current_stage
    if stage_name == "completed":
        return "调 `workflow done` 标记本次工作流完成"

    stage_state = wf_state.stages.get(stage_name)
    if stage_state is None:
        return "调 `workflow status` 查看当前工作流状态"

    gate = stage_state.gate
    if not gate.discussion_complete:
        return (
            f"调 `workflow discuss` 加载当前 {stage_name} stage 提示词；"
            f"讨论完成后调 `workflow gate {stage_name} --discuss-done`"
        )
    if not gate.code_validated:
        return (
            f"完成当前 {stage_name} stage 的产出文件后，"
            f"调 `workflow gate {stage_name}` 执行校验"
        )
    if not gate.user_confirmed:
        return (
            f"用户确认当前 {stage_name} stage 的产出后，"
            f"调 `workflow gate {stage_name} --confirmed`"
        )
    return "调 `workflow status` 查看当前工作流状态"


# 从当前工作目录向上查找 .workflow_loop/ 目录，定位项目根
# 日常命令（start/discuss/gate 等）用这个找项目根
# 安装命令（install-project）不用这个，直接用 cwd
def resolve_project_root() -> str | None:
    # 从当前目录开始
    current = os.getcwd()
    # 一直向上找
    while True:
        # 找到 .workflow_loop/ → 返回当前目录作为项目根
        if os.path.exists(os.path.join(current, WORKFLOW_LOOP_DIRNAME)):
            return current
        # 取父目录
        parent = os.path.dirname(current)
        # 到根目录了还没找到 → 返回 None
        if parent == current:
            return None
        # 继续向上
        current = parent


# 加载 .workflow_loop/ 下的 .md 文档内容（discuss 命令用）
# 路径为 None → 返回占位文本；文件不存在 → 返回错误提示
def load_doc_content(project_root: str, rel_path: str | None) -> str:
    # 路径为 None → 该 stage 没有配置文档
    if rel_path is None:
        return "（无文档配置）"
    # 拼完整路径（项目根 + .workflow_loop/ + 相对路径）
    full_path = os.path.join(project_root, WORKFLOW_LOOP_DIRNAME, rel_path)
    # 文件不存在 → 返回错误提示
    if not os.path.exists(full_path):
        return f"（文档 {rel_path} 不存在，请创建后重试）"
    # 读文件内容
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


# 记录进入穿刺阶段时的产品设计和代码设计内容哈希
# 新流程只在真正进入 spike 时记录；旧 state.json 已经停在 spike 且没有基线时，明确标记无法还原
# 旧状态里的穿刺产物路径也在这里迁移为新的固定清单路径
def ensure_spike_baseline(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    *,
    capture_if_missing: bool = False,
) -> bool:
    changed = False
    spike_state = wf_state.stages.get("spike")
    expected_artifact_paths = ["spec/spike_index.md"]
    if spike_state is not None and spike_state.artifact_paths != expected_artifact_paths:
        spike_state.artifact_paths = expected_artifact_paths
        changed = True
        journal_mod.append_entry(
            project_root,
            "穿刺状态迁移",
            "workflow.py",
            artifact_paths=expected_artifact_paths,
        )

    if wf_state.spike_baseline.captured_at is not None:
        return changed

    if not capture_if_missing:
        if not wf_state.spike_baseline.legacy_unavailable:
            wf_state.spike_baseline.legacy_unavailable = True
            journal_mod.append_entry(
                project_root,
                "穿刺基线缺失",
                "workflow.py",
                reason="旧工作流没有保存进入 spike 时的设计哈希，不能用当前文件冒充旧基线",
            )
            changed = True
        return changed

    product_hash, product_paths = verification_mod.compute_product_design_hash(project_root)
    wf_state.spike_baseline = state_mod.SpikeBaselineState(
        captured_at=state_mod.now_iso(),
        product_design_hash=product_hash,
        product_design_paths=product_paths,
        code_design_hash=verification_mod.compute_code_design_hash(project_root),
        legacy_unavailable=False,
    )
    journal_mod.append_entry(
        project_root,
        "穿刺设计基线",
        "workflow.py",
        product_design_hash=product_hash,
        product_design_paths=product_paths,
        code_design_hash=wf_state.spike_baseline.code_design_hash,
    )
    return True


def ensure_stage_artifact_baseline(
    project_root: str,
    wf_state: state_mod.WorkflowState,
    stage: StageStrategy,
) -> bool:
    """在开始写产物前保存文件哈希；同一阶段只记录一次。"""
    stage_state = wf_state.stages.get(stage.name())
    if stage_state is None or stage_state.artifact_baseline_captured_at is not None:
        return False

    tracked_paths = stage.change_tracked_paths(project_root)
    if not tracked_paths:
        return False

    stage_state.artifact_baseline_captured_at = state_mod.now_iso()
    stage_state.artifact_baseline_hashes = verification_mod.compute_file_hashes(
        project_root,
        tracked_paths,
    )
    journal_mod.append_entry(
        project_root,
        "阶段产物基线",
        "workflow.py",
        stage=stage.name(),
        artifact_hashes=stage_state.artifact_baseline_hashes,
    )
    return True


def ensure_stage_path_current(project_root: str, wf_state: state_mod.WorkflowState) -> bool:
    """把旧工作流状态迁移到当前阶段顺序，并保留已经完成的前置阶段。"""
    stage_instances = build_stage_path(wf_state.intent, project_root)

    # project_design_init（项目设计初始化）只在开工时决定是否加入路径。
    # 旧 Run 已经包含它时，即使项目标记后来变为 true，也要保留这段历史。
    if "project_design_init" in wf_state.stage_path and not any(
        stage.name() == "project_design_init" for stage in stage_instances
    ):
        stage_instances.insert(0, ProjectDesignInitStage())

    expected_names = [stage.name() for stage in stage_instances]
    if wf_state.stage_path == expected_names:
        return False

    old_names = wf_state.stage_path
    old_stages = wf_state.stages
    new_stages = {}
    for stage in stage_instances:
        stage_name = stage.name()
        if stage_name in old_stages:
            stage_state = old_stages[stage_name]
            stage_state.artifact_paths = stage.artifact_paths()
        else:
            stage_state = state_mod.StageState(
                status="pending",
                artifact_paths=stage.artifact_paths(),
                artifact_produced_at=None,
                gate=state_mod.GateState(),
            )
        new_stages[stage_name] = stage_state

    # 旧顺序先做 plan/fix_plan。新顺序要求先验收计划、再测试计划、最后实施计划。
    implementation_plan_name = "fix_plan" if wf_state.intent == "bugfix" else "plan"
    if (
        implementation_plan_name in old_names
        and "acceptance_plan" in old_names
        and old_names.index(implementation_plan_name) < old_names.index("acceptance_plan")
        and (
            new_stages["acceptance_plan"].status != "done"
            or new_stages["test_plan"].status != "done"
        )
    ):
        new_stages[implementation_plan_name] = state_mod.StageState(
            status="pending",
            artifact_paths=new_stages[implementation_plan_name].artifact_paths,
        )

    # 新增最终全量回归与整体验收后，旧版提前完成的详细架构不能继续算完成。
    if "regression_test" not in old_names or "overall_acceptance" not in old_names:
        update_state = new_stages.get("update_code_design")
        if update_state is not None and update_state.status == "done":
            new_stages["update_code_design"] = state_mod.StageState(
                status="pending",
                artifact_paths=update_state.artifact_paths,
            )
            wf_state.architecture.detailed_done = False

    current_stage = "completed"
    for stage_name in expected_names:
        if new_stages[stage_name].status != "done":
            current_stage = stage_name
            break

    for stage_name, stage_state in new_stages.items():
        if stage_state.status != "done":
            stage_state.status = "in_progress" if stage_name == current_stage else "pending"

    previous_path = wf_state.stage_path
    previous_stage = wf_state.current_stage
    wf_state.stage_path = expected_names
    wf_state.stages = new_stages
    wf_state.current_stage = current_stage
    journal_mod.append_entry(
        project_root,
        "阶段路径迁移",
        "workflow.py",
        previous_path=previous_path,
        current_path=expected_names,
        previous_stage=previous_stage,
        current_stage=current_stage,
    )
    return True


# 从 stage 实例列表里找对应 stage 名的策略实例
# discuss 和 gate 命令用这个找当前 stage 的策略
def get_stage_strategy(stage_name: str, state: state_mod.WorkflowState, stage_instances: list[StageStrategy]) -> StageStrategy | None:
    # 遍历 stage 实例列表
    for stage in stage_instances:
        # 名字匹配 → 返回该实例
        if stage.name() == stage_name:
            return stage
    # 没找到
    return None


# 探测项目根下是否有过程产物（from_scratch 清场用）
# 检查 CLEAN_DETECT_DIRS 里的目录是否存在且含文件
# 不监测 .workflow_loop/Template_Repository/ 和 Standardized_Repository/
def detect_clean_artifacts(project_root: str) -> list[str]:
    # 收集有内容的产物目录
    found = []
    # 遍历清场监测清单
    for dir_name in CLEAN_DETECT_DIRS:
        # 拼出目录路径
        dir_path = os.path.join(project_root, dir_name)
        # 目录存在
        if os.path.isdir(dir_path):
            # 检查目录下是否有任何文件（递归遍历）
            has_files = any(
                os.path.isfile(os.path.join(root, f))
                for root, dirs, files in os.walk(dir_path)
                for f in files
            )
            # 有文件 → 加入待删清单
            if has_files:
                found.append(dir_name)
    # 返回有内容的目录列表
    return found


# 删除项目根下的过程产物（from_scratch --confirm-clean 时调用）
# 删除 CLEAN_DETECT_DIRS 里有文件的目录
def clean_artifacts(project_root: str) -> list[str]:
    # 收集已清理的目录
    cleaned = []
    # 遍历清场监测清单
    for dir_name in CLEAN_DETECT_DIRS:
        # 拼出目录路径
        dir_path = os.path.join(project_root, dir_name)
        # 目录存在
        if os.path.isdir(dir_path):
            # 检查是否有文件
            has_files = any(
                os.path.isfile(os.path.join(root, f))
                for root, dirs, files in os.walk(dir_path)
                for f in files
            )
            # 有文件 → 删除整个目录
            if has_files:
                shutil.rmtree(dir_path)
                cleaned.append(dir_name)
    # 返回已清理的目录列表
    return cleaned


# start 命令：启动工作流或检查状态
# 不带 --intent → 只读状态检查，不初始化 Run
# 带 --intent → 初始化 Run（from_scratch 另循 Clean Confirm）
def cmd_start(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    # 找不到 .workflow_loop/ → 项目未安装
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 检查项目是否已安装（project.json 存在且 installer_version 匹配）
    if not project_mod.is_installed(project_root):
        print("错误：项目未安装。请先在项目根执行官方安装脚本。")
        sys.exit(1)

    # 不带 --intent → 只读状态检查
    if args.intent is None:
        # 读已有 state
        existing = state_mod.load_state(project_root)
        # 有进行中 Run → 提示继续原流程，禁止开新 Run
        if existing is not None and existing.run_status == "active":
            if ensure_stage_path_current(project_root, existing):
                state_mod.save_state(project_root, existing)
            print(f"有进行中 Run（workflow_id: {existing.workflow_id}）")
            print(f"当前 stage: {existing.current_stage}")
            print(f"intent: {existing.intent}")
            print_next_step("调 `workflow status` 查看详情，或先 `workflow done`/`workflow abort` 结束当前 Run")
            return
        # 无进行中 Run → 列出三种意图
        print("无可进行中 Run。可选工作意图：")
        for intent in INTENT_CHOICES:
            print(f"  {intent}")
        print_next_step("根据用户提问确定意图，调 `workflow start --intent from_scratch|product_change|bugfix`")
        return

    # 带 --intent → 初始化 Run
    intent = args.intent

    # Active Run Guard：有进行中 Run → 禁止再 start
    if state_mod.is_active_run(project_root):
        print("错误：有进行中 Run。请先 `workflow done` 或 `workflow abort` 结束当前 Run。")
        sys.exit(1)

    # from_scratch 的 Clean Confirm 两段式
    if intent == "from_scratch":
        # 探测过程产物
        artifacts = detect_clean_artifacts(project_root)
        # 有产物且无 --confirm-clean → 只打印将删清单，不删、不开 Run
        if artifacts and not args.confirm_clean:
            print("检测到以下过程产物目录包含文件；确认后会删除整个目录及其中全部内容：")
            for d in artifacts:
                print(f"  {d}/")
            print("从零做不会保留这些目录中的其他文件。")
            print_next_step("用户确认清场后，调 `workflow start --intent from_scratch --confirm-clean`")
            return
        # 有产物且有 --confirm-clean → 删除产物后继续
        if artifacts and args.confirm_clean:
            cleaned = clean_artifacts(project_root)
            print(f"已清理: {cleaned}")
        # 无论是否发现并删除旧产物，都把 project_design_initialized 置为 false
        project_mod.set_project_design_initialized(project_root, False)

    # 生成 workflow_id：YYYY-MM-DD-HHmm-<intent>
    now = state_mod.now_iso()
    date_part = now[:10]
    # 去掉冒号避免文件名问题
    time_part = now[11:16].replace(":", "")
    workflow_id = f"{date_part}-{time_part}-{intent}"

    # 调 PathComposer 生成 stage 列表
    stages = build_stage_path(intent, project_root)
    # 提取 stage 名列表存入 state.stage_path
    stage_path = [s.name() for s in stages]

    # 初始化每个 stage 的状态
    stages_state = {}
    for stage in stages:
        stages_state[stage.name()] = state_mod.StageState(
            status="pending",
            artifact_paths=stage.artifact_paths(),
            artifact_produced_at=None,
            gate=state_mod.GateState(),
        )
    # 第一个 stage 标记为 in_progress
    first_stage_name = stages[0].name()
    stages_state[first_stage_name].status = "in_progress"

    # 组装 WorkflowState（全集 schema）
    wf_state = state_mod.WorkflowState(
        workflow_id=workflow_id,
        intent=intent,
        run_status="active",
        current_stage=first_stage_name,
        started_at=now,
        stage_path=stage_path,
        stages=stages_state,
        clean_confirmed=args.confirm_clean if intent == "from_scratch" else False,
    )

    # 保存 state.json
    state_mod.save_state(project_root, wf_state)

    # 写 journal：工作流启动
    journal_mod.append_entry(project_root, "工作流启动", "ai",
                            workflow_id=workflow_id, intent=intent)
    # 写 journal：路径生成
    journal_mod.append_entry(project_root, "路径生成", "workflow.py",
                            intent=intent, stage_path=stage_path)
    # 写 journal：清场确认（如果执行了清场）
    if intent == "from_scratch" and args.confirm_clean:
        journal_mod.append_entry(project_root, "清场确认", "workflow.py",
                                cleaned_paths=cleaned if 'cleaned' in dir() else [])

    # 打印路径向开工摘要（不倾倒文档百科）
    print(f"═══ 工作流启动 ═══")
    print(f"workflow_id: {workflow_id}")
    print(f"intent: {intent}")
    print(f"stage_path: {' → '.join(stage_path)}")
    print(f"当前 stage: {first_stage_name}")
    # product_change/bugfix 显示 project_design_initialized 状态
    if intent == "product_change" or intent == "bugfix":
        pdi = project_mod.is_project_design_initialized(project_root)
        print(f"project_design_initialized: {pdi}")

    # 下一步：discuss
    print_next_step("调 `workflow discuss` 加载第一个 stage 提示词")


# discuss 命令：加载全局写作规范 + 当前 stage 的提示词/规范/角色定义，完整输出给 AI
# Prompt Full Print：提示词/规范的消费者是 AI，必须在 stdout 给出完整正文
def cmd_discuss(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()

    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    # state 不存在 → 还没 start
    if wf_state is None:
        print("错误：还没启动工作流。调 `workflow start --intent <意图>` 开始。")
        sys.exit(1)
    # Run 已结束 → 不能 discuss
    if wf_state.run_status != "active":
        print(f"错误：Run 已 {wf_state.run_status}，无法 discuss。")
        sys.exit(1)
    if ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)
    # 工作流已完成
    if wf_state.current_stage == "completed":
        print("错误：工作流已完成。")
        sys.exit(1)

    # 兼容旧状态：已经进入 spike 但没有入场基线时，在加载提示词前标记无法还原
    if wf_state.current_stage == "spike" and ensure_spike_baseline(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 从 PathComposer 重建 stage 实例列表
    stage_instances = build_stage_path(wf_state.intent, project_root)
    # 找当前 stage 的策略
    stage = get_stage_strategy(wf_state.current_stage, wf_state, stage_instances)
    if stage is None:
        print(f"错误：找不到 stage '{wf_state.current_stage}' 的策略实现")
        sys.exit(1)

    # 加载全局写作规范（所有 stage 共用）
    global_writing_content = load_doc_content(project_root, GLOBAL_WRITING_STANDARD_PATH)
    # 加载模版提示词（Prompt Full Print：完整正文）
    print("当前路径：", stage.prompt_doc_path())
    prompt_content = load_doc_content(project_root, stage.prompt_doc_path())
    # 加载规范词（完整正文）
    standard_content = load_doc_content(project_root, stage.standard_doc_path())
    # 加载角色定义
    role_doc = role_doc_mod.get_role_doc(stage.name())

    # 打印 stage 头
    print(f"═══ {stage.name()} stage ═══")
    # 打印角色定义
    print(f"\n【角色定义】")
    if role_doc:
        print(f"角色: {role_doc['role']}")
        print(f"描述: {role_doc['description']}")
    else:
        print("（无角色定义）")
    # 打印全局写作规范全文
    print(f"\n【全局写作规范】")
    print(global_writing_content)
    # 打印提示词全文
    print(f"\n【流程模版】")
    print(prompt_content)
    # 打印规范词全文
    print(f"\n【流程规范】")
    print(standard_content)

    # 打印附加提示词/规范（project_design_init 加载 spec + code_design 两组）
    for extra_prompt_path, extra_standard_path in stage.additional_doc_paths():
        print(f"\n【附加流程模版: {extra_prompt_path}】")
        print(load_doc_content(project_root, extra_prompt_path))
        print(f"\n【附加流程规范: {extra_standard_path}】")
        print(load_doc_content(project_root, extra_standard_path))

    # 打印指令
    print(f"\n【指令】")
    print(stage.instruction())
    # 打印期望产出
    print(f"\n【期望产出】")
    print(f"文件: {stage.artifact_paths()}")

    # 写 journal：提示词加载
    journal_mod.append_entry(project_root, "提示词加载", "workflow.py",
                            stage=stage.name(), prompt_doc=stage.prompt_doc_path(),
                            standard_doc=stage.standard_doc_path(),
                            global_writing_standard=GLOBAL_WRITING_STANDARD_PATH)
    # 写 journal：角色文档加载
    journal_mod.append_entry(project_root, "角色文档加载", "workflow.py",
                            stage=stage.name())

    # 下一步：和用户讨论，讨论完毕调 gate --discuss-done
    print_next_step(
        f"用这个提示词和用户讨论。讨论完用户说'完毕'后，"
        f"调 `workflow gate {stage.name()} --discuss-done`"
    )


# gate 命令：3 道闸的总入口 + spike --skip
# --discuss-done：第 1 道闸（讨论完毕）
# 无 flag：第 2 道闸（代码校验 + Verification Invalidation 检查）
# --confirmed：第 3 道闸（用户确认 + 推进 + 记录 hash + 设置架构标记）
def cmd_gate(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # Run 已结束 → 不能 gate
    if wf_state.run_status != "active":
        print(f"错误：Run 已 {wf_state.run_status}，无法 gate。")
        sys.exit(1)
    if ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 要过门禁的 stage 名
    stage_name = args.stage

    # 所有门禁只能操作当前正在进行的 stage，不能跨阶段提前标记或推进
    if stage_name not in wf_state.stages:
        print(f"错误：stage '{stage_name}' 不在当前工作流的 stages 里")
        print_next_step(current_stage_next_instruction(wf_state))
        sys.exit(1)
    if stage_name != wf_state.current_stage:
        print(f"错误：当前 stage 是 {wf_state.current_stage}，不能操作 {stage_name} 的门禁")
        print_next_step(current_stage_next_instruction(wf_state))
        sys.exit(1)

    # ── 特殊：--skip（仅 spike）──
    if args.skip:
        # --skip 只适用于 spike stage
        if stage_name != "spike":
            print(f"错误：--skip 仅适用于 spike stage，不适用于 {stage_name}")
            sys.exit(1)
        # 标记 spike 跳过
        wf_state.spike_skipped = True
        # 绕过三道门（全设 True）
        wf_state.stages[stage_name].gate.discussion_complete = True
        wf_state.stages[stage_name].gate.code_validated = True
        wf_state.stages[stage_name].gate.user_confirmed = True
        wf_state.stages[stage_name].status = "done"
        # 找下一个 stage
        stage_names = list(wf_state.stages.keys())
        current_idx = stage_names.index(stage_name)
        # 有下一个 stage → 推进
        if current_idx + 1 < len(stage_names):
            next_stage = stage_names[current_idx + 1]
            wf_state.current_stage = next_stage
            wf_state.stages[next_stage].status = "in_progress"
        # 清理可能存在的临时内容
        cleaned_paths = clean_spike_tmp(project_root)
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：spike 跳过
        journal_mod.append_entry(project_root, "spike 跳过", "workflow.py",
                                cleaned_paths=cleaned_paths)
        # 写 journal：阶段推进
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to=wf_state.current_stage)
        # 打印跳过信息
        print(f"═══ {stage_name} 跳过 ═══")
        print(f"进入 {wf_state.current_stage}")
        print_next_step(f"调 `workflow discuss` 加载 {wf_state.current_stage} stage 提示词")
        return

    # 拿 stage 的 gate 状态
    stage_state = wf_state.stages[stage_name]
    gate = stage_state.gate

    # 找到当前阶段策略。第一道门需要它确定哪些文件要记录修改前基线。
    stage_instances = build_stage_path(wf_state.intent, project_root)
    stage = get_stage_strategy(stage_name, wf_state, stage_instances)
    if stage is None:
        print(f"错误：找不到 stage '{stage_name}' 的策略实现")
        sys.exit(1)

    # ── 第 1 道闸：--discuss-done ──
    if args.discuss_done:
        # 兼容旧状态：第一道门前处理产物路径迁移，并标记缺失的入场基线
        if stage_name == "spike" and ensure_spike_baseline(project_root, wf_state):
            state_mod.save_state(project_root, wf_state)
        # 已经标记过了 → 提示
        if gate.discussion_complete:
            print(f"提示：{stage_name} 的讨论已经标记完毕了")
        else:
            # 标记讨论完毕
            gate.discussion_complete = True
            # 写 journal：门禁讨论完毕
            journal_mod.append_entry(project_root, "门禁讨论完毕", "user",
                                    stage=stage_name, passed=True)
        # 讨论结束后、开始写文件前记录基线。重复调用不会覆盖原基线。
        ensure_stage_artifact_baseline(project_root, wf_state, stage)
        # 保存 gate 和基线
        state_mod.save_state(project_root, wf_state)
        # 打印讨论完毕
        print(f"═══ {stage_name} 讨论完毕 ═══")
        print(f"可以写产出文件了")
        # 下一步：写产出文件
        print_next_step(
            f"写产出文件 {stage_state.artifact_paths}。"
            f"写完调 `workflow gate {stage_name}`"
        )
        return

    # ── 第 2 道闸：无 flag（代码校验）──
    if not args.confirmed:
        # 前置检查：discussion_complete 必须为 True
        if not gate.discussion_complete:
            print(f"错误：{stage_name} 还没标记讨论完毕，请先调 "
                  f"`workflow gate {stage_name} --discuss-done`")
            sys.exit(1)

        # 穿刺门2比较设计文档前后变化；旧状态缺少基线时明确标记无法还原
        if stage_name == "spike" and ensure_spike_baseline(project_root, wf_state):
            state_mod.save_state(project_root, wf_state)

        # 兼容旧状态：讨论已经完成但没有记录基线时，从当前文件开始记录。
        # 这样旧文件不能直接通过，必须在记录后再次修改。
        if ensure_stage_artifact_baseline(project_root, wf_state, stage):
            state_mod.save_state(project_root, wf_state)

        # Verification Invalidation 检查：上游 hash 是否变化
        invalidations = verification_mod.check_invalidation(wf_state, project_root)
        # 有失效 → 清零下游，提示重新写产出
        if invalidations:
            # 保存清零后的 state
            state_mod.save_state(project_root, wf_state)
            # 写 journal：验证失效
            for from_stage, to_stages in invalidations:
                journal_mod.append_entry(project_root, "验证失效", "workflow.py",
                                        from_stage=from_stage, to_stage=to_stages,
                                        reason="上游内容已变化")
            # 打印失效信息
            print(f"═══ 验证失效 ═══")
            for from_stage, to_stages in invalidations:
                print(f"  {from_stage} 变化 → 清零 {to_stages}")
            print(f"请重新写产出后再过门禁")
            # 下一步：重新写产出
            print_next_step(current_stage_next_instruction(wf_state))
            return

        # 跑 code_validate（第 2 道闸的核心）
        passed, details = stage.code_validate(project_root)
        # 写 journal：门禁代码校验
        journal_mod.append_entry(project_root, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=passed, details=details)

        # 检查产出文件是否存在（写 journal：产出文件检查）
        for artifact in stage_state.artifact_paths:
            full_path = os.path.join(project_root, artifact)
            exists = os.path.exists(full_path)
            journal_mod.append_entry(project_root, "产出文件检查", "workflow.py",
                                    stage=stage_name, artifact=artifact, exists=exists)

        # 校验不通过
        if not passed:
            # 之前通过过门2，但产物后来被改坏时，旧的通过标记必须失效
            gate.code_validated = False
            gate.user_confirmed = False
            state_mod.save_state(project_root, wf_state)
            print(f"═══ {stage_name} 代码校验失败 ═══")
            print(f"详情: {details}")
            # 下一步：补完产出再校验
            print_next_step(f"产出文件未就绪，补完后再调 `workflow gate {stage_name}`")
            return

        # 校验通过
        gate.code_validated = True
        # 标记产出时间
        if stage_state.artifact_produced_at is None:
            stage_state.artifact_produced_at = state_mod.now_iso()
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：门禁代码校验通过
        journal_mod.append_entry(project_root, "门禁代码校验", "workflow.py",
                                stage=stage_name, passed=True, details=details)
        # 打印校验通过
        print(f"═══ {stage_name} 代码校验通过 ═══")
        print(f"详情: {details}")
        # 下一步：问用户确认
        print_next_step(
            f"问用户'{stage_name} 写完了？'，用户确认后调 "
            f"`workflow gate {stage_name} --confirmed`"
        )
        return

    # ── 第 3 道闸：--confirmed（用户确认 + 推进）──
    # 前置检查：code_validated 必须为 True
    if not gate.code_validated:
        print(f"错误：{stage_name} 还没跑代码校验，请先调 "
              f"`workflow gate {stage_name}`")
        sys.exit(1)

    # 门2通过后文件仍可能变化。门3推进前必须重新检查当前文件，不能只相信旧布尔值。
    invalidations = verification_mod.check_invalidation(wf_state, project_root)
    if invalidations:
        state_mod.save_state(project_root, wf_state)
        for from_stage, to_stages in invalidations:
            journal_mod.append_entry(
                project_root,
                "验证失效",
                "workflow.py",
                from_stage=from_stage,
                to_stage=to_stages,
                reason="用户确认前发现上游内容已变化",
            )
        print("═══ 用户确认前校验失败 ═══")
        for from_stage, to_stages in invalidations:
            print(f"  {from_stage} 变化 → 清零 {to_stages}")
        print_next_step(current_stage_next_instruction(wf_state))
        return

    passed, details = stage.code_validate(project_root)
    journal_mod.append_entry(
        project_root,
        "门禁确认前复核",
        "workflow.py",
        stage=stage_name,
        passed=passed,
        details=details,
    )
    if not passed:
        gate.code_validated = False
        gate.user_confirmed = False
        state_mod.save_state(project_root, wf_state)
        print(f"═══ {stage_name} 用户确认前校验失败 ═══")
        print(f"详情: {details}")
        print_next_step(f"修正文档后重新调 `workflow gate {stage_name}`")
        return

    # acceptance_plan（验收计划）确认时，从计划文件名确定本次全部主题并登记历史。
    if stage_name == "acceptance_plan":
        topics = topic_mod.candidate_topics(project_root)
        if not topics:
            print("错误：没有找到本次新增的验收主题")
            print_next_step("补充 acceptance/<topic>_plan.md 后重新执行验收计划门禁")
            return
        previous_topics = set(wf_state.topics or ([wf_state.topic] if wf_state.topic else []))
        new_topics = [topic for topic in topics if topic not in previous_topics]
        try:
            project_mod.register_topics(project_root, new_topics)
        except ValueError as exc:
            print(f"错误：{exc}")
            print_next_step("修改重复的主题名称后重新执行验收计划门禁")
            return
        wf_state.topics = topics
        wf_state.topic = topics[0] if len(topics) == 1 else None
        journal_mod.append_entry(
            project_root,
            "主题确定",
            "user",
            topics=topics,
        )

    # 标记用户确认
    gate.user_confirmed = True
    # stage 状态改为 done
    stage_state.status = "done"

    # 调 on_advance 钩子（spike 清理临时代码、样本和原始输出）
    cleaned_paths = stage.on_advance(project_root)
    if stage_name == "spike":
        journal_mod.append_entry(
            project_root,
            "spike 清理",
            "workflow.py",
            cleaned_paths=cleaned_paths,
        )

    # ── 记录 verification hash（验证绑定哈希）──
    # topic_execution（主题执行）完成后记录实施代码、实施记录和主题测试结果哈希。
    if stage_name in ("impl", "topic_execution"):
        wf_state.verification.impl_hash = verification_mod.compute_impl_hash(project_root, wf_state.topics)
        # 执行结果变化后，最终全量回归和整体验收必须重做。
        for sn in ["test", "acceptance", "regression_test", "overall_acceptance"]:
            if sn in wf_state.stages:
                verification_mod.clear_stage_gates(wf_state.stages[sn])
        if stage_name == "topic_execution":
            wf_state.verification.test_result_hash = verification_mod.compute_test_result_hash(
                project_root,
                wf_state.topics,
            )
    # test_plan stage → 记录 test_plan_hash
    elif stage_name == "test_plan":
        wf_state.verification.test_plan_hash = verification_mod.compute_test_plan_hash(project_root, wf_state.topics)
    # acceptance_plan stage → 记录 acceptance_plan_hash，退 test_plan 待检查
    elif stage_name == "acceptance_plan":
        wf_state.verification.acceptance_plan_hash = verification_mod.compute_acceptance_plan_hash(project_root, wf_state.topics)
        # acceptance_plan 变了 → test_plan 需要重新检查
        if "test_plan" in wf_state.stages:
            wf_state.stages["test_plan"].gate.code_validated = False
            wf_state.stages["test_plan"].gate.user_confirmed = False
            wf_state.stages["test_plan"].status = "pending"
    # test stage → 记录 test_result_hash
    elif stage_name == "test":
        wf_state.verification.test_result_hash = verification_mod.compute_test_result_hash(project_root, wf_state.topics)
    elif stage_name == "regression_test":
        wf_state.verification.regression_test_result_hash = (
            verification_mod.compute_regression_test_result_hash(project_root)
        )

    # ── 设置 Architecture Gate Marks ──
    # 前段架构 stage → preliminary_done
    if stage_name in ("code_design", "revise_code_design", "project_design_init"):
        wf_state.architecture.preliminary_done = True
        journal_mod.append_entry(project_root, "架构标记", "workflow.py",
                                mark="preliminary_done", stage=stage_name)
    # 末段架构 stage → detailed_done
    if stage_name == "update_code_design":
        wf_state.architecture.detailed_done = True
        journal_mod.append_entry(project_root, "架构标记", "workflow.py",
                                mark="detailed_done", stage=stage_name)

    # ── 设置 project_design_initialized ──
    # project_design_init 完成 → 置 true
    if stage_name == "project_design_init":
        project_mod.set_project_design_initialized(project_root, True)
    # from_scratch 的 code_design 完成 + spec 也完成 → 置 true
    elif stage_name == "code_design" and wf_state.intent == "from_scratch":
        if "spec" in wf_state.stages and wf_state.stages["spec"].gate.user_confirmed:
            project_mod.set_project_design_initialized(project_root, True)
    # from_scratch 的 spec 完成 + code_design 也完成 → 置 true
    elif stage_name == "spec" and wf_state.intent == "from_scratch":
        if "code_design" in wf_state.stages and wf_state.stages["code_design"].gate.user_confirmed:
            project_mod.set_project_design_initialized(project_root, True)

    # 写 journal：门禁用户确认
    journal_mod.append_entry(project_root, "门禁用户确认", "user",
                            stage=stage_name, passed=True)

    # 找下一个 stage
    stage_names = list(wf_state.stages.keys())
    current_idx = stage_names.index(stage_name)

    # 有下一个 stage → 推进
    if current_idx + 1 < len(stage_names):
        next_stage = stage_names[current_idx + 1]
        wf_state.current_stage = next_stage
        wf_state.stages[next_stage].status = "in_progress"
        # 新流程在真正进入 spike 时记录设计基线
        if next_stage == "spike":
            ensure_spike_baseline(project_root, wf_state, capture_if_missing=True)
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：阶段推进
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to=next_stage)
        # 打印完成 + 进入下一 stage
        print(f"═══ {stage_name} 完成 ═══")
        print(f"进入 {next_stage}")
        # 下一步：discuss 下一 stage
        print_next_step(f"调 `workflow discuss` 加载 {next_stage} stage 提示词")
    # 没有下一个 stage → 所有 stage 已完成
    else:
        # 临时置 "completed"，由 done 命令确认
        wf_state.current_stage = "completed"
        # 保存 state
        state_mod.save_state(project_root, wf_state)
        # 写 journal：阶段推进到 completed
        journal_mod.append_entry(project_root, "阶段推进", "workflow.py",
                                from_=stage_name, to="completed")
        # 打印完成
        print(f"═══ {stage_name} 完成 ═══")
        print(f"所有 stage 已完成")
        # 下一步：done
        print_next_step("调 `workflow done` 标记完成")


# status 命令：打印 state + journal 摘要；旧状态会先迁移到当前阶段顺序
def cmd_status(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("找不到 .workflow_loop/ 目录。请先在项目根执行官方安装脚本。")
        return

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("还没启动工作流。调 `workflow start` 查看可选意图。")
        return
    if wf_state.run_status == "active" and ensure_stage_path_current(project_root, wf_state):
        state_mod.save_state(project_root, wf_state)

    # 打印 state 摘要
    print(f"═══ 工作流状态 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"intent: {wf_state.intent}")
    print(f"run_status: {wf_state.run_status}")
    print(f"当前 stage: {wf_state.current_stage}")
    print(f"主题: {wf_state.topics or '（未定）'}")
    print(f"启动时间: {wf_state.started_at}")
    print(f"结束时间: {wf_state.ended_at or '（未完成）'}")
    print(f"作废时间: {wf_state.aborted_at or '（未作废）'}")
    print(f"spike_skipped: {wf_state.spike_skipped}")
    print(f"架构: preliminary_done={wf_state.architecture.preliminary_done}, detailed_done={wf_state.architecture.detailed_done}")
    # 打印每个 stage 的门禁状态
    print(f"\n各阶段门禁状态：")
    for name, stage_state in wf_state.stages.items():
        gate = stage_state.gate
        # 3 道闸用 ✓/✗ 显示
        d = "✓" if gate.discussion_complete else "✗"
        c = "✓" if gate.code_validated else "✗"
        u = "✓" if gate.user_confirmed else "✗"
        # 当前 stage 用 → 标记
        marker = "→" if name == wf_state.current_stage else " "
        print(f"  {marker} {name:20s} [{stage_state.status:12s}] 讨论:{d} 校验:{c} 确认:{u}")
    # 打印 journal 最近 10 条
    print(f"\n最近 journal 记录：")
    recent = journal_mod.read_recent(project_root, count=10)
    for entry in recent:
        print(f"  [{entry.get('ts', '')}] {entry.get('action', '')} ({entry.get('actor', '')})")
    print(f"\n下一步：{current_stage_next_instruction(wf_state)}")


# done 命令：标记 Run 为 completed，写结束时间
# 不再二次确认；不删除产物；不改写 bug/index.md
def cmd_done(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # 已经是 completed
    if wf_state.run_status == "completed":
        print("错误：Run 已经是 completed 状态")
        sys.exit(1)
    # 已经是 aborted
    if wf_state.run_status == "aborted":
        print("错误：Run 已经是 aborted 状态")
        sys.exit(1)
    # 前置检查：current_stage 必须是 "completed"（末段 --confirmed 推进后）
    if wf_state.current_stage != "completed":
        print(f"错误：还有未完成的 stage（当前: {wf_state.current_stage}），"
              f"请先完成所有 stage 的 gate --confirmed")
        sys.exit(1)

    # 标记 Run 为 completed
    wf_state.run_status = "completed"
    # 写结束时间
    wf_state.ended_at = state_mod.now_iso()
    # 保存 state
    state_mod.save_state(project_root, wf_state)
    # 写 journal：Run 完成
    journal_mod.append_entry(project_root, "Run 完成", "workflow.py",
                            workflow_id=wf_state.workflow_id)

    # 打印完成信息
    print(f"═══ 工作流完成 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"完成时间: {wf_state.ended_at}")
    # 下一步：工作流结束
    print_next_step("工作流完成。本次 workflow 结束。")


# abort 命令：将进行中的 Run 正式中止
# 不删除 Artifact；不删除 state.json；保留作废快照直至下次 start 覆盖
def cmd_abort(args) -> None:
    # 定位项目根
    project_root = resolve_project_root()
    if project_root is None:
        print("错误：找不到 .workflow_loop/ 目录。")
        sys.exit(1)

    # 读 state
    wf_state = state_mod.load_state(project_root)
    if wf_state is None:
        print("错误：还没启动工作流")
        sys.exit(1)
    # 前置检查：只有 active 可以 abort
    if wf_state.run_status != "active":
        print(f"错误：Run 状态为 {wf_state.run_status}，无法 abort（仅 active 可 abort）")
        sys.exit(1)

    # 标记 Run 为 aborted
    wf_state.run_status = "aborted"
    # 写作废时间
    wf_state.aborted_at = state_mod.now_iso()
    # 保存 state（不删除，保留作废快照）
    state_mod.save_state(project_root, wf_state)
    # 写 journal：Run 作废
    journal_mod.append_entry(project_root, "Run 作废", "workflow.py",
                            workflow_id=wf_state.workflow_id)

    # 打印作废信息
    print(f"═══ 工作流作废 ═══")
    print(f"workflow_id: {wf_state.workflow_id}")
    print(f"作废时间: {wf_state.aborted_at}")
    # 下一步：可重新开新 Run
    print_next_step(f"Run 已作废。可重新调 `workflow start --intent {wf_state.intent}` 开新 Run")


# install-project 命令：安装当前项目（由 install.sh 调用）
# 项目根用 cwd（install.sh 已确认目录）
def cmd_install_project(args) -> None:
    # 项目根 = 当前工作目录
    project_root = os.getcwd()
    # 调 installer 安装项目
    code = installer_mod.install_project(project_root)
    # 退出
    sys.exit(code)


# CLI 入口：解析参数、分发到对应 handler
def main() -> None:
    # 创建 argparse 解析器
    parser = argparse.ArgumentParser(
        description="workflow_loop 工作流管理 CLI",
        prog="workflow",
    )
    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start 命令
    start_parser = subparsers.add_parser("start", help="启动工作流或检查状态")
    # --intent：工作意图（不带时只读状态检查）
    start_parser.add_argument("--intent", choices=INTENT_CHOICES, default=None,
                             help="工作意图（不带时只读状态检查）")
    # --confirm-clean：从零做清场确认（仅 from_scratch）
    start_parser.add_argument("--confirm-clean", action="store_true",
                             help="从零做清场确认（仅 from_scratch）")

    # discuss 命令（无参数，读 state.current_stage）
    subparsers.add_parser("discuss", help="加载当前 stage 提示词")

    # gate 命令
    gate_parser = subparsers.add_parser("gate", help="过门禁")
    # stage 名（位置参数）
    gate_parser.add_argument("stage", help="stage 名")
    # --discuss-done：第 1 道闸
    gate_parser.add_argument("--discuss-done", action="store_true",
                             help="标记讨论完毕（第 1 道闸）")
    # --confirmed：第 3 道闸
    gate_parser.add_argument("--confirmed", action="store_true",
                             help="用户确认 + 推进（第 3 道闸）")
    # --skip：跳过 stage（仅 spike）
    gate_parser.add_argument("--skip", action="store_true",
                             help="跳过 stage（仅 spike）")
    # status 命令（旧状态可能先迁移阶段路径）
    subparsers.add_parser("status", help="打印状态摘要")
    # done 命令
    subparsers.add_parser("done", help="标记完成")
    # abort 命令
    subparsers.add_parser("abort", help="作废当前 Run")

    # install-project 命令（由 install.sh 调用）
    subparsers.add_parser("install-project", help="安装当前项目（由 install.sh 调用）")

    # 解析参数
    args = parser.parse_args()

    # 没传命令 → 打印 help
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # 分发到对应 handler
    if args.command == "start":
        cmd_start(args)
    elif args.command == "discuss":
        cmd_discuss(args)
    elif args.command == "gate":
        cmd_gate(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "done":
        cmd_done(args)
    elif args.command == "abort":
        cmd_abort(args)
    elif args.command == "install-project":
        cmd_install_project(args)
    else:
        # 未知命令（argparse 应该已经拦了，这是兜底）
        print(f"未知命令: {args.command}")
        parser.print_help()
        sys.exit(1)


# 脚本直接运行时调 main
if __name__ == "__main__":
    main()
