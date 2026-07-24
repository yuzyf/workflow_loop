# workflow_loop 设计文档（第一版）

> **目的**：把 AI 驱动的软件开发从"读 markdown 自觉遵守"变成"不过代码门禁就不能推进"的流程约束系统。
> **读者**：用户（审查）+ AI（实现时参考）+ 未来维护者。
> **原则**：MECE（互斥且完备），不省略任何步骤。术语以 `CONTEXT.md` 为准。
> **关系**：本文档是 `CONTEXT.md` 的设计落地。CONTEXT.md 定义术语与约束，DESIGN.md 定义实现形态。冲突时以 CONTEXT.md 为准。

---

## 1. 第一性原理：根问题与根解法

### 1.1 根问题
**AI 读 markdown 描述的工作流，会漂移、跳步、自创步骤——不自觉遵守流程。**

现象：
- AI 读了一段 workflow.md 文字描述，自觉性不可控
- 跳过必要的讨论环节直接写产出
- 自创 workflow 里没有的步骤
- 忘记当前在哪个 stage、漏做门禁

### 1.2 根解法
**把工作流从"文字描述"变成"代码关卡"：**
- AI 不调代码就过不了下一阶段
- 强制力放在**门禁**上（关卡式强制），不在每轮注入上（唠叨式强制）
- 代码是流程的**唯一真相**，`AGENTS.md` 告诉 AI "去调代码"，并给出聊天和文档共同遵守的核心表达规则

### 1.3 第一版要验证的假设
`AGENTS.md 最小契约 + 全局 CLI workflow + Python 代码门禁` 这个组合，能让 AI 被代码关卡约束着走完三种工作意图（from_scratch / product_change / bugfix）的完整工作流（从 start 到 done/abort），并从第一条回复开始使用直白表达。

### 1.4 与旧 spike 的关系
本设计是 `workflow_loop_spike` 旧 spike（4 场景 + `python3 workflow.py` + `SCENARIO_REGISTRY`）的**全量重写**，不是增量改造。旧入口、旧 state schema、旧 ScenarioStrategy 直接删除，不做双写兼容（CONTEXT.md "Legacy CLI Removal"）。

---

## 2. 部署形态

### 2.1 语言：Python
理由（按重要性排）：
1. **零配置 shell 可跑**：macOS 自带 python3
2. **AI 肌肉记忆**：`workflow xxx` 是 AI 写 bash 时的 canonical 模式
3. **训练数据密度**：Airflow/Prefect/Temporal 等 workflow engine 范式海量
4. **策略模式表达力**：ABC + dataclass + Protocol
5. **REPL/自省**：`python -i` 可调试

### 2.2 调用方式：全局 CLI `workflow`
用户命令名 `workflow`（发行包名 `workflow-loop`，导入包名 `workflow_loop`）。AI 通过 shell 调用 `workflow <command> [args]`。每次调用是一个**新进程**，读 state.json → 干一件事 → 写 state.json + 追加 journal.jsonl → 打印下一步指令到 stdout → 退出。

`git` 模型：有状态 CLI、状态在 `.workflow_loop/`、每条命令 mutate state。

### 2.3 安装方式：官方安装脚本
用户在目标项目根执行一条命令：
```
curl -fsSL <安装地址>/install.sh | bash
```
脚本在一次运行里完成两件事：
1. 全局命令安装：检查 `workflow` 全局命令是否存在，存在则复用，不存在则 `pipx install workflow-loop`（或 `uv tool install workflow-loop`）
2. 当前项目安装：调用 `workflow install-project` 子命令，在当前项目根写入运行骨架（详见第 8.8 节）

安装脚本必须在任何写操作前，先打印当前目录的绝对路径，以及将检查或修改的 `AGENTS.md` 和 `.workflow_loop/`，在终端只等待用户确认项目目录。用户取消时整个安装立即结束。

重复安装保护：若当前项目已有完整 `.workflow_loop/` 和有效 `installer_version`，安装脚本判定已安装，直接退出且不修改任何文件。

### 2.4 AI 客户端：opencode / codex
- 客户端无关：契约在 `AGENTS.md` 里自包含
- 不依赖任何客户端的特殊行为（如自动读 AGENTS.md）
- AGENTS.md 自己说清"调 `workflow start` 遵守流程"和核心表达要求

### 2.5 仓库布局

```
workflow_loop_spike/                      # 仓库根（可仍名 spike）
  ├─ pyproject.toml                       # console script: workflow = "workflow_loop.cli:main"
  ├─ install.sh                           # 官方安装脚本（shell 引导 + 调 workflow install-project）
  ├─ AGENTS.md                            # 最小工作流契约 + 核心表达要求
  ├─ README.md
  ├─ DESIGN.md                            # 本文档
  ├─ CONTEXT.md                           # 术语与约束（设计真相源）
  ├─ docs/                                # 流程图等附件
  │   └─ workflow_loop_design_overview.drawio
  ├─ src/workflow_loop/                   # 包代码
  │   ├─ __init__.py
  │   ├─ cli.py                           # CLI 入口 main + 命令 dispatch
  │   ├─ state.py                         # state.json schema + load/save
  │   ├─ journal.py                        # journal.jsonl append + read_recent
  │   ├─ project.py                       # .workflow_loop/project.json 读写
  │   ├─ path_composer.py                 # build_stage_path(intent, project_root)
  │   ├─ verification.py                  # SHA256 哈希 + 失效清零逻辑
  │   ├─ traceability.py                  # 需求交付追踪表结构校验与阶段更新
  │   ├─ bug_record.py                    # 缺陷结果追加与 bug 索引状态更新
  │   ├─ spike_validation.py              # 穿刺清单/详情解析 + spike 门2校验
  │   ├─ installer.py                     # workflow install-project 子命令实现
  │   ├─ role_doc.py                      # 文档概览 + stage 角色定义
  │   ├─ stages/                          # Stage 策略类（替换旧 strategies/）
  │   │   ├─ __init__.py
  │   │   ├─ base.py                      # StageStrategy ABC + clean_spike_tmp
  │   │   └─ stages.py                    # 所有具体 Stage 类
  │   └─ data/                            # 随包装分发的资源
  │       ├─ Template_Repository/         # 提示词模板
  │       └─ Standardized_Repository/     # 规范词
  │           └─ global/
  │               └─ document_writing.md # 所有 stage 共用的写作规范
  ├─ tests/                               # pytest 单元测试
  │   ├─ test_state.py
  │   ├─ test_path_composer.py
  │   ├─ test_verification.py
  │   ├─ test_spike_validation.py
  │   ├─ test_active_run_guard.py
  │   ├─ test_clean_confirm.py
  │   ├─ test_installer.py
  │   └─ test_commands.py
  ├─ .workflow_loop/                      # 本仓库自己作为被管理项目的运行时骨架
  │   ├─ project.json                     # 项目级字段（安装版本、设计初始化、主题历史）
  │   ├─ state.json                       # 当前 Run 快照（开工后才写）
  │   ├─ journal.jsonl                    # 历史记录（开工后才写）
  │   ├─ Template_Repository/             # 从包内 data/ 复制（项目可定制）
  │   ├─ Standardized_Repository/         # 从包内 data/ 复制（项目可定制）
  │   │   └─ global/document_writing.md   # discuss 每次完整加载
  │   └─ spike_tmp/                       # spike stage 的临时代码、样本和原始输出
  └─ .gitignore
```

**注意**：
- 仓库根**不再有** `workflow.py`/`state.py`/`journal.py`/`role_doc.py`/`strategies/`，全部搬进 `src/workflow_loop/`（CONTEXT.md "Package Layout" + "避免全局 CLI 长期绑根目录 workflow.py"）
- `src/workflow_loop/data/Template_Repository/` 与 `src/workflow_loop/data/Standardized_Repository/` 是**打包源**，用 `importlib.resources` 定位后由 installer 复制到目标项目 `.workflow_loop/`
- 本仓库根的 `.workflow_loop/` 是本仓库自己作为被管理项目的运行时骨架（开发态用 `pipx install -e . --force` 把开发版链到全局，然后跑 `workflow install-project` 刷新本仓库的 `.workflow_loop/`）
- 项目根下的产物目录（`spec/`/`plan/`/`acceptance/`/`qa/`/`impl/`/`bug/`）**不在安装时预建**，首次写产物时才建（CONTEXT.md "瘦骨架"）

### 2.6 AGENTS.md 最小契约
仓库根 `AGENTS.md` 既是模板（被 `workflow install-project` 写入到目标项目），也是本仓库自己的开发契约。内容固定为：

```markdown
# Agent 契约

本项目由 workflow_loop 管理。用户提出需求后，调 `workflow start`，
之后严格按每条命令 stdout 打印的"下一步"执行。

## 表达要求

AI 回复用户和编写正式文档时：

- 输出前先弄清实际问题、已知事实、限制和目标。
- 能用直白话就不用抽象词；必须使用专业词时，马上说明它具体指什么。
- 写清谁在什么情况下做什么，以及会得到什么结果。
- 删除空泛、重复，或者没有增加事实、决定、行动和理由的话。
```

安装策略（CONTEXT.md "Agent Contract File"）：
- 当前项目未安装：`workflow install-project` 写入固定最小契约；`AGENTS.md` 不存在则新建，存在则整份覆盖，不询问、不合并、不备份
- 当前项目已安装：按重复安装保护直接退出，不覆盖现有 `AGENTS.md`

### 2.7 开发态入口
开发态用 `pipx install -e . --force` 把 `workflow` 链到全局 editable 模式，之后改代码自动反映；或临时用 `python -m workflow_loop.cli xxx`。两种都和运行态的 `workflow xxx` 一致。

---

## 3. 数据模型

### 3.1 state.json（当前 Run 快照）

`workflow` 每次调用都是新进程，state 必须 persist 到磁盘。state 跟着**被管理的项目**走（不是跟着全局 CLI 走），落在项目根的 `.workflow_loop/state.json`。

