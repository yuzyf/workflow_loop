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
  │   ├─ test_active_run_guard.py
  │   ├─ test_clean_confirm.py
  │   ├─ test_installer.py
  │   └─ test_commands.py
  ├─ .workflow_loop/                      # 本仓库自己作为被管理项目的运行时骨架
  │   ├─ project.json                     # 项目级字段（installer_version, project_design_initialized）
  │   ├─ state.json                       # 当前 Run 快照（开工后才写）
  │   ├─ journal.jsonl                    # 历史记录（开工后才写）
  │   ├─ Template_Repository/             # 从包内 data/ 复制（项目可定制）
  │   ├─ Standardized_Repository/         # 从包内 data/ 复制（项目可定制）
  │   │   └─ global/document_writing.md   # discuss 每次完整加载
  │   └─ spike_tmp/                       # spike stage 的 throwaway 代码
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
  "clean_confirmed": false,
  "spike_skipped": false,
  "stage_path": [
    "spec", "code_design", "spike", "plan",
    "acceptance_plan", "test_plan", "impl",
    "test", "acceptance", "update_code_design"
  ],
  "stages": {
    "<name>": {
      "status": "pending",
      "artifact_paths": ["..."],
      "artifact_produced_at": null,
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
    "test_result_hash": null
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
| `topic` | str\|null | 主题字符串；`plan`/`fix_plan` stage 的 `--confirmed` 时写入 |
| `clean_confirmed` | bool | 从零做清场确认标记；`workflow start --intent from_scratch --confirm-clean` 时置 true |
| `spike_skipped` | bool | spike 跳过标记；`gate spike --skip` 时置 true |
| `stage_path` | list[str] | PathComposer 在 start 时解析出的完整 stage 名顺序；固定不再变 |
| `stages` | dict[str, StageState] | 每个 stage 的细粒度状态 |
| `architecture.preliminary_done` | bool | 初步架构完成标记；前段架构 stage `--confirmed` 后置 true |
| `architecture.detailed_done` | bool | 详细架构完成标记；末段 `update_code_design` `--confirmed` 后置 true |
| `verification.*_hash` | str\|null | 上游内容哈希；`gate --confirmed` 时记录，下游 `gate`（无 flag）时检查 |
| `meta` | dict | 自由扩展口子（hooks 等后面用） |

**StageState 字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | str | `pending` / `in_progress` / `gated` / `done` |
| `artifact_paths` | list[str] | 期望产出文件路径列表 |
| `artifact_produced_at` | str\|null | 产出文件首次出现时间戳 |
| `gate.discussion_complete` | bool | 第 1 道闸（讨论完毕） |
| `gate.code_validated` | bool | 第 2 道闸（代码校验通过） |
| `gate.user_confirmed` | bool | 第 3 道闸（用户确认） |

**state 不存的**：
- 不存 journal（历史在 journal.jsonl）
- 不存讨论内容（讨论在 AI 和用户之间，不落 workflow）
- 不存 artifact 内容（只存路径，不存文件内容）
- 不存 `project_design_initialized`（项目级字段，落 `project.json`，跨 Run 持久，不被新 Run 覆盖）
- 不存 `installer_version`（同上，落 `project.json`）

### 3.2 .workflow_loop/project.json（项目级持久字段）

跨 Run 持久，不被新 Run 覆盖：

```json
{
  "installer_version": "0.1.0",
  "installed_at": "2026-07-20T10:00:00Z",
  "project_design_initialized": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `installer_version` | str | 安装时写入；用于重复安装保护判断 |
| `installed_at` | str | 安装时间 ISO 8601 UTC |
| `project_design_initialized` | bool | 项目设计架构初始化标记；安装时 `false`；`project_design_init` stage `--confirmed` 后置 `true`；`from_scratch` 在 `spec` + `code_design` 都 `--confirmed` 后置 `true` |

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
| 产出文件检查 | `gate`（无 flag）检查时 | `stage`, `artifact`, `exists` |
| 门禁代码校验 | `gate`（无 flag）时 | `stage`, `passed`, `details` |
| 验证失效 | 上游 hash 变化清零下游时 | `from_stage`, `to_stage`, `reason` |
| 门禁用户确认 | `gate --confirmed` 时 | `stage`, `passed` |
| 阶段推进 | `--confirmed` 推进时 | `from`, `to` |
| 主题确定 | `plan`/`fix_plan` `--confirmed` 时 | `topic` |
| 架构标记 | preliminary/detailed 设置时 | `mark`, `stage` |
| spike 跳过 | `gate spike --skip` 时 | `cleaned_paths` |
| spike 清理 | spike `on_advance` 时 | `cleaned_paths` |
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
- 项目级字段独立：`project_design_initialized` 不应被新 Run 覆盖

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
- **删除**（仅项目根产物侧）：`spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 下由 workflow 约定写出的设计/过程文档
- **不删除**：`.workflow_loop/Template_Repository/` 与 `Standardized_Repository/` 全部内容；`.workflow_loop/project.json` 本身（只更新初始化字段）；源代码、`.git`、与设计产物无关的项目文件；`.workflow_loop/` 运行时骨架本身

**Clean Detect List**（监测清单）：
- 监测：项目根下 `spec/`、`plan/`、`acceptance/`、`qa/`、`impl/`、`bug/` 中**已存在且含文件**的路径
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
| `from_scratch` | 总是 | 清场确认 → `spec` → `code_design`（初步）→ `spike`（可选）→ `plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design` |
| `product_change` | `project_design_initialized=false` | `project_design_init` → `spec` → `revise_code_design` → `spike`（可选）→ `plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design` |
| `product_change` | `project_design_initialized=true` | `spec` → `revise_code_design` → `spike`（可选）→ `plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design` |
| `bugfix` | `project_design_initialized=false` | `project_design_init` → `reproduce` → `fix_plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design` |
| `bugfix` | `project_design_initialized=true` | `reproduce` → `fix_plan` → `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design` |

**清场确认**不是 stage，是 `from_scratch` 在 `start --intent` 时的前置动作（见 4.5）。

**共享后半截**：所有意图在 `plan`/`fix_plan` 之后都是 `acceptance_plan` → `test_plan` → `impl` → `test` → `acceptance` → `update_code_design`。

### 5.3 Stage 命名规则（CONTEXT.md 强制）

- `from_scratch` 的前段初步架构 stage 名 = `code_design`
- `product_change` 的设计期架构修订 stage 名 = `revise_code_design`
- 存量项目首次初始化 stage 名 = `project_design_init`
- **所有意图**末段详细架构收尾 stage 名 = `update_code_design`
- 废弃 `generate_code_design`（初步阶段已可能创建同文件，末环不是"首次生成"语义）
- `acceptance` 拆为 `acceptance_plan`（制定）+ `acceptance`（执行）
- `qa` 拆为 `test_plan`（制定）+ `test`（执行）
- 任何意图不得跳过末段 `update_code_design`

### 5.4 Optional Spike
- `spike` 在 `from_scratch` / `product_change` 路径上**默认在路径中**
- 用户确认不需要穿刺后，通过显式门禁动作跳过：`workflow gate spike --skip`
- state 记 `spike_skipped=true`、journal 记跳过并推进下一 Stage
- 不要求 throwaway 与完整结论文档
- 不能靠 AI 自觉删 stage；不在 `start` 时默认从路径抹掉 spike
- `spike` `--skip` 不取消其它 stage 的三道门，也不合并门禁

### 5.5 路径存储与复用
- `start --intent` 时调一次 PathComposer，结果存入 `state.stage_path`（list[str]）
- 后续命令（discuss/gate）读 `state.stage_path` 找当前 stage 对应的 Stage 策略类
- 不在每次命令调用时重新跑 PathComposer（PathComposer 看清场/`project_design_initialized` 等条件，这些在 start 时就固定）

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
     → （spike stage 特殊：AI 写 throwaway 代码验证风险，见第 7.3 节）
     → 可重复 discuss：同一 stage 在 Run 仍 active 且尚未整轮结束前，允许多次 discuss
     → 重复 discuss 不自动清零已通过的门禁

[S3] 讨论完毕门禁（第 1 道闸）
     → 用户确认"讨论完毕"
     → AI 调 `workflow gate <stage> --discuss-done`
     → workflow 标记 state.stages.<stage>.gate.discussion_complete = True
     → 写 journal: 门禁讨论完毕 passed

[S4] AI 写产出文件
     → 可能是多个文件（spec: product.md + feature_*.md）
     → 主题在 plan/fix_plan 定下后，后面 stage 复用主题做文件名（见第 10 节）
     → spike stage 特殊：throwaway 代码进 .workflow_loop/spike_tmp/，结论文档进 spec/

[S5] 代码校验门禁（第 2 道闸）
     → AI 调 `workflow gate <stage>`（无 flag）
     → 前置：discussion_complete=True
     → **Verification Invalidation 检查**（见 6.4）：进入下游 stage 的第 2 道闸时，先重算上游 hash 比对，不一致则清零本 stage 的所有 gate
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
     → 前置：code_validated=True
     → 标记 user_confirmed = True
     → 调 stage.on_advance(project_root)（spike 清理 throwaway 代码）
     → **记录上游 hash**（见 6.4）：本 stage 是 impl/test_plan/acceptance_plan/test 时，记录对应 verification hash
     → **设置 Architecture Gate Marks**（见第 9 节）：本 stage 是 code_design/revise_code_design/project_design_init/update_code_design 时，置对应 mark
     → **设置 project_design_initialized**（见 4.4）：本 stage 是 project_design_init 或 from_scratch 的 spec+code_design 都确认后
     → 推进 state.current_stage = 下一 stage
     → 写 journal: 门禁用户确认 passed / 阶段推进 <stage>→<next> / 主题确定（若 plan/fix_plan）/ 架构标记（若适用）
```

### 6.2 3 道闸（顺序硬性，CONTEXT.md "Gate Policy"）

| 闸 | 字段 | 命令 | 前置条件 | 不满足时报错 |
|---|---|---|---|---|
| 1 讨论完毕 | `discussion_complete` | `gate <stage> --discuss-done` | stage 已 discuss | "请先调 discuss 加载提示词" |
| 2 代码校验 | `code_validated` | `gate <stage>` | `discussion_complete=True` | "请先确认讨论完毕" |
| 3 用户确认 | `user_confirmed` | `gate <stage> --confirmed` | `code_validated=True` | "请先跑代码校验" |

**跳步抛错**：直接调 `gate --confirmed` 而没跑前两道 → 报错并提示正确顺序。

**门禁策略第一版**：每个正式 Stage 保留三道门、顺序硬性。`test`（测试执行）与 `acceptance`（验收执行）是强制 Stage，不提供 `--skip`；自动测试不可用时可执行人工测试并记录证据。AI 不得自动替用户验收。

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
    
    def on_advance(self, project_root: str) -> None:
        """stage 推进时的钩子。默认 no-op。
        spike stage 重写这个清理 throwaway 代码。"""
        pass
    
    @abstractmethod
    def instruction(self) -> str: ...
```

### 6.4 Verification Invalidation（验证结果自动失效）

**核心机制**：通过状态只对绑定的上游内容有效。上游变化时下游门禁清零。

**哈希对象**（SHA256）：

| hash 字段 | 哈希对象 | 记录时机 |
|---|---|---|
| `impl_hash` | `impl/<topic>.md` 内容 + `git status --porcelain` + `git diff --stat` 输出（代码修改快照）；非 git 仓库退化为指定目录下代码文件 mtime+size 快照 | `gate impl --confirmed` 时 |
| `test_plan_hash` | `qa/<topic>_plan.md` 内容 | `gate test_plan --confirmed` 时 |
| `acceptance_plan_hash` | `acceptance/<topic>_plan.md` 内容 | `gate acceptance_plan --confirmed` 时 |
| `test_result_hash` | `qa/<topic>_result.md` 内容 | `gate test --confirmed` 时 |

**清零检查**：进入下游 stage 的第 2 道闸（`gate` 无 flag）时，先重算上游 hash 比对：

| 进入 stage | 检查上游 | 不一致时清零 |
|---|---|---|
| `test` | `impl_hash`（impl 变了吗）、`test_plan_hash`（test_plan 变了吗） | 清零 `test` 与 `acceptance` 的所有 gate |
| `acceptance` | `test_result_hash`（test 结果变了吗）、`acceptance_plan_hash`（acceptance_plan 变了吗） | 清零 `acceptance` 的所有 gate |
| `acceptance_plan` | `test_plan_hash`（如果 test_plan 已确认） | 清零 `acceptance` 的所有 gate，并把 `test_plan` 的 `code_validated`/`user_confirmed` 退回 false（discussion_complete 保留） |

**失效动作**：写入 State Snapshot（清零对应 stage 的 gate 字段）+ 写 journal（"验证失效"，记录 from_stage/to_stage/reason）。

**实现位置**：`src/workflow_loop/verification.py`。

### 6.5 on_advance() 钩子
- 默认 no-op
- `spike` stage 重写：删除 `.workflow_loop/spike_tmp/` 下所有内容（保留 `spec/spike_*.md` 结论文档）
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
| `code_validate` | 检查 `spec/product.md` 存在 + 至少一个 `spec/feature_*.md` 存在；阶段进入时记录相关文件路径与内容哈希，校验时比较前后变化（证明产物属于本 Run） |
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
| 角色 | 架构文档撰写者（初步） |
| 提示词 | `Template_Repository/code_design/code_design.md` |
| 规范 | `Standardized_Repository/code_design/code_design.md` |
| 产物 | `spec/architecture_code_design.md` |
| `code_validate` | 默认（检查文件存在） |
| `on_advance` | 置 `architecture.preliminary_done=true`；`from_scratch` 中若 `spec` 也已 `--confirmed`，置 `project_design_initialized=true` |
| instruction | "初步架构阶段：产出 spec/architecture_code_design.md（从零做的初步架构设计）" |

**顺序约束**：`from_scratch` 中顺序固定为**先产品设计与功能拆分、后初步架构**（先定做什么，再定怎么搭）。不可因旧文件存在跳过。

### 7.3 spike（可选穿刺）

| 字段 | 值 |
|---|---|
| 角色 | 风险验证者 |
| 提示词 | `Template_Repository/spike/spike.md` |
| 规范 | `Standardized_Repository/spike/spike.md` |
| 产物 | `spec/spike_<临时名>.md`（结论文档）+ throwaway 代码进 `.workflow_loop/spike_tmp/` |
| `code_validate` | 检查 `spec/` 下有 `spike_*.md` 文件存在 |
| `on_advance` | 删除 `.workflow_loop/spike_tmp/` 下所有内容（保留 `spec/spike_*.md`） |
| instruction | "穿刺阶段：问用户哪些功能要穿刺、识别风险、写 throwaway 代码到 .workflow_loop/spike_tmp/、写结论文档 spec/spike_<临时名>.md" |

**特殊跳过**：`workflow gate spike --skip` 跳过整个 spike stage（包括三道门），state 记 `spike_skipped=true`，journal 记跳过并推进下一 Stage。

**throwaway 代码**：不进 git（`.workflow_loop/` 整个或部分 gitignore）；代码目的是验证设计风险，不是产出。

### 7.4 project_design_init（存量项目首次初始化）

| 字段 | 值 |
|---|---|
| 角色 | 存量产品与架构分析师 |
| 提示词 | 同时加载 `Template_Repository/spec/spec.md` + `Template_Repository/code_design/code_design.md` 两组 |
| 规范 | 同时加载 `Standardized_Repository/spec/spec.md` + `Standardized_Repository/code_design/code_design.md` 两组 |
| 产物 | `spec/product.md` + 多个 `spec/feature_<english-name>.md` + `spec/architecture_code_design.md`（一次建立） |
| `code_validate` | 同时校验三类产物都存在 |
| `on_advance` | 置 `project_design_initialized=true` 与 `architecture.preliminary_done=true` |
| instruction | "项目设计架构初始化：根据现有代码及可运行行为一次建立 spec/product.md + spec/feature_*.md + spec/architecture_code_design.md" |

**顺序约束**：该 stage 完成前作废不得写 `project_design_initialized=true`。不拆成彼此可能不一致的"产品反推"+"架构反推"两轮。

**事实边界**：代码和运行结果用于确认产品当前怎样工作，不能单独证明产品当初为什么诞生或某个功能为什么设计；历史背景无法核实时必须询问用户或标记未确认。

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
| `code_validate` | 检查文件存在；bugfix 无结构变化时显式确认"无结构变化"（不省略 stage） |
| `on_advance` | 置 `architecture.detailed_done=true` |
| instruction | "详细架构收尾：写入/更新 spec/architecture_code_design.md，反映最终被验证和接受的真实结构" |

**强制**：所有工作意图在 `test` 通过且最终 `acceptance` 经用户确认之后必须经过 `update_code_design`。从零做、改产品、修 bug 末环同名；不再使用 `generate_code_design`。

### 7.7 plan（计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 计划制定者 |
| 提示词 | `Template_Repository/plan/plan.md` |
| 规范 | `Standardized_Repository/plan/plan.md` |
| 产物 | `plan/<topic>.md` + `plan/index.md`（主题在这里定） |
| `code_validate` | 检查 `plan/index.md` 存在 + 至少一个 `plan/*.md` 文件存在 |
| `on_advance` | 写 `state.topic`（从讨论决定的主题字符串） |
| instruction | "计划阶段：产出 plan/<主题>.md + plan/index.md（主题在这里定下，后面 stage 复用）" |

**主题写入时机**：`gate plan --confirmed` 推进落盘时写 `state.topic`。

### 7.8 fix_plan（修复计划制定，bugfix 专用）

| 字段 | 值 |
|---|---|
| 角色 | 修复计划制定者 |
| 提示词 | `Template_Repository/plan/fix_plan.md` |
| 规范 | `Standardized_Repository/plan/fix_plan.md` |
| 产物 | `plan/<topic>.md` + 更新 `plan/index.md` |
| `code_validate` | 同 plan |
| `on_advance` | 写 `state.topic`（从 bug 反推） |
| instruction | "修复计划阶段：和用户讨论修复方案，产出 plan/<主题>.md + 更新 plan/index.md（主题从 bug 反推）" |

### 7.9 acceptance_plan（验收计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 验收计划制定者 |
| 提示词 | `Template_Repository/qa/acceptance_plan.md` |
| 规范 | `Standardized_Repository/qa/acceptance_plan.md` |
| 产物 | `acceptance/<topic>_plan.md` |
| `code_validate` | 校验文件属于当前 Run、文件名与 `state.topic` 一致、每条验收条件可判定且覆盖本次实施计划 |
| `on_advance` | 记录 `verification.acceptance_plan_hash` |
| instruction | "验收计划阶段：制定什么算完成的验收计划，产出 acceptance/<topic>_plan.md" |

### 7.10 test_plan（测试计划制定）

| 字段 | 值 |
|---|---|
| 角色 | 测试计划制定者 |
| 提示词 | `Template_Repository/qa/test_plan.md` |
| 规范 | `Standardized_Repository/qa/test_plan.md` |
| 产物 | `qa/<topic>_plan.md` + 更新 `qa/index.md` |
| `code_validate` | 校验测试计划属于当前 Run、文件名与 topic 一致、每条验收条件至少被一个测试项或明确人工验收项覆盖 |
| `on_advance` | 记录 `verification.test_plan_hash` |
| instruction | "测试计划阶段：把验收条件转换为可执行测试范围、步骤、回归项、边界与证据要求，产出 qa/<topic>_plan.md" |

### 7.11 impl（实施执行）

| 字段 | 值 |
|---|---|
| 角色 | 实施执行者 |
| 提示词 | `Template_Repository/impl/impl.md` |
| 规范 | `Standardized_Repository/impl/impl.md` |
| 产物 | 实际代码修改 + `impl/<topic>.md` 实施记录 |
| `code_validate` | 校验实施记录与当前 Run/topic 对应，并记录当前代码与实施记录内容哈希 |
| `on_advance` | 记录 `verification.impl_hash`；清零 `test` 与 `acceptance` 的门禁状态（如果之前有） |
| instruction | "实施阶段：执行已确认的实施/修复计划并修改真实代码，产出 impl/<topic>.md 实施记录" |

**注意**：impl 不再承担"再制定一份实施计划"的职责。plan/fix_plan 已经制定计划，impl 执行。

### 7.12 test（测试执行）

| 字段 | 值 |
|---|---|
| 角色 | 测试执行者 |
| 提示词 | `Template_Repository/qa/test.md` |
| 规范 | `Standardized_Repository/qa/test.md` |
| 产物 | `qa/<topic>_result.md` + 更新 `qa/index.md` |
| `code_validate` | 校验结果绑定当前代码/实施记录哈希与测试计划哈希；逐项记录 pass/fail/blocked 及命令、日志、截图或人工测试证据；要求所有必测项通过且无未解决 fail/blocked |
| `on_advance` | 记录 `verification.test_result_hash` |
| instruction | "测试执行阶段：按照 qa/<topic>_plan.md 执行全部必要测试并记录证据，产出 qa/<topic>_result.md" |

**强制**：该 Stage 不提供 `--skip`。失败必须回到 `impl`，修改后旧测试与验收状态失效并重新完整测试。

### 7.13 acceptance（最终验收执行）

| 字段 | 值 |
|---|---|
| 角色 | 验收执行者 |
| 提示词 | `Template_Repository/qa/acceptance.md` |
| 规范 | `Standardized_Repository/qa/acceptance.md` |
| 产物 | `acceptance/<topic>_result.md` |
| `code_validate` | 校验结果绑定验收计划哈希与最新测试结果哈希；逐项给出可复核证据；要求全部适用验收项通过且无阻塞 |
| `on_advance` | no-op（末段 update_code_design 之前） |
| instruction | "最终验收阶段：在测试通过后，按照 acceptance/<topic>_plan.md 执行最终验收，产出 acceptance/<topic>_result.md" |

**强制**：该 Stage 不提供 `--skip`。门3必须由用户明确确认，AI 不得自动代验收。实现不符合计划时回到 `impl`，之后重新走 `test` 与 `acceptance`；验收计划错误、遗漏或不可判定时回到 `acceptance_plan`，修改后重新检查 `test_plan` 并使旧结果失效。

### 7.14 reproduce（bug 复现，bugfix 专用）

| 字段 | 值 |
|---|---|
| 角色 | bug 复现者 |
| 提示词 | `Template_Repository/reproduce/reproduce.md` |
| 规范 | `Standardized_Repository/reproduce/reproduce.md` |
| 产物 | `bug/<YYYY-MM-DD_HHmm-<bug描述>>.md` + 更新 `bug/index.md` |
| `code_validate` | 检查 `bug/` 下有 bug 记录 `.md` 文件（非 index.md） |
| `on_advance` | no-op |
| instruction | "复现阶段：和用户讨论 bug 现象、复现步骤，产出 bug/<YYYY-MM-DD_HHmm-<bug描述>>.md + 更新 bug/index.md" |

**注意**：reproduce 用自己的 bug 描述做文件名，不用主题。

---

## 8. 命令清单

> **设计约束**：每条命令的 stdout 末尾必须以 `───── 下一步：xxx ─────` 结尾（见第 6.6 节）。`status` 是纯只读，无"下一步"。

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
- **前置**：该 stage 已 discuss（journal 里有提示词加载记录）
- **流程**：标记 `gate.discussion_complete = True`；写 journal
- **stdout 末尾**：`下一步：写产出文件 <artifact_paths>。写完调 workflow gate <stage>`

### 8.4 `gate <stage>`（无 flag，第 2 道闸代码校验）
- **前置**：`discussion_complete=True`
- **Verification Invalidation 检查**：进入下游 stage 的第 2 道闸时，先重算上游 hash 比对，不一致则清零本 stage 的所有 gate，写 journal "验证失效"，提示用户重新写产出
- **流程**：
  1. 跑 `stage.code_validate(project_root)`
  2. 检查产出文件是否存在（写 journal: 产出文件检查）
  3. 失败 → 打印"产出文件未就绪"，写 journal: 门禁代码校验 failed
  4. 成功 → 标记 `code_validated=True` + `artifact_produced_at`，打印"请和用户确认已写完"
- **stdout 末尾**（通过）：`下一步：问用户"<stage> 写完了？"，用户确认后调 workflow gate <stage> --confirmed`
- **stdout 末尾**（失败）：`下一步：产出文件未就绪，补完后再调 workflow gate <stage>`

### 8.5 `gate <stage> --confirmed`（第 3 道闸用户确认 + 推进）
- **前置**：`code_validated=True`
- **流程**：
  1. 标记 `user_confirmed=True`，stage 状态改 `done`
  2. 调 `stage.on_advance(project_root)`（spike 清理 throwaway 代码）
  3. **记录 verification hash**（若 stage 是 impl/test_plan/acceptance_plan/test）
  4. **设置 Architecture Gate Marks**（若 stage 是 code_design/revise_code_design/project_design_init/update_code_design）
  5. **设置 project_design_initialized**（若 stage 是 project_design_init，或 from_scratch 的 spec+code_design 都已确认）
  6. **写入 topic**（若 stage 是 plan/fix_plan）
  7. 推进 `state.current_stage` = 下一 stage（或 `"completed"` 临时中间态，由 done 确认）
  8. 写 journal：门禁用户确认 / 阶段推进 / 主题确定 / 架构标记（若适用）
- **stdout 末尾**（非最后 stage）：`下一步：调 workflow discuss 加载 <next_stage> stage 提示词`
- **stdout 末尾**（最后 stage）：`下一步：调 workflow done 标记完成`

### 8.6 `gate spike --skip`（特殊跳过）
- **干啥**：跳过整个 spike stage
- **流程**：
  1. 标记 `state.spike_skipped=True`
  2. 标记 `state.stages.spike.gate.{discussion_complete,code_validated,user_confirmed}=True`（绕过三道门）
  3. 标记 `state.stages.spike.status="done"`
  4. 推进 `current_stage` = 下一 stage
  5. 写 journal：spike 跳过 / 阶段推进
- **stdout 末尾**：`下一步：调 workflow discuss 加载 <next_stage> stage 提示词`

### 8.7 `status`
- **干啥**：打印 state + journal 摘要。纯只读，无副作用
- **stdout 内容**：
  - `workflow_id` / `intent` / `run_status` / `current_stage` / `topic` / `started_at` / `ended_at` / `aborted_at`
  - 各 stage 的 gate 状态（3 道闸 ✓/✗）
  - `architecture.preliminary_done` / `detailed_done`
  - journal 最近 10 条
- **stdout 末尾**：无（纯只读命令，不驱动下一步；打印友好提示"按之前命令打印的下一步继续"）

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
- **不**在 done 时改写 `bug/index.md` 等文档（bug 类产物以 reproduce 等路径上 Stage 的门禁产出为准）
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
2. **详细架构**（代码通过测试与最终验收后）：`acceptance` 之后强制更新/写全，反映最终被验证和接受的真实结构
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
- `from_scratch`：链接先指向不存在的文件，末段 `update_code_design` stage 才创建/更新该文件
- `product_change`/`bugfix`：链接指向已存在的文件（来自 `project_design_init` 或 `revise_code_design`）

---

## 10. 主题规则

### 10.1 主题是什么
主题 = 文件名里的描述性标题。文件名格式：`<folder>/<YYYY-MM-DD_HHmm-<topic>>.md`。

例：`plan/2026-07-20_1438-用户认证系统.md`、`acceptance/2026-07-20_1438-用户认证系统_result.md`、`qa/2026-07-20_1438-用户认证系统_plan.md`

### 10.2 何时定
- `from_scratch` / `product_change`：**`plan` stage** `--confirmed` 时定（写 `state.topic`）
- `bugfix`：**`fix_plan` stage** `--confirmed` 时定

`start` 不强制 `--topic`；spec / reproduce / 前段架构等可以尚无 topic。

### 10.3 如何复用
- `plan`/`fix_plan` 之后的 stage 强制复用 `state.topic` 做文件名
- 日期时间用 workflow 启动时间（不是 stage 时间），保证整个 workflow 的文件名时间一致

### 10.4 主题前的命名规则
- `spec`：`spec/product.md` + `spec/feature_*.md`
- `spike`：`spec/spike_<临时名>.md`
- `reproduce`：`bug/<YYYY-MM-DD_HHmm-<bug描述>>.md`
- `code_design`/`revise_code_design`/`update_code_design`/`project_design_init`：`spec/architecture_code_design.md`（文档级产出，不属于某个功能主题）

### 10.5 不需要主题的 stage
- `code_design` / `revise_code_design` / `update_code_design` / `project_design_init`：产出 `spec/architecture_code_design.md`
- `reproduce`：用 bug 描述做文件名

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

`index.md` 结构：
```markdown
| 日期 | 主题 | 根因 | 修复方案 | 状态 |
|---|---|---|---|---|
| 2026-07-20 | 用户认证系统 | ... | ... | 已修复 |
```

### 11.3 何时沉淀
- bugfix 的 `reproduce` stage 已经写 `bug/<...>.md` + 更新 `bug/index.md`（在 stage 内门禁产出，不是 done 时偷偷沉淀）
- `done` 命令**不**改写 `bug/index.md`（CONTEXT.md "Done Command" 明确）

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
| 内容结构校验 | 只查文件存在 + 内容哈希，内容结构归 Standardized_Repository 管 |
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
- [x] Stage 详典：14 个 stage 的角色/提示词/规范/产物/`code_validate`/`on_advance`/instruction（第 7 节）
- [x] 命令清单：start + discuss + gate（三种 flag + spike --skip）+ status + done + abort + install-project + 每条 stdout 末尾的"下一步"（第 8 节）
- [x] 架构文档双阶段：preliminary_done / detailed_done + 同一文件两阶段 + `update_code_design` 末环强制（第 9 节）
- [x] 主题规则：plan/fix_plan `--confirmed` 时写入 + 后续 stage 复用 + 文件名格式（第 10 节）
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

**等待用户审查。审查通过后开始改代码：搭包布局 → 自下而上写代码 → 写测试 → install.sh → 验证。**