```json
{
  "workflow_id": "2026-07-20-1438-from_scratch",
  "intent": "from_scratch",
  "run_status": "active",
  "current_stage": "spec",
  "started_at": "2026-07-20T14:38:00Z",
  "ended_at": null,
  "aborted_at": null,
  "topic": null,
  "topics": [],
  "clean_confirmed": false,
  "spike_skipped": false,
  "stage_path": [
    "spec", "code_design", "spike", "acceptance_plan",
    "test_plan", "plan", "topic_execution",
    "regression_test", "overall_acceptance", "update_code_design"
  ],
  "stages": {
    "<name>": {
      "status": "pending",
      "artifact_paths": ["..."],
      "artifact_produced_at": null,
      "artifact_baseline_captured_at": null,
      "artifact_baseline_hashes": {},
      "gate": {
        "discussion_complete": false,
        "code_validated": false,
        "user_confirmed": false
      }
    }
  },
  "architecture": {
    "preliminary_done": false,
    "detailed_done": false
  },
  "verification": {
    "impl_hash": null,
    "test_plan_hash": null,
    "acceptance_plan_hash": null,
    "test_result_hash": null,
    "regression_test_result_hash": null
  },
  "spike_baseline": {
    "captured_at": null,
    "product_design_hash": null,
    "product_design_paths": [],
    "code_design_hash": null,
    "legacy_unavailable": false
  },
  "meta": {}
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `workflow_id` | str | 启动时生成，`YYYY-MM-DD-HHmm-<intent>` 格式 |
| `intent` | str | `from_scratch` / `product_change` / `bugfix`（替代旧 `entry`/`scenario`） |
| `run_status` | str | `active` / `completed` / `aborted`（替代用 `current_stage=completed` 推断） |
| `current_stage` | str | 当前 stage 名；末段 `--confirmed` 后置为下一 stage 或 `"completed"`（临时中间态，由 `done` 确认为 `completed`） |
| `started_at` | str | ISO 8601 UTC |
| `ended_at` | str\|null | `done` 时写（`run_status=completed`）；`abort` 时为 null |
| `aborted_at` | str\|null | `abort` 时写（`run_status=aborted`）；`done` 时为 null |
| `topic` | str\|null | 旧版单主题兼容字段；新流程不再以它作为主题主数据 |
| `topics` | list[str] | 本次需求的全部验收主题；`from_scratch`、`product_change` 在 `acceptance_plan` 用户确认时写入，`bugfix` 在 `reproduce` 用户确认时写入 |
| `clean_confirmed` | bool | 从零做清场确认标记；`workflow start --intent from_scratch --confirm-clean` 时置 true |
| `spike_skipped` | bool | spike 跳过标记；`gate spike --skip` 时置 true |
| `stage_path` | list[str] | PathComposer 在 start 时解析出的完整 stage 名顺序；固定不再变 |
| `stages` | dict[str, StageState] | 每个 stage 的细粒度状态 |
| `architecture.preliminary_done` | bool | 初步架构完成标记；前段架构 stage `--confirmed` 后置 true |
| `architecture.detailed_done` | bool | 详细架构完成标记；末段 `update_code_design` `--confirmed` 后置 true |
| `verification.*_hash` | str\|null | 上游内容哈希；`gate --confirmed` 时记录，下游 `gate`（无 flag）时检查 |
| `spike_baseline.captured_at` | str\|null | 真正进入 spike 时记录基线的时间；旧状态缺失时保持为空，不用当前文件冒充旧基线 |
| `spike_baseline.product_design_hash` | str\|null | `product.md` 及其功能清单实际链接文档的整体 SHA256 |
| `spike_baseline.product_design_paths` | list[str] | 参与产品设计整体哈希的文件路径 |
| `spike_baseline.code_design_hash` | str\|null | `architecture_code_design.md` 的 SHA256 |
| `spike_baseline.legacy_unavailable` | bool | 旧工作流已经进入 spike，但没有保存入场基线；为 true 时不能证明设计文档在穿刺后发生变化 |
| `meta` | dict | 自由扩展口子（hooks 等后面用） |

**StageState 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | str | `pending` / `in_progress` / `gated` / `done` |
| `artifact_paths` | list[str] | 期望产出文件路径列表 |
| `artifact_produced_at` | str\|null | 产出文件首次出现时间戳 |
| `artifact_baseline_captured_at` | str\|null | 对需要证明本阶段发生修改的阶段，在用户确认讨论完成时记录基线时间 |
| `artifact_baseline_hashes` | dict[str, str\|null] | 讨论完成时相关文件的 SHA256；文件当时不存在时记录 null，用于识别本阶段新增、修改或删除 |
| `gate.discussion_complete` | bool | 第 1 道闸（讨论完毕） |
| `gate.code_validated` | bool | 第 2 道闸（代码校验通过） |
| `gate.user_confirmed` | bool | 第 3 道闸（用户确认） |

**state 不存的**：
- 不存 journal（历史在 journal.jsonl）
- 不存讨论内容（讨论在 AI 和用户之间，不落 workflow）
- 不存 artifact 内容（只存路径，不存文件内容）
- 不存 `project_design_initialized`、`topic_history`、`installer_version`（项目级字段，落 `project.json`）

### 3.2 .workflow_loop/project.json（项目级持久字段）

跨 Run 持久，不被新 Run 覆盖：

```json
{
  "installer_version": "0.1.0",
  "installed_at": "2026-07-20T10:00:00Z",
  "project_design_initialized": false,
  "topic_history": []
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `installer_version` | str | 安装时写入；用于重复安装保护判断 |
| `installed_at` | str | 安装时间 ISO 8601 UTC |
| `project_design_initialized` | bool | 项目设计架构初始化标记；安装时 `false`；`project_design_init` stage `--confirmed` 后置 `true`；`from_scratch` 在 `spec` + `code_design` 都 `--confirmed` 后置 `true` |
| `topic_history` | list[str] | 项目历史中已经确认过的主题；`bugfix` 在 `reproduce` 确认，其他意图在 `acceptance_plan` 确认；跨 Run 保留，防止主题重名 |

### 3.3 journal.jsonl（历史记录）

append-only，每条一行 JSON。记录 workflow 发生的每个动作。

**通用字段**：
- `ts`：ISO 8601 UTC 时间戳
- `action`：动作类型（中文受控词表）
- `actor`：`ai` / `user` / `workflow`

**动作词表**：

| action | 何时记 | 额外字段 |
|---|---|---|
| 工作流启动 | `start --intent` 初始化时 | `workflow_id`, `intent` |
| 清场确认 | `start --intent from_scratch --confirm-clean` 删除产物时 | `cleaned_paths` |
| 路径生成 | `start --intent` 调 PathComposer 后 | `intent`, `stage_path` |
| 提示词加载 | `discuss` 时 | `stage`, `prompt_doc`, `standard_doc` |
| 角色文档加载 | `discuss` 时 | `stage` |
| 门禁讨论完毕 | `gate --discuss-done` 时 | `stage`, `passed` |
| 阶段产物基线 | 需要变化校验的 stage 第一次 `gate --discuss-done` 时 | `stage`, `artifact_hashes` |
| 产出文件检查 | `gate`（无 flag）检查时 | `stage`, `artifact`, `exists` |
| 门禁代码校验 | `gate`（无 flag）时 | `stage`, `passed`, `details` |
| 门禁确认前复核 | `gate --confirmed` 推进前重新校验当前产物时 | `stage`, `passed`, `details` |
| 验证失效 | 上游 hash 变化清零下游时 | `from_stage`, `to_stage`, `reason` |
| 门禁用户确认 | `gate --confirmed` 时 | `stage`, `passed` |
| 阶段推进 | `--confirmed` 推进时 | `from`, `to` |
| 主题确定 | `bugfix` 的 `reproduce` 或其他意图的 `acceptance_plan` `--confirmed` 时 | `topics` |
| 架构标记 | preliminary/detailed 设置时 | `mark`, `stage` |
| spike 跳过 | `gate spike --skip` 时 | `cleaned_paths` |
| spike 清理 | spike `on_advance` 时 | `cleaned_paths` |
| 穿刺基线缺失 | 旧工作流已经在 spike，但没有保存入场基线时 | `reason` |
| Run 作废 | `abort` 时 | `workflow_id` |
| Run 完成 | `done` 时 | `workflow_id` |

### 3.4 state vs journal vs project.json 分离原则

| 文件 | 角色 | 读写模式 |
|---|---|---|
| `state.json` | 当前 Run 快照（"现在在哪"） | 可重写，新 Run 整份覆盖 |
| `journal.jsonl` | 历史记录（"发生过啥"） | append-only，不可改 |
| `project.json` | 项目级持久事实（"项目处于什么状态"） | 跨 Run 持久，不被新 Run 覆盖 |

分离理由：
- state 被多次读改写，journal 只追加，project 跨 Run 持久
- 崩溃恢复：state 可能损坏，从 journal 可重建
- 调试：journal 是完整审计日志
- 项目级字段独立：`project_design_initialized` 和 `topic_history` 不应被新 Run 覆盖

### 3.5 State File Lifecycle

- 同时最多一份 `state.json`，用 `run_status` 区分生命周期
- `run_status=active` → Active Run Guard 禁止再 `start`
- `completed` 或 `aborted` 后：允许新 `start --intent`；新 Run **直接整份覆盖**写入新 `state.json`（新局 `run_status=active`），不另建 history 目录
- 历史追溯：依赖 Journal，不堆叠多份 state 文件
- `abort` 不删产物、不删 state 文件（仅改 `run_status=aborted` + 写 `aborted_at` 直至被下次 `start` 覆盖）

---

## 4. 入口与意图模型

### 4.1 Work Intent Set（工作意图集合）

正式互斥意图仅三类（CONTEXT.md "Work Intent Set"）：

| intent | 含义 | 触发条件 |
|---|---|---|
| `from_scratch` | 从零做新能力或新项目 | 用户要交付新东西 |
| `product_change` | 改已有产品的设计或增加功能 | 项目已有产品，用户要改 |
| `bugfix` | 定位并修复一个具体缺陷 | 用户要修 bug |

`docs_only` 暂不作为正式意图。`existing_no_workflow` / `new_project` 等旧四场景名废弃（CONTEXT.md "Legacy CLI Removal"）。

### 4.2 `start` 命令两种模式

**模式 1：不带 `--intent`（只读状态检查）**
- 不初始化 Run、不清场
- 正常流程已由官方安装脚本保证项目安装完成
- stdout 按序回答：
  1. **有进行中 Run**（`run_status=active`）→ 说明须 `status` 继续原流程（或先 `done`/`abort`）；禁止提示开新 Run
  2. **无进行中 Run**（无 state / `completed` / `aborted`）→ 列出三种意图及一句话说明；下一步：`workflow start --intent from_scratch|product_change|bugfix`

**模式 2：带 `--intent`（初始化 Run）**
- Active Run Guard：若 `run_status=active`，报错并提示先 `status`/`done`/`abort`
- 校验完整 `.workflow_loop/` 与 `installer_version`；校验失败时立即报错，禁止读取或创建 `state.json`（异常保护，不作为正常分支）
- `from_scratch`：先做 Clean Confirm 两段式（见 4.5）；通过后调 PathComposer 生成 stage_path
- `product_change` / `bugfix`：读 `project.json` 的 `project_design_initialized`，传给 PathComposer
- PathComposer 返回 stage 列表后，初始化 `state.json`（全集 schema，所有 stage `pending`，第一个 stage `in_progress`）
- 写 Journal：工作流启动 / 路径生成
- stdout 打印路径向开工摘要（`workflow_id`/`intent`/stage_path/当前 stage/跳过标记），不倾倒文档百科
- 下一步：`workflow discuss`

### 4.3 Active Run Guard
- 触发点：`workflow start --intent <intent>`
- 判定：`state.json` 存在且 `run_status=active` → 报错"有进行中 Run，先 `status`/`done`/`abort`"
- `completed` / `aborted` 不拦截，新 `start --intent` 整份覆盖写新 state
- `--confirm-clean` 不能绕过 Active Run Guard（有未完成 Run 仍须先 `done`/`abort`）

### 4.4 Project Design Init Skip
- 仅对 `product_change` / `bugfix`：读 `project.json` 的 `project_design_initialized`
- `true` → 跳过共享前置 `project_design_init` stage
- `false` → 必须执行 `project_design_init`
- 不用 `spec/architecture_code_design.md` 是否存在决定跳过
- `from_scratch` 不走 `project_design_init`，但在 `spec` + `code_design` 都 `--confirmed` 后写 `project_design_initialized=true`

### 4.5 Clean Confirm（两段式，仅 from_scratch）
开工前先探测是否存在 Clean Scope 内的过程/设计产物：

1. **无过程产物**：不进入删除流程；`workflow start --intent from_scratch` 直接初始化 Run
2. **有过程产物**：`workflow start --intent from_scratch` 只打印将删清单与说明，**不删、不开 Run**；下一步指示用户同意后执行 `workflow start --intent from_scratch --confirm-clean` 才删除并开工

`--confirm-clean` 表达用户确认；`start` 不阻塞读 stdin 做 y/n，由 stdout 指示 AI 询问用户。

无论是否发现并删除旧产物，都把 `project.json` 的 `project_design_initialized` 置为 `false`；之后固定走 `spec` → `code_design`（初步）→ ... → 末段 `update_code_design`。

### 4.6 Clean Scope（清场范围）
- **整目录删除**：只要 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 中存在文件，就删除命中的整个目录及其中全部内容。放在这些目录中的非 workflow 文件也会一起删除。
- **删除根文件**：项目根存在 `traceability.md` 时一并删除，避免新的从零开发工作流继承旧需求的交付追踪记录。
- **不删除其他目录外内容**：`.workflow_loop/Template_Repository/` 与 `Standardized_Repository/` 全部内容；`.workflow_loop/project.json` 本身（只更新初始化字段）；上述六个目录和 `traceability.md` 之外的源代码、`.git` 和项目文件；`.workflow_loop/` 运行时骨架本身。

**Clean Detect List**（监测清单）：
- 监测：项目根下 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 中**已存在且含文件**的路径
- 监测：项目根下已存在的 `traceability.md`
- 不监测：`.workflow_loop/Template_Repository/**`、`.workflow_loop/Standardized_Repository/**`
- 有命中 → 打印将删清单，需 `--confirm-clean`；全无命中 → 直接开工

清单在代码中集中维护，stdout 与删除共用，避免两套规则。

---

## 5. Stage Path 拼法

### 5.1 PathComposer 接口

```python
def build_stage_path(intent: str, project_root: str) -> list[StageStrategy]:
    """根据 intent 和项目事实返回 stage 列表。
    取代旧的四个 Scenario 类并行流水线与 SCENARIO_REGISTRY。"""
```

实现位置：`src/workflow_loop/path_composer.py`。函数形态，不强制类层次（CONTEXT.md "Path Composer"）。

### 5.2 三种意图的路径表

| intent | 条件 | Stage Path |
|---|---|---|
| `from_scratch` | 总是 | 清场确认 → `spec` → `code_design` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design` |
| `product_change` | `project_design_initialized=false` | `project_design_init` → `spec` → `revise_code_design` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design` |
| `product_change` | `project_design_initialized=true` | `spec` → `revise_code_design` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design` |
| `bugfix` | `project_design_initialized=false` | `project_design_init` → `reproduce` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `fix_plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design` |
| `bugfix` | `project_design_initialized=true` | `reproduce` → `spike`（可选）→ `acceptance_plan` → `test_plan` → `fix_plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design` |

**清场确认**不是 stage，是 `from_scratch` 在 `start --intent` 时的前置动作（见 4.5）。

**共享后半截**：`acceptance_plan` → `test_plan` → `plan` / `fix_plan` → `topic_execution` → `regression_test` → `overall_acceptance` → `update_code_design`。

### 5.3 Stage 命名规则（CONTEXT.md 强制）

- `from_scratch` 的前段初步架构 stage 名 = `code_design`
- `product_change` 的设计期架构修订 stage 名 = `revise_code_design`
- 存量项目首次初始化 stage 名 = `project_design_init`
- **所有意图**末段详细架构收尾 stage 名 = `update_code_design`
- 废弃 `generate_code_design`（初步阶段已可能创建同文件，末环不是"首次生成"语义）
- `acceptance_plan`、`test_plan`、`plan` / `fix_plan` 各进入一次，分别完成验收计划、测试计划和实施计划
- `topic_execution` 统筹各主题分别实施、测试和验收，不在顶层路径强制 `impl → test → acceptance` 全局串行
- `regression_test` 是全部主题完成后的最终全量回归；`overall_acceptance` 是整个需求的最终确认
- 任何意图不得跳过末段 `update_code_design`

### 5.4 Optional Spike
- `spike` 在 `from_scratch` / `product_change` / `bugfix` 路径上**默认在路径中**
- `bugfix` 前段顺序固定为 `reproduce → spike`，之后进入共享后半截的 `acceptance_plan → test_plan → fix_plan`；`reproduce` 确认缺陷和根因，`spike` 只验证修复仍依赖的具体技术不确定性
- 用户确认不需要穿刺后，通过显式门禁动作跳过：`workflow gate spike --skip`
- state 记 `spike_skipped=true`、journal 记跳过并推进下一 Stage
- 跳过时不要求 `spike_index.md`、结论文档和临时代码，并清理已存在的 `spike_tmp`
- 不能靠 AI 自觉删 stage；不在 `start` 时默认从路径抹掉 spike
- `spike` `--skip` 不取消其它 stage 的三道门，也不合并门禁
- `--skip` 只能在当前 stage 确实是 `spike` 时调用，不能跨阶段跳转
- 所有 `gate <stage>` 命令只能操作 `state.current_stage` 指向的当前阶段，不能提前操作后续阶段或重复操作已完成阶段；调用错误阶段时，stdout 必须同时打印当前阶段和按当前门禁状态计算出的下一步命令

### 5.5 路径存储与复用
- `start --intent` 时调一次 PathComposer，结果存入 `state.stage_path`（list[str]）
- 后续命令（discuss/gate）读 `state.stage_path` 找当前 stage 对应的 Stage 策略类；旧状态首次加载时迁移到新顺序
- 新 Run 的路径在 `start` 时固定。旧 state 首次迁移时只调整已经确认的新阶段顺序，并保留开工时是否包含 `project_design_init` 的历史决定

---

## 6. Stage 7 步模式 + 3 道闸 + Verification Invalidation

### 6.1 7 步模式（所有正式 stage 都走这个）

```
[S1] 提示词加载
     AI 调 `workflow discuss`
     → workflow 读 state.current_stage
     → 从 state.stage_path 找对应 Stage 策略类实例
     → 加载 role_doc.py 里该 stage 的角色定义
     → 加载 .workflow_loop/Standardized_Repository/global/document_writing.md
     → 从项目内 .workflow_loop/Template_Repository/ 与 Standardized_Repository/ 加载当前 stage 提示词与规范
     → stdout 完整输出：角色全文 + 全局写作规范全文 + 提示词全文 + stage 规范全文 + stage.instruction()
     → 写 journal: 提示词加载 / 角色文档加载

[S2] AI 和用户讨论
     → AI 用提示词里的问题/结构和用户交互
     → workflow 不参与对话，但提示词是 workflow 加载的
     → 讨论持续到双方满意
     → （spike stage 特殊：AI 先查事实、识别真实场景中的技术不确定性，用户逐项决定执行或全部跳过，见第 7.3 节）
     → 可重复 discuss：同一 stage 在 Run 仍 active 且尚未整轮结束前，允许多次 discuss
     → 重复 discuss 不自动清零已通过的门禁

[S3] 讨论完毕门禁（第 1 道闸）
     → 用户确认"讨论完毕"
     → AI 调 `workflow gate <stage> --discuss-done`
     → 前置：命令中的 stage 必须等于 state.current_stage
     → workflow 标记 state.stages.<stage>.gate.discussion_complete = True
     → 对 spec、project_design_init、revise_code_design、reproduce 记录相关文件当前哈希，作为开始写产物前的基线；重复调用不覆盖基线
     → 写 journal: 门禁讨论完毕 passed

[S4] AI 写产出文件
     → 可能是多个文件（spec: product.md + feature_*.md）
     → from_scratch/product_change 的主题在 acceptance_plan 确认后写入 state.topics；bugfix 的主题已在 reproduce 确认，acceptance_plan 只能复用（见第 10 节）
     → spike stage 特殊：清单写入 spec/spike_index.md，每项结论写入 spec/spike_<english-name>.md；只有需要时才把临时代码和原始证据放入 .workflow_loop/spike_tmp/

[S5] 代码校验门禁（第 2 道闸）
     → AI 调 `workflow gate <stage>`（无 flag）
     → 前置：命令中的 stage 等于 state.current_stage，且 discussion_complete=True
     → **Verification Invalidation 检查**（见 6.4）：先重算上游 hash；不一致则退回最早受影响阶段，清零该阶段及其后续门禁和旧哈希
     → 跑 stage.code_validate(project_root)
     → 默认实现：检查所有 artifact_paths 的文件是否存在
     → 不存在 → 打印"产出文件未就绪"，写 journal: 门禁代码校验 failed
     → 存在 → state.stages.<stage>.gate.code_validated = True + 标记 artifact_produced_at
            → 打印"代码校验通过，请和用户确认已写完"
            → 写 journal: 门禁代码校验 passed

[S6] 用户确认（第 3 道闸前半）
     → AI 问用户"<stage> 写完了？"
     → 用户确认

[S7] 用户确认门禁 + 推进（第 3 道闸后半）
     → AI 调 `workflow gate <stage> --confirmed`
     → 前置：命令中的 stage 等于 state.current_stage，且 code_validated=True
     → 重新执行 Verification Invalidation 和 stage.code_validate(project_root)
     → 当前文件已变化或重新校验失败：code_validated=False，停留在当前 stage
     → 阶段确认前更新 traceability.md；bugfix 按阶段追加缺陷结果，更新失败则不推进
     → 标记 user_confirmed = True
     → 调 stage.on_advance(project_root)（spike 清理临时代码并记录清理 journal）
     → **记录上游 hash**（见 6.4）：acceptance_plan、test_plan、topic_execution、regression_test 记录对应 verification hash
     → **设置 Architecture Gate Marks**（见第 9 节）：本 stage 是 code_design/revise_code_design/project_design_init/update_code_design 时，置对应 mark
     → **设置 project_design_initialized**（见 4.4）：本 stage 是 project_design_init 或 from_scratch 的 spec+code_design 都确认后
     → 推进 state.current_stage = 下一 stage
     → 写 journal: 门禁用户确认 passed / 阶段推进 <stage>→<next> / 追踪表更新 / 缺陷状态更新 / 主题确定（若为 bugfix 的 reproduce 或其他意图的 acceptance_plan）/ 架构标记（若适用）
```

### 6.2 3 道闸（顺序硬性，CONTEXT.md "Gate Policy"）

| 闸 | 字段 | 命令 | 前置条件 | 不满足时报错 |
|---|---|---|---|---|
| 1 讨论完毕 | `discussion_complete` | `gate <stage> --discuss-done` | stage 是当前阶段；用户通过命令确认讨论完成，程序不检查聊天记录或提示词加载记录 | 当前阶段不一致时拒绝 |
| 2 代码校验 | `code_validated` | `gate <stage>` | stage 是当前阶段且 `discussion_complete=True` | 当前阶段不一致或讨论未完成时拒绝 |
| 3 用户确认 | `user_confirmed` | `gate <stage> --confirmed` | stage 是当前阶段、`code_validated=True`，并且当前产物重新校验通过 | 当前阶段不一致、未过门2或产物已变化时拒绝 |

**跳步抛错**：直接调 `gate --confirmed` 而没跑前两道 → 报错并提示正确顺序。

**门禁策略第一版**：每个正式 Stage 保留三道门、顺序硬性。`topic_execution`（按主题实施、测试和验收）、`regression_test`（最终全量回归）与 `overall_acceptance`（整体验收）是强制 Stage，不提供 `--skip`；自动测试不可用时可执行人工测试并记录证据。AI 不得自动替用户验收。

### 6.3 StageStrategy ABC 接口

```python
class StageStrategy(ABC):
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def artifact_paths(self) -> list[str]: ...
    
    @abstractmethod
    def role_doc_path(self) -> str | None: ...
    
    @abstractmethod
    def prompt_doc_path(self) -> str | None: ...
    
    @abstractmethod
    def standard_doc_path(self) -> str | None: ...
    
    def code_validate(self, project_root: str) -> tuple[bool, str]:
        """默认实现：检查所有 artifact_paths 文件都存在。
        子类可重写做更复杂校验。"""
        ...
    
    def on_advance(self, project_root: str) -> list[str]:
        """stage 推进时的钩子。默认 no-op。
        spike stage 重写这个清理临时代码、样本和原始输出，返回已清理条目。"""
        return []
    
    @abstractmethod
    def instruction(self) -> str: ...
```

### 6.4 Verification Invalidation（验证结果自动失效）

**核心机制**：通过状态只对绑定的上游内容有效。上游变化时，退回最早受影响的顶层阶段，清零该阶段及其后续门禁和旧哈希。

**哈希对象**（SHA256）：

| hash 字段 | 哈希对象 | 记录时机 |
|---|---|---|
| `impl_hash` | `impl/` 下全部实施记录 + 当前代码修改快照 | `gate topic_execution --confirmed` 时 |
| `test_plan_hash` | 本次全部 `qa/<topic>_plan.md` | `gate test_plan --confirmed` 时 |
| `acceptance_plan_hash` | 本次全部 `acceptance/<topic>_plan.md` | `gate acceptance_plan --confirmed` 时 |
| `test_result_hash` | 本次全部 `qa/<topic>_result.md` | `gate topic_execution --confirmed` 时 |
| `regression_test_result_hash` | `qa/final_regression_result.md` | `gate regression_test --confirmed` 时 |

**穿刺设计基线**不属于 Verification Invalidation，但同样使用 SHA256：

| 字段 | 哈希对象 | 记录时机 | 使用位置 |
|---|---|---|---|
| `spike_baseline.product_design_hash` | `spec/product.md` + 其功能清单实际链接的 `spec/feature_*.md`，路径和文件哈希共同参与 | 真正进入 `spike` 时记录；旧状态缺失时不自动补造 | spike 门2发现任意项目写“产品设计影响：需要修改”时比较当前值 |
| `spike_baseline.code_design_hash` | `spec/architecture_code_design.md` | 同上 | spike 门2发现任意项目写“代码设计影响：需要修改”时比较当前值 |

**失效检查**：第 2 道门和第 3 道门推进前都重算上游 hash：

| 变化来源 | 退回阶段 | 清零范围 |
|---|---|---|
| 验收计划文件或主题集合 | `acceptance_plan` | `acceptance_plan` 及全部后续阶段 |
| 测试计划文件 | `test_plan` | `test_plan` 及全部后续阶段 |
| 实施代码、实施记录或主题测试结果 | `topic_execution` | `topic_execution` 及全部后续阶段 |
| 最终全量回归结果 | `regression_test` | `regression_test`、`overall_acceptance`、`update_code_design` |

**失效动作**：清零对应门禁和旧哈希，把 `current_stage` 移到最早受影响阶段，写入 State Snapshot，并写 journal（"验证失效"，记录 from_stage/to_stage/reason）。主题内部的选择性失效规则后续在 `topic_execution` 详细设计中补充，本轮不提前实现。

**实现位置**：`src/workflow_loop/verification.py`。

### 6.5 on_advance() 钩子
- 默认 no-op
- `spike` stage 重写：删除 `.workflow_loop/spike_tmp/` 下所有内容（保留 `spec/spike_index.md`、`spec/spike_*.md` 和更新后的设计文档）
- 后面扩展：某 stage 推进时要通知/迁移/清理，重写这个方法

### 6.6 stdout 驱动原则（核心设计约束）

`workflow` 每条命令的 stdout 末尾必须以 `───── 下一步：xxx ─────` 结尾，告诉 AI 下一步干啥。这是把"流程步骤"从 AGENTS.md（文字）搬到代码里的关键设计。

**stdout 格式**：
```
<命令的实际输出内容>
──────────────────────────────────────────
下一步：<具体指令，含完整命令行>
```

**每条命令的"下一步"映射**：见第 8 节命令清单。

**强制力分层**：

| 层 | 形式 | 强制度 |
|---|---|---|
| AGENTS.md（最小契约 + 核心表达要求） | 文字 | 弱：AI 可能不看，但不看就不知道入口和聊天表达要求 |
| workflow stdout 下一步 | 代码生成 | 中：AI 大概率跟着走，但不强制 |
| workflow 门禁 | 代码强制 | 强：跳步直接报错，过不去 |

**根本边界**：代码能强制"不调 gate 过不去"，但不能强制"AI 主动调命令"，也不能自动判断一篇文章是否直白。AGENTS.md 必须给出入口和核心表达要求；全局写作规范负责详细检查，用户确认负责最后判断。

### 6.7 全局写作规范

- 固定路径：`.workflow_loop/Standardized_Repository/global/document_writing.md`
- 适用：AI 对用户的回复，以及 AI 编写或修改的正式文档
- 不适用：`workflow` 命令行 stdout
- 加载顺序：角色说明 → 全局写作规范 → 当前 stage 模板 → 当前 stage 规范 → 附加材料 → 指令与产物
- 核心要求：输出前确认实际问题、事实、限制和目标；能用普通话说明就不用抽象词；写清对象、条件、动作和结果；删除重复和不增加信息的话
- 正式文档写完后执行完整对抗性清晰审查；AI 聊天发送前快速检查抽象词、歧义、重复和废话
- 不做关键词封禁。代码只检查全局规范已安装并被 `discuss` 加载，不能声称自动判断写作质量
- 本次只更新当前仓库和未来新安装项目；其他已安装项目不自动覆盖，升级机制以后单独设计

---

## 7. Stage 详典

每个 stage 的角色 / 提示词路径 / 规范路径 / 产物路径 / `code_validate` / `on_advance` / instruction。提示词路径相对 `.workflow_loop/`，规范路径同。

### 7.1 spec（产品设计 + 功能拆分）

| 字段 | 值 |
|---|---|
| 角色 | 产品设计师 |
| 提示词 | `Template_Repository/spec/spec.md` |
| 规范 | `Standardized_Repository/spec/spec.md` |
| 产物 | `spec/product.md` + `spec/feature_<english-name>.md`（可能多个，文件名使用英文，正文使用中文） |
| `code_validate` | 检查 `spec/product.md` 存在 + 至少一个 `spec/feature_*.md` 存在；第一次 `--discuss-done` 时记录相关文件路径与内容哈希，校验时比较前后变化（证明产物属于本 Run） |
| `on_advance` | no-op；`from_scratch` 中若 `code_design` 也已 `--confirmed`，置 `project_design_initialized=true` |
| instruction | "产品设计阶段：产出 spec/product.md（产品设计说明书 + 功能路由）+ spec/feature_*.md（功能拆分）" |

**门2特殊校验**：
- `from_scratch` 要求新建 `product.md` 且至少新建一个功能文档
- `product_change` 要求 `product.md` 有变化且至少一个功能文档新增、修改或删除

**产品设计提示词规则**：
- 产品背景说明产品诞生的现实背景和需求来源，不把提示词缺陷、模板修改历史或技术实现写成产品背景
- 产品目标只写完成后要达到的结果，不把 AI 的提问、调查和整理方法写成目标
- 产品背景、产品目标、功能背景和设计原因必须来自用户确认或可核实事实；代码和运行结果不能单独证明历史原因
- 用户清单只列实际用户；AI 和系统服务作为执行角色写在场景或使用过程中
- 产品通用规则只放整个产品或多个功能共同生效的用户可见行为；讨论方法归阶段规范，表达要求归全局写作规范
- `bugfix`（修 bug）中，项目设计未初始化时由 `project_design_init` 建立产品设计；已初始化时使用现有设计；改变产品行为时改走 `product_change`（修改产品）

### 7.2 code_design（从零做前段初步架构）

| 字段 | 值 |
|---|---|
| 角色 | 代码架构设计师（初步） |
| 提示词 | `Template_Repository/code_design/code_design.md` |
| 规范 | `Standardized_Repository/code_design/code_design.md` |
| 产物 | `spec/architecture_code_design.md` |
| `code_validate` | 默认（检查文件存在） |
| `on_advance` | 置 `architecture.preliminary_done=true`；`from_scratch` 中若 `spec` 也已 `--confirmed`，置 `project_design_initialized=true` |
| instruction | "初步代码架构阶段：从已确认产品设计推导代码分层、关键节点和功能代码过程，产出 spec/architecture_code_design.md" |

**顺序约束**：`from_scratch` 中顺序固定为**先产品设计与功能拆分、后初步架构**（先定做什么，再定怎么搭）。不可因旧文件存在跳过。

**文档主线**：面向项目维护者，说明整个项目的代码怎样落实产品设计。内容固定从产品概览开始，再说明产品怎样决定代码架构、代码分层、架构关键节点、每个产品功能的完整代码过程、多个功能共同使用的代码，以及产品设计与代码实现的差异。

**代码映射**：每个产品功能按场景说明完整代码过程。流程图中的每个程序处理节点必须直接标出文件、类、函数、类型或接口，并说明关键判断、调用、状态或数据结果、失败结果和验证位置。不能只列模块名或函数名，也不能使用脱离流程的“状态变化”字段。

**图的边界**：架构图只画代码分层、职责和依赖方向；功能流程图或时序图只画一个明确场景的执行过程；单个复杂函数需要时再单独画内部流程或状态迁移。三种范围不能混在一张图中。

### 7.3 spike（可选穿刺）

| 字段 | 值 |
|---|---|
| 角色 | 技术不确定性验证工程师 |
| 提示词 | `Template_Repository/spike/spike.md` |
| 规范 | `Standardized_Repository/spike/spike.md` |
| 产物 | `spec/spike_index.md` + 每项 `spec/spike_<english-name>.md`；需要时临时代码、样本和原始输出进 `.workflow_loop/spike_tmp/<english-name>/` |
| `code_validate` | `SpikeStage` 调 `spike_validation.validate_spike_stage()`：检查当前工作流编号、唯一穿刺项编号、文档链接、八章、固定字段、结果一致性、阻塞状态、剩余风险、意图边界和设计哈希 |
| `on_advance` | 删除 `.workflow_loop/spike_tmp/` 下所有内容，保留清单、结论和设计文档 |
| instruction | "先查产品设计、代码设计、相关代码和运行事实，识别真实场景中的技术不确定性；用户决定执行清单或全部跳过。正常执行时写清单和每项结论，需要临时代码时放入 spike_tmp，并在进入计划前同步受影响的设计文档。" |

**适用路径**：`from_scratch`、`product_change`、`bugfix`。修 bug 时位于 `reproduce` 和 `fix_plan` 之间。

**候选识别**：AI 必须先查看产品设计、代码设计、相关代码、测试、日志、依赖文档和已有运行结果；具备运行条件时先运行相关现有功能。已经能确认的事项不进入穿刺。语义重复由 AI 比较真实场景、不确定内容、证据和结果用途，程序不声称能判断。

**用户选择**：候选尚未选择时不写入清单、不分配 `SP-001` 编号。用户逐项决定后确认最终清单，第一道门才通过。没有穿刺项时用户明确决定跳过。

**真实场景**：验证对象必须是实际接口、业务文件、目标平台、真实数据特征、实际数据规模、操作路径或故障条件。不能用模拟返回、自造业务数据或理想化文件证明真实行为。方法不限于原型；现有命令或程序能取得证据时优先使用。

**特殊跳过**：`workflow gate spike --skip` 只允许当前 stage 为 `spike`，跳过整个 stage（包括三道门），state 记 `spike_skipped=true`，清理临时目录，journal 记跳过并推进下一 Stage。

**正常门2**：

1. `spike_index.md` 和每份详情必须绑定当前 `workflow_id`。
2. 清单中每项必须有唯一 `SP-xxx` 编号和唯一结论文档，且不再是“待验证”。
3. 详情必须包含八章和固定字段，清单状态必须与详情一致。
4. 任意项目“是否阻塞后续：是”时失败。
5. `仍未确认`但不阻塞时，剩余风险、后续处理阶段和后续检查内容必须完整。
6. 产品设计或代码设计写“需要修改”时，对应当前哈希必须不同于 `spike_baseline`。
7. `bugfix` 中出现“产品设计影响：需要修改”时失败，提示结束当前 Run 后启动 `product_change`。
8. 旧工作流缺少入场基线时，全部设计影响为“无需修改”才允许继续；需要证明设计变化时直接失败。

**临时代码**：不是每次穿刺必需；只在现有手段无法取得证据时编写。不进正式代码，用户确认结果后自动清理。正式实现可以使用穿刺确认的事实，但不能直接照搬缺少正式错误处理和测试的临时代码。

### 7.4 project_design_init（存量项目首次初始化）

| 字段 | 值 |
|---|---|
| 角色 | 存量产品与架构分析师 |
| 提示词 | `Template_Repository/code_design/project_design_init.md`，并附加加载 `Template_Repository/spec/spec.md` + `Template_Repository/code_design/code_design.md` |
| 规范 | `Standardized_Repository/code_design/project_design_init.md`，并附加加载 `Standardized_Repository/spec/spec.md` + `Standardized_Repository/code_design/code_design.md` |
| 产物 | `spec/product.md` + 多个 `spec/feature_<english-name>.md` + `spec/architecture_code_design.md` + `spec/project_design_init_evidence.md`（调查证据） |
| `code_validate` | 校验产品设计、代码设计和调查证据都存在且相对讨论完成时的基线发生变化；调查证据必须绑定当前工作流编号，列出至少一个真实存在的代码文件，并按运行条件记录命令、结果或无法运行原因 |
| `on_advance` | 置 `project_design_initialized=true` 与 `architecture.preliminary_done=true` |
| instruction | "已有项目设计初始化：必须查看代码和测试，具备安全条件时实际运行，一次建立相互一致的 spec/product.md + spec/feature_*.md + spec/architecture_code_design.md" |

**顺序约束**：该 stage 完成前作废不得写 `project_design_initialized=true`。不拆成彼此可能不一致的"产品反推"+"架构反推"两轮。

**事实边界**：代码和运行结果用于确认产品当前怎样工作，不能单独证明产品当初为什么诞生或某个功能为什么设计；历史背景无法核实时必须询问用户或标记未确认。

**调查要求**：必须查看项目说明、构建与依赖配置、用户实际入口、关键调用链、状态与外部输入输出、自动化测试。具备安全的本地运行条件时，至少运行现有测试，并在条件允许时构建项目和走主要产品入口。需要生产账号、真实数据、付费服务或外部写入时先取得用户同意。调查过程必须写入 `spec/project_design_init_evidence.md`，不能只在聊天中声明已经完成。

**证据状态**：关键结论区分运行确认、测试确认、代码确认、文档或用户确认、未确认和冲突。代码确认表示已经阅读真实调用链和关键逻辑，不等于已经运行。不可达、隐藏、未完成或废弃代码不能直接写成正式产品功能。

### 7.5 revise_code_design（改产品设计期改架构）

| 字段 | 值 |
|---|---|
| 角色 | 架构文档修订者 |
| 提示词 | `Template_Repository/code_design/revise_code_design.md` |
| 规范 | `Standardized_Repository/code_design/revise_code_design.md` |
| 产物 | 更新 `spec/architecture_code_design.md`（已存在，按新设计改） |
| `code_validate` | 检查 `spec/architecture_code_design.md` 存在且有变化（内容哈希前后比对） |
| `on_advance` | 置 `architecture.preliminary_done=true` |
| instruction | "设计期架构修订：按变更后的产品设计改 spec/architecture_code_design.md" |

**强制**：`product_change` 在 `spec` 之后、`plan` 之前必须经过 `revise_code_design`。

### 7.6 update_code_design（末段详细架构收尾）

| 字段 | 值 |
|---|---|
| 角色 | 架构文档更新者（详细落地） |
| 提示词 | `Template_Repository/code_design/update_code_design.md` |
| 规范 | `Standardized_Repository/code_design/update_code_design.md` |
| 产物 | 写入/更新 `spec/architecture_code_design.md` |
| `code_validate` | 检查文件和当前工作流追踪表存在；bugfix 无结构变化时显式确认"无结构变化"（不省略 stage） |
| 门3确认处理 | 更新追踪表的最终代码设计列，并置 `architecture.detailed_done=true` |
| instruction | "详细架构收尾：写入/更新 spec/architecture_code_design.md，反映最终被验证和接受的真实结构" |

**强制**：所有工作意图在 `regression_test` 通过且 `overall_acceptance` 经用户确认之后必须经过 `update_code_design`。

### 7.7 acceptance_plan（验收计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 验收计划制定者 |
| 提示词 | `Template_Repository/acceptance/acceptance_plan.md` |
| 规范 | `Standardized_Repository/acceptance/acceptance_plan.md` |
| 产物 | 项目根 `traceability.md` + `acceptance/<topic>_plan.md` |
| `code_validate` | 校验当前工作流追踪章节、九列交付链路、每个主题的六个固定章节、`AC-01` 形式的验收条件、逐条追踪行、初始状态和上下游路径；`bugfix` 额外校验计划主题与缺陷记录中已确认的主题完全一致 |
| 门3确认处理 | `from_scratch`、`product_change` 把主题列表写入 `state.topics` 和项目 `topic_history`；`bugfix` 只复核 `reproduce` 已登记的主题；三种意图都记录 `verification.acceptance_plan_hash` |
| instruction | "从零开发和修改产品先确定全部验收主题；修 bug 复用缺陷复现阶段已经确认的主题。为每个主题写清什么算完成，并建立需求交付追踪表" |

**讨论顺序**：`from_scratch` 和 `product_change` 先让用户确认完整主题清单，再逐个主题讨论验收条件。`bugfix` 不重新讨论主题名称，只讨论缺陷记录中既有主题的验收范围和验收条件。

**主题计划结构**：每份 `acceptance/<topic>_plan.md` 固定包含“本次需求与验收目标、产品设计依据、验收范围、验收条件、完成判定、上下游文档”。每条验收条件必须写清“条件与触发、预期结果、产品设计或缺陷依据”，不能写测试环境、测试数据、执行命令、代码方案或实施步骤。

**需求交付追踪表**：`traceability.md` 按工作流编号分段，每条验收条件单独占一行。验收计划阶段填写来源、主题和验收条件；测试计划和实施计划列写“待制定”，实施记录、测试结果和验收结果列写“待执行”，最终代码设计列写“待更新”。后续阶段只更新自己负责的列：`test_plan` 更新测试计划，`plan/fix_plan` 更新实施计划，`topic_execution` 更新实施记录、主题测试结果和主题验收结果，`regression_test` 更新最终回归结果，`overall_acceptance` 更新整体验收结果，`update_code_design` 更新最终代码设计。验收计划哈希只计算主题计划文件，不包含持续更新的追踪表。

### 7.8 test_plan（测试计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 测试计划制定者 |
| 提示词 | `Template_Repository/qa/test_plan.md` |
| 规范 | `Standardized_Repository/qa/test_plan.md` |
| 产物 | `qa/<topic>_plan.md` + 更新 `qa/index.md` |
| `code_validate` | `state.topics` 中每个主题都有同名 `qa/<topic>_plan.md`，并且当前工作流追踪表存在 |
| 门3确认处理 | 记录 `verification.test_plan_hash`，更新追踪表的测试计划列 |
| instruction | "根据已确认的验收主题制定测试计划，不执行测试，也不改变主题" |

具体测试项字段和文档正文结构后续单独完善。

### 7.9 plan（实施计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 实施计划制定者 |
| 提示词 | `Template_Repository/plan/plan.md` |
| 规范 | `Standardized_Repository/plan/plan.md` |
| 产物 | `plan/index.md` + 至少一份实施计划文档 |
| `code_validate` | 检查 `plan/index.md`、实施计划文档和当前工作流追踪表存在 |
| 门3确认处理 | 更新追踪表的实施计划与任务列 |
| instruction | "根据已确认的验收计划和测试计划制定实施步骤；不在这里重新确定主题" |

实施计划文档可以按实施任务拆分，不要求与验收主题一一对应。具体正文结构后续单独完善。

### 7.10 fix_plan（修复实施计划制定，bugfix 专用）

| 字段 | 值 |
|---|---|
| 角色 | 修复实施计划制定者 |
| 提示词 | `Template_Repository/plan/fix_plan.md` |
| 规范 | `Standardized_Repository/plan/fix_plan.md` |
| 产物 | `plan/index.md` + 至少一份修复实施计划文档 |
| `code_validate` | 同 plan，且检查当前工作流追踪表存在 |
| 门3确认处理 | 更新追踪表的实施计划与任务列 |
| instruction | "根据已确认的验收计划和测试计划制定修复步骤；不在这里重新确定主题" |

### 7.11 topic_execution（按主题执行）

| 字段 | 值 |
|---|---|
| 角色 | 按主题执行协调者 |
| 提示词 | `Template_Repository/execution/topic_execution.md` |
| 规范 | `Standardized_Repository/execution/topic_execution.md` |
| 产物 | 实际代码、实施记录、每个主题的测试结果与验收结果 |
| `code_validate` | 当前工作流追踪表存在；`state.topics` 中每个主题都有实施记录、当前工作流编号匹配且写“测试结果：通过”的测试结果、当前工作流编号匹配且写“验收结果：通过”的主题验收结果 |
| 门3确认处理 | 记录实施代码快照与全部主题测试结果哈希，更新追踪表的实施记录、测试结果和验收结果列；bugfix 追加“主题验收通过，待全量回归” |
| instruction | "分别推进各主题的实施、测试和验收；全部主题完成后才结束本阶段" |

固定字段和阶段结果由程序校验；测试项、测试数据、实施任务和主题内部文档结构仍由后续提示词和规范讨论决定。

### 7.12 regression_test（最终全量回归）

| 字段 | 值 |
|---|---|
| 角色 | 最终回归测试执行者 |
| 提示词 | `Template_Repository/qa/final_regression.md` |
| 规范 | 无独立规范文件；固定通过条件由 `RegressionTestStage.code_validate()` 执行 |
| 产物 | `qa/final_regression_result.md` |
| `code_validate` | 检查当前工作流追踪表、结果文件中的工作流编号和固定字段“回归状态：通过”；未通过时不能进入整体验收 |
| 门3确认处理 | 记录 `verification.regression_test_result_hash`，更新追踪表的测试结果列；bugfix 失败时在门2记录“回归失败，重新处理中” |
| instruction | "全部主题完成后，对全部已合并代码执行最终全量回归" |

### 7.13 overall_acceptance（整体验收）

| 字段 | 值 |
|---|---|
| 角色 | 整体验收执行者 |
| 提示词 | `Template_Repository/acceptance/overall_acceptance.md` |
| 规范 | 无独立规范文件；固定通过条件由 `OverallAcceptanceStage.code_validate()` 执行 |
| 产物 | `acceptance/overall_result.md` |
| `code_validate` | 先复核当前工作流追踪表和最终全量回归已经通过，再检查结果绑定当前工作流编号，并且明确写“整体验收状态：通过” |
| 门3确认处理 | 更新追踪表的验收结果列；bugfix 追加“已修复并验收”并更新 `bug/index.md` |
| `on_advance` | no-op |
| instruction | "最终全量回归通过后，由用户确认整个需求是否完成" |

### 7.14 reproduce（bug 复现，bugfix 专用）

| 字段 | 值 |
|---|---|
| 角色 | bug 复现者 |
| 提示词 | `Template_Repository/reproduce/reproduce.md` |
| 规范 | `Standardized_Repository/reproduce/reproduce.md` |
| 产物 | `bug/<YYYY-MM-DD_HHmm-<bug描述>>.md` + 更新 `bug/index.md` |
| `code_validate` | 比较讨论完成时的文件基线，要求 `bug/index.md` 和至少一份本次缺陷记录发生变化；检查文件名、当前工作流编号、索引链接、七个固定复现章节、真实环境与输入、复现状态“已复现”、根因状态“已确认”、根因说明、位置、证据和唯一验收主题 |
| 门3确认处理 | 从本次缺陷记录读取主题，写入 `state.topics` 和项目 `topic_history`；一份缺陷记录对应一个主题，同一工作流内主题不能重复 |
| `on_advance` | no-op |
| instruction | "缺陷复现阶段：使用真实环境和真实输入复现缺陷、确认根因，并根据修复后用户必须恢复的结果确定验收主题；产出 bug/<YYYY-MM-DD_HHmm-缺陷描述>.md 并更新 bug/index.md" |

**注意**：reproduce 用 bug 描述做文件名，验收主题写在缺陷记录字段中，不用主题替代缺陷文件名。缺陷记录不预先链接尚未生成的验收文档；后续验收计划和验收结果链接回缺陷记录。程序只能检查文档结构、状态、链接、文件变化和明确字段，不能证明证据没有伪造；第三道门仍由用户核对真实复现过程、根因证据和主题名称。

---

## 8. 命令清单

> **设计约束**：每条命令的 stdout 末尾必须给出“下一步”。`status` 在读取旧状态时允许先执行阶段路径迁移，然后根据当前门禁状态打印正确命令。

正式日常命令面：`start`、`discuss`、`gate`、`status`、`done`、`abort`（及已定参数：`--intent`、`--confirm-clean`、`gate spike --skip`、`gate <stage> --discuss-done`、`gate <stage> --confirmed`）。安装命令 `install-project` 是日常 CLI 之外的安装入口，由 `install.sh` 调用。

旧命令 `overview` / `align` / `start --entry` / `attach` / `--overwrite-agent` 直接删除，不做双写兼容。误用旧参数时明确报错并用说人话提示正确入口。

### 8.1 `start`（两种模式）

**模式 1：不带 `--intent`（只读状态检查）**
- **干啥**：只读取工作状态并指路，不初始化 Run、不清场
- **stdout 内容**：
  - 有进行中 Run → 说明须 `status` 继续原流程（或先 `done`/`abort`）；禁止提示开新 Run
  - 无进行中 Run → 列出三种 intent 及一句话说明
- **stdout 末尾**：`下一步：workflow start --intent from_scratch|product_change|bugfix`
- **写 journal**：无（纯只读）

**模式 2：带 `--intent <intent>`**
- **干啥**：初始化 Run（`from_scratch` 另循 Clean Confirm）
- **前置**：Active Run Guard（`run_status=active` 则报错）；校验 `.workflow_loop/` 完整
- **`from_scratch` 流程**：
  1. Clean Detect List 探测项目根过程产物
  2. 有产物且无 `--confirm-clean` → 打印将删清单，不开 Run；下一步指示加 `--confirm-clean`
  3. 有产物且有 `--confirm-clean` → 删除产物，置 `project_design_initialized=false`，继续
  4. 无产物 → 直接继续，置 `project_design_initialized=false`
- **`product_change`/`bugfix` 流程**：读 `project.json` 的 `project_design_initialized`，传给 PathComposer
- **PathComposer 调用**：`build_stage_path(intent, project_root)` 返回 stage 列表
- **state 初始化**：全集 schema，所有 stage `pending`，第一个 stage `in_progress`，`run_status=active`
- **stdout 内容**：路径向开工摘要（`workflow_id`/`intent`/stage_path/当前 stage/跳过标记）；不倾倒文档百科
- **stdout 末尾**：`下一步：workflow discuss`
- **写 journal**：工作流启动 / 路径生成 / 清场确认（若适用）

### 8.2 `discuss`
- **干啥**：加载全局写作规范和当前 stage 的提示词、规范、角色定义，**完整输出**给 AI
- **何时调**：每个 stage 的 S1
- **流程**：
  1. 读 `state.current_stage`
  2. 从 `state.stage_path` 找对应 Stage 策略类实例
  3. 加载 `role_doc.py` 里该 stage 的角色定义
  4. 加载 `Standardized_Repository/global/document_writing.md` 全局写作规范
  5. 加载 `stage.prompt_doc_path()` 指向的提示词
  6. 加载 `stage.standard_doc_path()` 指向的阶段规范
  7. stdout 按顺序打印：角色全文 + 全局写作规范全文 + 提示词全文 + 阶段规范全文 + 附加材料 + `stage.instruction()` + 期望产出路径
  8. 写 journal：提示词加载（含全局规范路径）/ 角色文档加载
- **可重复加载**：同一 stage 在 Run 仍 active 且尚未整轮结束前，允许多次 discuss；重复 discuss 不自动清零已通过的门禁
- **stdout 末尾**：`下一步：用这个提示词和用户讨论。讨论完用户说"完毕"后，调 workflow gate <stage> --discuss-done`

### 8.3 `gate <stage> --discuss-done`
- **干啥**：标记讨论完毕（第 1 道闸）
- **前置**：命令中的 stage 必须是 `state.current_stage`。该命令代表用户已经确认讨论完成，程序不读取聊天记录，也不要求 journal 中存在提示词加载记录。
- **错误阶段**：拒绝修改状态，并打印当前 stage 和正确的下一步。当前阶段尚未完成讨论时，下一步先给出 `workflow discuss`，并同时说明讨论完成后的 `workflow gate <current_stage> --discuss-done`
- **流程**：标记 `gate.discussion_complete = True`；需要变化校验的阶段同时记录当前文件哈希基线；写 journal。重复调用不覆盖原基线。
- **stdout 末尾**：`下一步：写产出文件 <artifact_paths>。写完调 workflow gate <stage>`

### 8.4 `gate <stage>`（无 flag，第 2 道闸代码校验）
- **前置**：命令中的 stage 必须是 `state.current_stage`，并且 `discussion_complete=True`
- **Verification Invalidation 检查**：先重算上游 hash；不一致时退回最早受影响阶段，清零该阶段及其后续门禁和旧哈希，写 journal "验证失效"，并打印退回阶段的下一条命令
- **流程**：
  1. 跑 `stage.code_validate(project_root)`
  2. 检查产出文件是否存在（写 journal: 产出文件检查）
  3. 失败 → 清除旧的 `code_validated` 和 `user_confirmed`，打印"产出文件未就绪"，写 journal: 门禁代码校验 failed
  4. 成功 → 标记 `code_validated=True` + `artifact_produced_at`，打印"请和用户确认已写完"
- **stdout 末尾**（通过）：`下一步：问用户"<stage> 写完了？"，用户确认后调 workflow gate <stage> --confirmed`
- **stdout 末尾**（失败）：`下一步：产出文件未就绪，补完后再调 workflow gate <stage>`

### 8.5 `gate <stage> --confirmed`（第 3 道闸用户确认 + 推进）
- **前置**：命令中的 stage 必须是 `state.current_stage`，并且 `code_validated=True`
- **流程**：
  1. 重新执行上游失效检查和当前 stage 的 `code_validate()`，写 journal“门禁确认前复核”
  2. 重新校验失败时清除 `code_validated`，停留在当前阶段并要求重新执行门2
  3. 更新当前阶段负责的 `traceability.md` 列；bugfix 在主题执行和整体验收阶段追加缺陷状态。更新失败时不推进
  4. 标记 `user_confirmed=True`，stage 状态改 `done`
  5. 调 `stage.on_advance(project_root)`；spike 清理临时代码并写 journal“spike 清理”
  6. **记录 verification hash**（若 stage 是 acceptance_plan/test_plan/topic_execution/regression_test）
  7. **设置 Architecture Gate Marks**（若 stage 是 code_design/revise_code_design/project_design_init/update_code_design）
  8. **设置 project_design_initialized**（若 stage 是 project_design_init，或 from_scratch 的 spec+code_design 都已确认）
  9. **写入 topics 并登记项目主题历史**（`bugfix` 在 `reproduce`；`from_scratch`、`product_change` 在 `acceptance_plan`）
  10. 推进 `state.current_stage` = 下一 stage（或 `"completed"` 临时中间态，由 done 确认）
  11. 写 journal：门禁用户确认 / 阶段推进 / 追踪表更新 / 缺陷状态更新 / 主题确定 / 架构标记（若适用）
- **stdout 末尾**（非最后 stage）：`下一步：调 workflow discuss 加载 <next_stage> stage 提示词`
- **stdout 末尾**（最后 stage）：`下一步：调 workflow done 标记完成`

### 8.6 `gate spike --skip`（特殊跳过）
- **干啥**：跳过整个 spike stage
- **前置**：当前 `state.current_stage` 必须是 `spike`；用户已经明确决定本次没有需要实际验证的不确定性
- **流程**：
  1. 标记 `state.spike_skipped=True`
  2. 标记 `state.stages.spike.gate.{discussion_complete,code_validated,user_confirmed}=True`（绕过三道门）
  3. 标记 `state.stages.spike.status="done"`
  4. 删除 `.workflow_loop/spike_tmp/` 中可能残留的临时内容
  5. 推进 `current_stage` = 下一 stage
  6. 写 journal：spike 跳过 / 阶段推进，并记录清理路径
- **stdout 末尾**：`下一步：调 workflow discuss 加载 <next_stage> stage 提示词`

### 8.7 `status`
- **干啥**：打印 state + journal 摘要；读取旧版 active 状态时，先迁移到当前阶段顺序并保存
- **stdout 内容**：
  - `workflow_id` / `intent` / `run_status` / `current_stage` / `topics` / `started_at` / `ended_at` / `aborted_at`
  - 各 stage 的 gate 状态（3 道闸 ✓/✗）
  - `architecture.preliminary_done` / `detailed_done`
  - journal 最近 10 条
- **stdout 末尾**：根据当前阶段和门禁状态打印下一条命令

### 8.8 `done`
- **干啥**：将 Run 标为 `completed`，写结束时间
- **前置**：所有 stage 已走完且 `current_stage` 已到可收工状态（末段 `update_code_design` 的 `--confirmed` 推进后，`current_stage="completed"` 临时中间态）
- **流程**：
  1. 标记 `run_status=completed`
  2. 写 `ended_at`（不动 `aborted_at`）
  3. 写 journal：Run 完成
  4. 解除 Active Run Guard，允许之后重新 `start --intent`
- **不**再向用户二次确认"整轮结束"
- **不**删除产物
- **不**在 done 时改写 `bug/index.md` 等文档（缺陷状态由主题执行、回归和整体验收阶段按实际结果更新）
- **stdout 末尾**：`工作流完成。本次 workflow 结束。`

### 8.9 `abort`
- **干啥**：将进行中的 Workflow Run 正式中止
- **前置**：`run_status=active`（对已 `completed`/已 `aborted`/无 state 的调用明确报错，不静默空操作装成功）
- **流程**：
  1. 标记 `run_status=aborted`
  2. 写 `aborted_at`（不动 `ended_at`）
  3. 写 journal：Run 作废
  4. **不**删除已有 Artifact
  5. **不**删除 `state.json`（保留作废快照直至下次 `start` 覆盖）
  6. Active Run Guard 视为无活跃 Run，允许重新 `start --intent`
- **stdout 末尾**：`Run 已作废。可重新调 workflow start --intent <intent> 开新 Run`

### 8.10 `install-project`（由 install.sh 调用，非日常命令）
- **干啥**：把运行骨架安装到当前项目根
- **前置**：由 `install.sh` 在用户确认目录后调用；用户不直接调
- **流程**：
  1. 检查 `.workflow_loop/project.json` 是否存在且 `installer_version` 一致 → Repeat Installation 直接退出，零修改
  2. 创建 `.workflow_loop/`
  3. 用 `importlib.resources` 把 `workflow_loop.data.Template_Repository`、`workflow_loop.data.Standardized_Repository` 解包到 `.workflow_loop/`
  4. 写 `AGENTS.md`（最小工作流契约 + 核心表达要求；存在则整份覆盖，不询问、不合并、不备份）
  5. 写 `.workflow_loop/project.json`（`installer_version`、`installed_at`、`project_design_initialized=false`）
  6. 不创建 `state.json`（那是 `start --intent` 的事）
  7. 不预建空产物目录（`spec/`/`plan/` 等首次写产物时才建）
- **stdout 末尾**：`项目安装完成。启动 Codex/OpenCode 并提出需求即可。`

---

## 9. 架构文档双阶段

### 9.1 同一文件两阶段
`spec/architecture_code_design.md` 是固定产物。两阶段完成度，不是两个无关文件：

1. **初步架构**（前期设计）：路径前段产出或补齐，服务计划与实施前的共同理解
   - `from_scratch` 在 `code_design` stage 产出
   - `product_change` 在 `revise_code_design` stage 产出
   - `bugfix` 在 `project_design_init` stage 产出（若 `project_design_initialized=false`）
2. **详细架构**（最终全量回归和整体验收通过后）：`overall_acceptance` 之后强制更新/写全，反映最终被验证和接受的真实结构
   - 所有意图末段 `update_code_design` stage

### 9.2 Architecture Gate Marks
State Snapshot 中记录架构完成度：

| mark | 何时置 true |
|---|---|
| `architecture.preliminary_done` | 前段架构 stage（`code_design`/`revise_code_design`/`project_design_init`）`--confirmed` 后 |
| `architecture.detailed_done` | 末段 `update_code_design` `--confirmed` 后 |

文件存在只是必要条件；**不得**因 `spec/architecture_code_design.md` 已存在而自动跳过详细架构收尾。

### 9.3 路由链接
- `spec/product.md` 里始终有 markdown 链接 `[code_design](./architecture_code_design.md)`
- `from_scratch`：`spec` 阶段先写链接，紧接着的 `code_design` 阶段创建初步文档；末段 `update_code_design` 再按最终代码、测试和验收结果更新
- `product_change`/`bugfix`：链接指向已存在的文件（来自 `project_design_init` 或 `revise_code_design`）

---

## 10. 主题规则

### 10.1 主题是什么
主题是验收计划根据已确认需求拆出的可独立验收结果名称。主题文字本身就是唯一标识，并且在项目历史中不能重复。

### 10.2 何时定
- `from_scratch` 和 `product_change` 在 **`acceptance_plan` stage** 先确认完整主题清单，再写入 `state.topics`
- `bugfix` 在 **`reproduce` stage** 根据每份缺陷修复后必须恢复的用户结果确定主题；一份缺陷记录对应一个主题，验收计划只能复用
- 主题确认时同时写入 `.workflow_loop/project.json` 的 `topic_history`，后续 Workflow Run 不得重复使用
- `start` 不要求主题；`from_scratch`、`product_change` 的 spec、前段架构和 spike 可以尚无主题；`bugfix` 进入 spike 前必须已经有主题

### 10.3 如何复用
- 验收计划、测试计划、主题测试结果和主题验收结果使用同一个主题名称
- 实施计划和实施记录只要求写清关联主题，不强制与主题一一对应
- 修 bug 的验收计划不能新增、改名、拆分或合并缺陷复现阶段确认的主题

### 10.4 主题前的命名规则
- `spec`：`spec/product.md` + `spec/feature_*.md`
- `spike`：`spec/spike_index.md` + `spec/spike_<english-name>.md`；清单项使用 `SP-001` 等编号，文件名使用小写英文和下划线
- `reproduce`：`bug/<YYYY-MM-DD_HHmm-<bug描述>>.md`
- `code_design`/`revise_code_design`/`update_code_design`/`project_design_init`：`spec/architecture_code_design.md`（文档级产出，不属于某个功能主题）

### 10.5 不按主题命名的产物
- `code_design` / `revise_code_design` / `update_code_design` / `project_design_init`：`spec/architecture_code_design.md`
- `reproduce`：使用 bug 描述
- `regression_test`：`qa/final_regression_result.md`
- `overall_acceptance`：`acceptance/overall_result.md`

---

## 11. bug 册

### 11.1 性质
**被动沉淀库**，不是主动 workflow 的 stage。bug 册记录已解决问题的复现+根因+修复方案，供以后查询。

### 11.2 bug 册结构
```
bug/
  ├─ index.md                       # 索引表（自动维护）
  └─ YYYY-MM-DD_HHmm-<bug描述>.md   # 单个 bug 记录
```

`index.md` 至少包含：
```markdown
| Bug 记录 | 现象 | 根因 | 状态 |
|---|---|---|---|
| [缺陷名称](./2026-07-24_1200-缺陷描述.md) | 一句话现象 | 一句话根因 | 根因已确认 |
```

### 11.3 何时沉淀
- bugfix 的 `reproduce` stage 已经写 `bug/<...>.md` + 更新 `bug/index.md`（在 stage 内门禁产出，不是 done 时偷偷沉淀）
- `topic_execution` 通过后写“主题验收通过，待全量回归”；最终回归失败后写“回归失败，重新处理中”；整体验收通过后写“已修复并验收”
- `done` 命令**不**改写 `bug/index.md`；缺陷状态由主题执行、回归和整体验收阶段按实际结果更新。

### 11.4 查询用法
任何人遇到重复问题时，先查 `bug/index.md`，有记录直接用，不用重新走 bugfix 流程。

---

## 12. 扩展点

### 12.1 加新 stage
加一个 `StageStrategy` 子类，实现所有 abstract 方法；在 `path_composer.py` 的对应 intent 路径列表里插入。零改动 `cli.py`。

### 12.2 加新 intent
在 `path_composer.py` 的 `build_stage_path` 函数里加分支；在 `start --intent` 的 choices 里加新值。

### 12.3 加新门禁类型
重写 `StageStrategy.code_validate()`。默认查文件存在，重写后可查内容结构、查文件大小、查 git 状态等。

### 12.4 加 on_advance 行为
重写 `StageStrategy.on_advance()`。默认 no-op，重写后可做清理、通知、迁移等。

### 12.5 加 lifecycle hooks
`state.meta` 留口子，后面加 `after_advance` / `after_discuss` / `after_gate` 等 hook 配置。

### 12.6 加自动路由（ProjectCharDetector，TBD）
留一个 `ProjectCharDetector` 接口，默认实现 = "AI 显式传 `--intent`"。后面加自动检测（看代码量、看 README 等），加一个新实现即可。

---

## 13. 第一版不做

| 不做的 | 理由 |
|---|---|
| 多 Run 并行 | `state.json` 单文件单 Run，足够第一版 |
| MCP server 包装 | 第一版直接 CLI，MCP 是 later |
| 自动路由（ProjectCharDetector） | 留口子，默认 AI 显式传 `--intent` |
| `overview` 命令 | 文档百科非开工阻塞；需要时后置（CONTEXT.md "Legacy CLI Removal"） |
| journal 的查询/grep 命令 | 第一版只做追加 + status 摘要 |
| bug 册的查询命令 | 第一版只做沉淀 |
| 所有阶段都做统一的文档语义校验 | 第一版只检查能够稳定判断的内容；`spec` 和 `revise_code_design` 检查本阶段文件变化，`project_design_init` 检查调查证据和三类内容变化，`reproduce` 检查复现与根因固定字段，`spike` 检查清单、八章、结果一致性、阻塞状态和设计哈希；证据真实性仍由用户确认 |
| 抽象词自动封禁 | 词本身不能判断内容是否清楚；全局规范要求 AI 自查并由用户确认 |
| 安装时静默安装 + 直接开跑 | 安装必须独立完成，再由 AI 调 `start` |
| 升级流程 | 第一版不做，升级流程后置单独设计 |
| 项目安装的 `attach` 子命令 | 用官方安装脚本，不留 attach 入口 |

---

## 14. 确认清单

设计到此，以下全部钉死：

- [x] 第一性原理 + 根解法 + 第一版验证假设（第 1 节）
- [x] 部署形态：全局 CLI `workflow` + 官方安装脚本 + `src/workflow_loop/` 包布局 + Template/Standardized 随包资源 + AGENTS.md 最小契约（第 2 节）
- [x] 数据模型：state.json 全集 schema + `.workflow_loop/project.json` + journal.jsonl + state vs journal vs project.json 分离原则 + State File Lifecycle（第 3 节）
- [x] 入口与意图模型：`start` 两种模式 + 三种 Work Intent + Active Run Guard + Clean Confirm 两段式 + Clean Scope + Project Design Init Skip（第 4 节）
- [x] Stage Path 拼法：PathComposer `build_stage_path` + 三种意图路径表 + spike 可选 + 路径存储与复用（第 5 节）
- [x] Stage 7 步模式 + 3 道闸 + Verification Invalidation（哈希对象 + 清零检查 + 失效链）+ StageStrategy ABC + stdout 驱动原则（第 6 节）
- [x] 全局写作规范：AGENTS.md 核心规则 + discuss 每阶段完整加载 + 正式文档/聊天分级审查 + 不做关键词封禁（第 6.7 节）
- [x] 产品设计文档规则：背景与目标依据、用户与执行角色区分、产品规则归位、修 bug 场景边界（第 7.1、7.4 节）
- [x] 穿刺规则：真实场景、用户决定执行项、清单与详情绑定、结构化门2、设计基线哈希、`bugfix` 边界和临时内容清理（第 3、5、6、7.3、8.6、10 节）
- [x] Stage 详典：顶层阶段的角色、提示词、规范、产物和门禁边界（第 7 节）
- [x] 命令清单：start + discuss + gate（三种 flag + spike --skip）+ status + done + abort + install-project + 每条 stdout 末尾的"下一步"（第 8 节）
- [x] 架构文档双阶段：preliminary_done / detailed_done + 同一文件两阶段 + `update_code_design` 末环强制（第 9 节）
- [x] 主题规则：从零开发和修改产品在 acceptance_plan 确定主题，修 bug 在 reproduce 确定主题；项目历史唯一，后续计划与执行复用（第 10 节）
- [x] bug 册：被动沉淀 + reproduce stage 内产出 + done 不改写 bug/index.md（第 11 节）
- [x] 扩展点：加 stage / 加 intent / 加门禁类型 / 加 on_advance / 加 hooks / 加自动路由（第 12 节）
- [x] 第一版不做清单（第 13 节）

**与旧 spike 的差异**：
- 入口：`python3 workflow.py start --entry <4场景>` → `workflow start --intent <3意图>`
- 状态：`entry/scenario` + `current_stage=completed` → `intent/run_status/ended_at/aborted_at` + `architecture.{preliminary_done,detailed_done}` + `verification.*_hash`
- 项目级：无 → `.workflow_loop/project.json`（`project_design_initialized`/`installer_version`/`installed_at`）
- 部署：项目根 `workflow.py` 单文件 → 全局 CLI `workflow` + `src/workflow_loop/` 包布局 + `install.sh`
- 路径编排：`SCENARIO_REGISTRY` + 4 个 `ScenarioStrategy` → `build_stage_path(intent, project_root)` 函数
- Stage 命名：`acceptance`/`qa` 混用 + `generate_code_design` → 拆 `acceptance_plan`/`acceptance` 和 `test_plan`/`test`；废弃 `generate_code_design`，统一 `update_code_design`；新增 `project_design_init`/`revise_code_design`
- 命令：无 `abort` + `done` 二次确认 → 新增 `abort` + `done` 不二次确认
- 机制：无 Verification Invalidation + 无 Architecture Gate Marks + 无 Clean Confirm + 无 Optional Spike --skip → 全部新增
- 穿刺：只检查任意 `spike_*.md` → 当前工作流清单 + 每项结论 + 固定状态 + 阻塞检查 + 产品/代码设计修改哈希校验

**当前状态**：穿刺流程代码、提示词、产品文档和代码设计已经同步；完整测试已通过。当前工作流停在 `spike` 第二道门之前，穿刺结论通过代码校验后还需要用户完成第三道门确认。
