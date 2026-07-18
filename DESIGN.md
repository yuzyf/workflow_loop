# workflow_loop 穿刺设计文档

> **目的**：用第一性原理描述用户的完整需求，作为穿刺实现的唯一设计真相。
> **读者**：用户（审查）+ AI（实现时参考）+ 未来维护者。
> **原则**：MECE（互斥且完备），不省略任何步骤。

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
- 代码是流程的**唯一真相**，`agent.md` 只是告诉 AI "去调代码"

对比 Trellis 的 hook 注入方式（每轮注入状态提示词），本设计把强制力放在门禁上：AI 即使在脑子里漂移，也无法跳过门禁推进到下一 stage。关卡比唠叨靠谱。

### 1.3 穿刺要验证的假设
`agent.md 契约 + Python 代码 workflow` 这个组合，能让 AI 被代码关卡约束着走完整个工作流（从 spec 到 done）。

**穿刺本身也是 throwaway**：参考 Matt Pocock 的 prototype skill，用一次性实现验证设计选择是否成立。

---

## 2. 部署形态

### 2.1 语言：Python
理由（按重要性排）：
1. **零配置 shell 可跑**：macOS 自带 python3，`python3 workflow.py` 直接跑，无 package.json/node_modules/tsconfig
2. **AI 肌肉记忆**：`python3 xxx.py` 是 AI 写 bash 时的 canonical 模式
3. **训练数据密度**：Airflow/Prefect/Temporal 等 workflow engine 范式海量，AI 一写就掉进坑里
4. **策略模式表达力**：ABC + Protocol + dataclass，干净
5. **REPL/自省**：`python3 -i` 可调试

否决的语言：
- TS：需 runtime + package.json，穿刺摩擦大
- Go：多文件需 go.mod，破坏零配置
- Rust：编译周期慢
- Bash：策略模式表达丑，无数据结构

### 2.2 调用方式：CLI 子命令
AI 通过 shell 调用 `python3 workflow.py <command> [args]`。每次调用是一个**新进程**，读 state.json → 干一件事 → 写 state.json + 追加 journal.jsonl → 打印下一步指令到 stdout → 退出。

AI 读 stdout 知道下一步干啥。`git` 模型：有状态 CLI、状态在 `.workflow_loop/`、每条命令 mutate state。

### 2.3 AI 客户端：opencode / codex
- 客户端无关：契约在 `agent.md` 里自包含
- 不依赖任何客户端的特殊行为（如自动读 AGENTS.md）
- agent.md 自己说清"调 `python3 workflow.py xxx` 遵守流程"

### 2.4 文件夹结构

```
workflow_loop_spike/
  ├─ agent.md                        # 契约：告诉 AI 怎么调代码
  ├─ workflow.py                     # CLI 入口 + 命令 dispatch
  ├─ state.py                         # state.json 读写
  ├─ journal.py                       # journal.jsonl 追加
  ├─ role_doc.py                      # 文档概览硬编码（stage → artifact 映射）
  ├─ DESIGN.md                        # 本文档
  ├─ strategies/
  │   ├─ __init__.py
  │   ├─ base.py                      # ScenarioStrategy + StageStrategy 两个 ABC
  │   ├─ stages.py                    # 所有 stage 策略实现
  │   └─ scenarios.py                 # 4 个 scenario 策略
  └─ .workflow_loop/                 # 运行时状态目录（被管理的项目里）
      ├─ state.json                   # 当前快照
      ├─ journal.jsonl                # 历史记录
      ├─ Template_Repository/        # 提示词模板（.md）
      ├─ Standardized_Repository/    # 规范词（.md）
      └─ spike_tmp/                   # spike stage 的 throwaway 代码
```

**注意**：穿刺文件夹自身既是代码库，又是被 workflow_loop 管理的示例项目（agent.md + .workflow_loop/ 都在里面）。穿刺不是文件夹结构本身，穿刺是验证"代码化 workflow 能不能让 AI 走通流程"这个设计选择。

---

## 3. 数据模型

### 3.1 state.json（当前快照）

workflow.py 每次调用都是新进程，state 必须 persist 到磁盘。state 跟着**被管理的项目**走（不是跟着 workflow.py 走）。

```json
{
  "workflow_id": "2026-07-16-1438-new-project",
  "entry": "new_project",
  "scenario": "new_project",
  "current_stage": "spec",
  "topic": null,
  "started_at": "2026-07-16T14:38:00Z",
  "completed_at": null,
  "stages": {
    "spec": {
      "status": "in_progress",
      "artifact_paths": ["spec/product.md", "spec/功能*.md"],
      "artifact_produced_at": null,
      "gate": {
        "discussion_complete": false,
        "code_validated": false,
        "user_confirmed": false
      }
    },
    "spike": { "status": "pending", "artifact_paths": ["spec/spike_<临时名>.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} },
    "plan": { "status": "pending", "artifact_paths": ["plan/<主题>.md", "plan/index.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} },
    "acceptance": { "status": "pending", "artifact_paths": ["acceptance/<主题>.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} },
    "qa": { "status": "pending", "artifact_paths": ["qa/<主题>.md", "qa/index.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} },
    "impl": { "status": "pending", "artifact_paths": ["impl/<主题>.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} },
    "generate_code_design": { "status": "pending", "artifact_paths": ["spec/architecture_code_design.md"], "artifact_produced_at": null, "gate": {"discussion_complete": false, "code_validated": false, "user_confirmed": false} }
  },
  "meta": {
    "hooks": {}
  }
}
```

**字段说明**：
- `workflow_id`：启动时生成，`YYYY-MM-DD-HHmm-<entry>` 格式
- `entry`：入口策略名（`new_project` / `existing_no_workflow` / `bugfix` / `product_mod`）
- `scenario`：场景策略名（穿刺中和 entry 相同）
- `current_stage`：当前 stage 名（`spec` / `spike` / `plan` / `acceptance` / `qa` / `impl` / `generate_code_design` / `update_code_design` / `code_design` / `reproduce` / `fix_plan` / `requirement` / `product_update` / `feature_split` / `completed`）
- `topic`：主题字符串，**在 plan/fix_plan stage 定下后写入**，之前的 stage 为 null
- `started_at` / `completed_at`：ISO 8601 UTC
- `stages.<name>`：每个 stage 的细粒度状态
  - `status`：`pending`（没开始）→ `in_progress`（AI 在做）→ `gated`（等门禁）→ `done`（过了门禁）
  - `artifact_paths`：期望产出的文件路径列表（可能多个，如 spec 的 product.md + 功能*.md）
  - `artifact_produced_at`：产出文件首次出现的 timestamp
  - `gate.discussion_complete`：第 1 道闸（讨论完毕）
  - `gate.code_validated`：第 2 道闸（代码校验通过）
  - `gate.user_confirmed`：第 3 道闸（用户确认）
- `meta.hooks`：lifecycle hooks 口子（穿刺为空，留扩展）

**state 不存的**：
- 不存 journal（历史在 journal.jsonl）
- 不存 session 指针（穿刺单窗口，不需要）
- 不存讨论内容（讨论在 AI 和用户之间，不落 workflow.py）
- 不存 artifact 内容（只存路径，不存文件内容）

### 3.2 journal.jsonl（历史记录）

append-only，每条一行 JSON。记录 workflow.py 发生的每个动作。

**通用字段**（每条都有）：
- `ts`：ISO 8601 UTC 时间戳
- `action`：动作类型（受控词表，穿刺用中文）
- `actor`：`ai` / `user` / `workflow.py`

**动作特定字段**：根据 action 不同带不同 payload。

**穿刺的 action 词表**（暂定，后面重新设计）：

| action | 何时记 | 额外字段 |
|---|---|---|
| 工作流启动 | `start` 初始化时 | `workflow_id`, `entry` |
| 场景进入 | scenario 实例化时 | `scenario` |
| 文档概览加载 | `overview` 命令时 | |
| 场景对齐 | `align` 命令确定 entry 时 | `entry` |
| 提示词加载 | `discuss` 加载提示词时 | `stage`, `prompt_doc`, `standard_doc` |
| 角色文档加载 | `discuss` 加载角色定义时 | `stage` |
| 门禁讨论完毕 | `gate --discuss-done` 时 | `stage`, `passed` |
| 产出文件检查 | workflow.py 检查文件存在时 | `stage`, `artifact`, `exists` |
| 门禁代码校验 | `gate`（无 flag）时 | `stage`, `passed`, `details` |
| 门禁用户确认 | `gate --confirmed` 时 | `stage`, `passed` |
| 阶段推进 | 双门禁通过推进时 | `from`, `to` |
| 主题确定 | plan/fix_plan stage 定主题时 | `topic` |
| spike 清理 | spike stage on_advance 清理时 | `cleaned_paths` |
| bug 沉淀 | `done` 时若 bugfix | `bug_doc` |
| 工作流完成 | `done` 时 | `workflow_id` |

**journal.jsonl 示例**：
```jsonl
{"ts":"2026-07-16T14:38:00Z","action":"工作流启动","workflow_id":"2026-07-16-1438-new-project","entry":"new_project","actor":"ai"}
{"ts":"2026-07-16T14:38:01Z","action":"场景进入","scenario":"new_project","actor":"workflow.py"}
{"ts":"2026-07-16T14:38:05Z","action":"提示词加载","stage":"spec","prompt_doc":"Template_Repository/spec_prompt.md","standard_doc":"Standardized_Repository/spec_规范.md","actor":"workflow.py"}
{"ts":"2026-07-16T14:38:06Z","action":"角色文档加载","stage":"spec","actor":"workflow.py"}
{"ts":"2026-07-16T14:50:00Z","action":"门禁讨论完毕","stage":"spec","passed":true,"actor":"user"}
{"ts":"2026-07-16T14:55:00Z","action":"产出文件检查","stage":"spec","artifact":"spec/product.md","exists":true,"actor":"workflow.py"}
{"ts":"2026-07-16T14:55:01Z","action":"门禁代码校验","stage":"spec","passed":true,"details":"所有期望文件存在","actor":"workflow.py"}
{"ts":"2026-07-16T15:00:00Z","action":"门禁用户确认","stage":"spec","passed":true,"actor":"user"}
{"ts":"2026-07-16T15:00:01Z","action":"阶段推进","from":"spec","to":"spike","actor":"workflow.py"}
```

### 3.3 state vs journal 分离原则
- **state.json** = 当前快照（"现在在哪"），可重写
- **journal.jsonl** = 历史记录（"发生过啥"），append-only，不可改

分离的理由：
- state 被多次读改写，journal 只追加
- 崩溃恢复：state 可能损坏，从 journal 可重建
- 调试：journal 是完整审计日志

---

## 4. Stage 模式（核心循环）

### 4.1 7 步模式（所有 stage 都走这个）

```
[S1] 提示词加载
     AI 调 `python3 workflow.py discuss`
     → workflow.py 读 state.current_stage
     → 实例化对应 StageStrategy
     → 加载 Template_Repository/<stage>_prompt.md（提示词）
     → 加载 Standardized_Repository/<stage>_规范.md（规范词）
     → 加载 role_doc.py 里该 stage 的角色定义
     → 打印：提示词全文 + 规范全文 + stage.instruction()
     → 写 journal: 提示词加载 / 角色文档加载

[S2] AI 和用户讨论
     → AI 用提示词里的问题/结构和用户交互
     → workflow.py 不参与对话，但提示词是 workflow.py 加载的
     → 讨论持续到双方满意
     → （spike stage 特殊：AI 写 throwaway 代码验证风险，见第 6 节）

[S3] 讨论完毕门禁（第 1 道闸）
     → 用户确认"讨论完毕"
     → AI 调 `python3 workflow.py gate <stage> --discuss-done`
     → workflow.py 标记 state.stages.<stage>.gate.discussion_complete = True
     → 写 journal: 门禁讨论完毕 passed

[S4] AI 写产出文件
     → 可能是多个文件（spec: product.md + 功能*.md）
     → 主题在 plan/fix_plan 定下后，后面 stage 复用主题做文件名（见第 7 节）
     → spike stage 特殊：throwaway 代码进 .workflow_loop/spike_tmp/，结论文档进 spec/

[S5] 代码校验门禁（第 2 道闸）
     → AI 调 `python3 workflow.py gate <stage>`
     → workflow.py 跑 stage.code_validate(project_root)
     → 默认实现：检查所有 artifact_paths 的文件是否存在
     → 不存在 → 打印"产出文件未就绪"，写 journal: 门禁代码校验 failed
     → 存在 → state.stages.<stage>.gate.code_validated = True
            → 打印"代码校验通过，请和用户确认已写完"
            → 写 journal: 门禁代码校验 passed

[S6] 用户确认（第 3 道闸前半）
     → AI 问用户"<stage> 写完了？"
     → 用户确认

[S7] 用户确认门禁 + 推进（第 3 道闸后半）
     → AI 调 `python3 workflow.py gate <stage> --confirmed`
     → workflow.py 标记 state.stages.<stage>.gate.user_confirmed = True
     → 调 stage.on_advance(project_root)（默认 no-op，spike stage 清理 throwaway 代码）
     → 推进 state.current_stage = 下一 stage
     → 写 journal: 门禁用户确认 passed / 阶段推进 <stage>→<next>
```

### 4.2 3 道闸（顺序硬性）

| 闸 | 字段 | 命令 | 前置条件 | 不满足时报错 |
|---|---|---|---|---|
| 1 讨论完毕 | `discussion_complete` | `gate <stage> --discuss-done` | stage 已 discuss | "请先调 discuss 加载提示词" |
| 2 代码校验 | `code_validated` | `gate <stage>` | discussion_complete=True | "请先确认讨论完毕" |
| 3 用户确认 | `user_confirmed` | `gate <stage> --confirmed` | code_validated=True | "请先跑代码校验" |

**跳步抛错**：直接调 `gate --confirmed` 而没跑前两道 → 报错并提示正确顺序。

### 4.3 StageStrategy ABC 接口

```python
class StageStrategy(ABC):
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def artifact_paths(self) -> list[str]: ...
        # 注意：是 list 不是单个，因为 spec stage 产出多个文件
    
    @abstractmethod
    def role_doc_path(self) -> str | None: ...
    
    @abstractmethod
    def prompt_doc_path(self) -> str | None: ...
    
    @abstractmethod
    def standard_doc_path(self) -> str | None: ...
        # 新增：规范词文档路径
    
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

**和之前版本的差异**：
- `artifact_path()` → `artifact_paths()`（list，因为 spec 产出多个文件）
- 新增 `standard_doc_path()`（规范词文档）
- 新增 `on_advance()` 钩子（spike 清理用）

### 4.4 on_advance() 钩子
- 默认 no-op
- spike stage 重写：删除 `.workflow_loop/spike_tmp/` 下所有内容
- 后面扩展：某 stage 推进时要通知/迁移/清理，重写这个方法

### 4.5 每 stage 的产出规则
- **spec**：`spec/product.md` + `spec/功能*.md`（功能数量由功能拆分决定）
- **spike**：`spec/spike_<临时名>.md`（结论文档）+ throwaway 代码（进 spike_tmp/，on_advance 时删）
- **plan**：`plan/<主题>.md` + `plan/index.md`（主题在这里定）
- **acceptance**：`acceptance/<主题>.md`（复用主题）
- **qa**：`qa/<主题>.md` + `qa/index.md`（复用主题）
- **impl**：`impl/<主题>.md`（复用主题）
- **generate_code_design**：`spec/architecture_code_design.md`（第一次写）
- **update_code_design**：更新 `spec/architecture_code_design.md`（已存在，追加/修改）
- **code_design**（场景 B）：`spec/architecture_code_design.md`（从读代码反推）
- **reproduce**：`bug/<YYYY-MM-DD_HHmm-<bug描述>>.md` + 更新 `bug/index.md`
- **fix_plan**：`plan/<主题>.md` + 更新 `plan/index.md`（主题在这里定）
- **requirement**：`spec/requirement_<临时名>.md`
- **product_update**：更新 `spec/product.md`
- **feature_split**：`spec/功能<新>.md`（可能多个）

### 4.6 stdout 驱动原则（核心设计约束）

**workflow.py 每条命令的 stdout 末尾必须以 `───── 下一步：xxx ─────` 结尾**，告诉 AI 下一步干啥。

这是把"流程步骤"从 agent.md（文字）搬到代码里的关键设计：
- agent.md 只写入口（3 行）
- 流程步骤由 workflow.py 的 stdout 驱动（代码生成，不是文字描述）
- AI 跟着 stdout 走，不用记流程

**stdout 格式**：
```
<命令的实际输出内容>
──────────────────────────
下一步：<具体指令，含完整命令行>
```

**每条命令的"下一步"映射**：

| 当前命令 | stdout 末尾的"下一步" |
|---|---|
| `start`（不带 --entry） | "根据用户提问确定场景，调 `python3 workflow.py start --entry <场景>`" |
| `start --entry <entry>` | "调 `python3 workflow.py discuss` 加载第一个 stage 提示词" |
| `discuss` | "用这个提示词和用户讨论。讨论完用户说'完毕'后，调 `python3 workflow.py gate <stage> --discuss-done`" |
| `gate <stage> --discuss-done` | "写产出文件 `<artifact_paths>`。写完调 `python3 workflow.py gate <stage>`" |
| `gate <stage>`（校验通过） | "问用户'<stage> 写完了？'，用户确认后调 `python3 workflow.py gate <stage> --confirmed`" |
| `gate <stage>`（校验失败） | "产出文件未就绪，补完后再调 `python3 workflow.py gate <stage>`" |
| `gate <stage> --confirmed`（非最后 stage） | "调 `python3 workflow.py discuss` 加载下一 stage 提示词" |
| `gate <stage> --confirmed`（最后 stage） | "调 `python3 workflow.py done` 标记完成" |
| `status` | （无下一步，纯只读） |
| `done` | "工作流完成。本次 workflow 结束。" |

**强制力分层**：

| 层 | 形式 | 强制度 |
|---|---|---|
| agent.md（2 行） | 文字 | 弱：AI 可能不看，但不看就不知道入口 |
| workflow.py stdout 下一步 | 代码生成 | 中：AI 大概率跟着走，但不强制 |
| workflow.py 门禁 | 代码强制 | 强：跳步直接报错，过不去 |

**根本边界（无法突破）**：代码能强制"不调 gate 过不去"，但不能强制"AI 主动调命令"。最薄一层 agent.md 无法消除——AI 必须有入口知道"调 start"。

---

## 5. 场景

### 5.1 ScenarioStrategy ABC 接口

```python
class ScenarioStrategy(ABC):
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def stages(self) -> list[StageStrategy]: ...
        # 返回该场景的 stage 实例列表，按顺序
    
    @abstractmethod
    def entry_instruction(self) -> str: ...
        # 告诉 AI 这个场景的路线图（要走哪些 stage）
```

### 5.2 场景 A：新项目（new_project）

**环节序列**：`spec → spike → plan → acceptance → qa → impl → generate_code_design`

**详细流程**：

| 步 | stage | 命令 | 产出 | 主题 |
|---|---|---|---|---|
| A.0.1 | （进入前） | `overview` | 无（打印文档概览给 AI+用户看） | - |
| A.0.2 | （进入前） | `align` | 无（加载场景对齐提示词，问用户，确定 entry） | - |
| A.1 | （启动） | `start --entry new-project` | 初始化 state | - |
| A.2.1 | spec | `discuss` | 加载 spec 提示词+规范+角色 | - |
| A.2.2 | spec | （AI 和用户讨论产品） | - | - |
| A.2.3 | spec | `gate spec --discuss-done` | 标记讨论完毕 | - |
| A.2.4 | spec | （AI 写 spec/product.md + 功能*.md） | spec/product.md + spec/功能A.md + ... | - |
| A.2.5 | spec | `gate spec` | 代码校验所有 spec 文件存在 | - |
| A.2.6 | spec | （用户确认） | - | - |
| A.2.7 | spec | `gate spec --confirmed` | 推进到 spike | - |
| A.3.1 | spike | `discuss` | 加载穿刺提示词 | - |
| A.3.2 | spike | （AI 问用户哪些功能要穿刺，识别风险，写 throwaway 代码） | throwaway 代码进 spike_tmp/ | - |
| A.3.3 | spike | `gate spike --discuss-done` | 标记穿刺范围确认 | - |
| A.3.4 | spike | （AI 写 spec/spike_<临时名>.md 结论文档） | spec/spike_<临时名>.md | - |
| A.3.5 | spike | `gate spike` | 校验结论文档存在 | - |
| A.3.6 | spike | （用户确认穿刺结束） | - | - |
| A.3.7 | spike | `gate spike --confirmed` | 推进到 plan + on_advance 清理 spike_tmp/ | - |
| A.4.1 | plan | `discuss` | 加载 plan 提示词+规范 | - |
| A.4.2 | plan | （AI 和用户讨论计划拆分） | - | - |
| A.4.3 | plan | `gate plan --discuss-done` | 标记讨论完毕 | - |
| A.4.4 | plan | （AI 写 plan/<主题>.md + plan/index.md） | plan/<主题>.md + plan/index.md | **定主题** |
| A.4.5 | plan | `gate plan` | 校验文件存在 | - |
| A.4.6 | plan | （用户确认） | - | - |
| A.4.7 | plan | `gate plan --confirmed` | 推进到acceptance + 写 state.topic | - |
| A.5 | acceptance | （同 7 步模式） | acceptance/<主题>.md | 复用 |
| A.6 | qa | （同 7 步模式） | qa/<主题>.md + qa/index.md | 复用 |
| A.7 | impl | （同 7 步模式） | impl/<主题>.md | 复用 |
| A.8 | generate_code_design | （同 7 步模式） | spec/architecture_code_design.md | - |
| A.9 | （完成） | `done` | 标记 completed | - |

**注意**：
- spec stage 不定主题（spec 是整体设计，可能含多个主题）
- plan stage 定主题（state.topic 写入）
- acceptance/qa/impl 复用主题做文件名
- generate_code_design stage 不需要主题（它是文档级产出，不属于某个功能主题）

### 5.3 场景 B：存量无 workflow_loop（existing_no_workflow）

**环节序列**：`code_design → spec → spike → plan → acceptance → qa → impl → update_code_design`

**和场景 A 的差异**：
- 开头多一个 `code_design` stage（看代码 + 能跑就跑 + 反推 architecture_code_design.md）
- spec stage 的 product.md 是根据 architecture_code_design.md 反推的（不是从零设计）
- product.md 里有路由链接到 architecture_code_design.md（此时已存在）
- 结尾是 `update_code_design`（不是 `generate_code_design`，因为 architecture_code_design.md 在开头已生成）

**详细流程**：

| 步 | stage | 产出 | 备注 |
|---|---|---|---|
| B.0.1 | （进入前） | `overview` 打印文档概览 | 同 A |
| B.0.2 | （进入前） | `align` 确定场景 | 用户说"已有项目没接 workflow_loop" |
| B.1 | （启动） | `start --entry existing-no-workflow` | 初始化 state |
| B.2.1 | code_design | `discuss` 加载code_design提示词 | 教 AI 怎么看代码 |
| B.2.2 | code_design | AI 看代码 + 能跑就跑 | 看目录结构、入口、依赖；运行看脉络 |
| B.2.3-B.2.7 | code_design | 7 步模式走完 | 产出 `spec/architecture_code_design.md` |
| B.3 | spec | 7 步模式 | 产出 `spec/product.md` + `spec/功能*.md`（根据 architecture_code_design.md 反推，product.md 有路由链接） |
| B.4 | spike | 同 A | |
| B.5 | plan | 同 A，定主题 | |
| B.6-B.8 | acceptance/qa/impl | 复用主题 | |
| B.9 | update_code_design | 7 步模式，产出更新 `spec/architecture_code_design.md` | impl 后把新理解更新回去 |
| B.10 | （完成） | `done` | |

### 5.4 场景 C：修 bug（bugfix，存量有 workflow_loop）

**环节序列**：`reproduce → fix_plan → acceptance → qa → impl → update_code_design`

**和场景 A 的差异**：
- 没有 spec / spike / plan，换成 reproduce / fix_plan
- 主题在 fix_plan 定（从 bug 反推）
- 结尾是update_code_design（不是generate_code_design）
- done 时沉淀 bug 到 bug/index.md

**详细流程**：

| 步 | stage | 产出 | 主题 |
|---|---|---|---|
| C.0.1 | （进入前） | `overview` | - |
| C.0.2 | （进入前） | `align` 确定场景 | 用户说"要修 bug" |
| C.1 | （启动） | `start --entry bugfix` | - |
| C.2 | reproduce | 7 步模式 | `bug/<YYYY-MM-DD_HHmm-<bug描述>>.md` + 更新 `bug/index.md` | 无（用 bug 描述） |
| C.3 | fix_plan | 7 步模式 | `plan/<主题>.md` + 更新 `plan/index.md` | **定主题**（从 bug 反推） |
| C.4 | acceptance | 7 步模式 | `acceptance/<主题>.md` | 复用 |
| C.5 | qa | 7 步模式 | `qa/<主题>.md` + 更新 `qa/index.md` | 复用 |
| C.6 | impl | 7 步模式 | `impl/<主题>.md` | 复用 |
| C.7 | update_code_design | 7 步模式 | 更新 `spec/architecture_code_design.md` | - |
| C.8 | （完成） | `done` + 沉淀 bug 到 `bug/index.md` | - |

### 5.5 场景 D：改产品设计（product_mod，存量有 workflow_loop）

**环节序列**：`requirement → product_update → feature_split → spike → plan → acceptance → qa → impl → update_code_design`

**和场景 A 的差异**：
- spec 拆成 requirement + product_update + feature_split 三步
- spike 在 feature_split 之后
- 主题在 plan 定
- 结尾是update_code_design

**详细流程**：

| 步 | stage | 产出 | 主题 |
|---|---|---|---|
| D.0.1 | （进入前） | `overview` | - |
| D.0.2 | （进入前） | `align` 确定场景 | 用户说"要改产品设计" |
| D.1 | （启动） | `start --entry product-mod` | - |
| D.2 | requirement | 7 步模式 | `spec/requirement_<临时名>.md` | 无 |
| D.3 | product_update | 7 步模式 | 更新 `spec/product.md` | 无 |
| D.4 | feature_split | 7 步模式 | `spec/功能<新>.md`（可能多个） | 无 |
| D.5 | spike | 同 A | `spec/spike_<临时名>.md` + throwaway 代码 | 无 |
| D.6 | plan | 7 步模式 | `plan/<主题>.md` + `plan/index.md` | **定主题** |
| D.7-D.9 | acceptance/qa/impl | 复用主题 | |
| D.10 | update_code_design | 7 步模式 | 更新 `spec/architecture_code_design.md` | - |
| D.11 | （完成） | `done` | - |

---

## 6. spike stage 特殊行为

spike stage 和普通 stage 的 7 步模式略有不同，S2 和 S4 有额外动作：

### 6.1 穿刺提示词
`Template_Repository/spike_prompt.md` 教 AI：
- 问用户"需要穿刺吗？哪些功能要穿刺？"
- 提前识别风险点
- 写 throwaway 代码验证风险
- 写结论文档记录风险 + 验证结果

### 6.2 throwaway 代码
- AI 在 `.workflow_loop/spike_tmp/<功能>/` 下写 throwaway 代码
- throwaway 代码不进 git（.workflow_loop/ 整个 gitignore 或部分 gitignore）
- 代码目的是验证设计风险，不是产出

### 6.3 on_advance 清理
- spike stage 的 `on_advance()` 重写：删除 `.workflow_loop/spike_tmp/` 下所有内容
- 在 `gate spike --confirmed` 时自动调用
- 只保留结论文档 `spec/spike_<临时名>.md`

### 6.4 结论文档
- 产出：`spec/spike_<临时名>.md`
- 内容：风险点列表 + 验证方式 + 验证结果 + 结论
- 这个文档**保留**（不删除），作为后续 plan 的输入

### 6.5 spike stage 的 7 步详细

```
[S1] discuss → 加载 spike_prompt.md
[S2] AI 问用户"哪些功能要穿刺？" → 用户回答 → AI 识别风险 → 写 throwaway 代码到 spike_tmp/
[S3] gate spike --discuss-done → 标记穿刺范围确认
[S4] AI 写 spec/spike_<临时名>.md（结论文档）
[S5] gate spike → 校验结论文档存在
[S6] 用户确认穿刺结束
[S7] gate spike --confirmed → on_advance 清理 spike_tmp/ → 推进到 plan
```

---

## 7. 主题（topic）规则

### 7.1 主题是什么
主题 = 文件名里的描述性标题，格式 `YYYY-MM-DD_HHmm-<主题>`。

例：workflow 是做"用户认证系统"，则：
```
plan/2026-07-16_1438-用户认证系统.md
acceptance/2026-07-16_1438-用户认证系统.md
qa/2026-07-16_1438-用户认证系统.md
impl/2026-07-16_1438-用户认证系统.md
```

### 7.2 何时定
- 场景 A/B/D：**plan stage** 定主题
- 场景 C：**fix_plan stage** 定主题

定主题的时机：plan/fix_plan 的 S4（写产出）时，AI 和用户讨论决定主题字符串，写入 `state.topic` 和文件名。

### 7.3 如何复用
- plan/fix_plan 之后的 stage（acceptance/qa/impl）强制复用 `state.topic` 做文件名
- 文件名格式：`<folder>/<YYYY-MM-DD_HHmm-<topic>>.md`
- 日期时间用 workflow 启动时间（不是 stage 时间），保证整个 workflow 的文件名时间一致

### 7.4 主题前的命名规则
plan 之前的 stage（spec/spike/reproduce/requirement/product_update/feature_split）用自己的命名，不带主题：
- spec：`spec/product.md` + `spec/功能*.md`（功能名由讨论决定）
- spike：`spec/spike_<临时名>.md`（临时名由穿刺范围决定）
- reproduce：`bug/<YYYY-MM-DD_HHmm-<bug描述>>.md`（bug 描述由用户决定）
- requirement：`spec/requirement_<临时名>.md`
- feature_split：`spec/功能<新>.md`

### 7.5 不需要主题的 stage
- code_design / update_code_design / generate_code_design：产出 `spec/architecture_code_design.md`，是文档级产出，不属于某个功能主题
- reproduce：用自己的 bug 描述做文件名

---

## 8. architecture_code_design.md 规则

### 8.1 命名
`spec/architecture_code_design.md`（名字已定）

### 8.2 何时生成
| 场景 | 何时生成 | stage 名 |
|---|---|---|
| A 新项目 | impl 之后 | `generate_code_design` stage（第一次写） |
| B 存量接入 | 开头 | `code_design` stage（从读+跑反推） |
| C bugfix | 已存在（之前生成过） | 无生成 stage |
| D product_mod | 已存在 | 无生成 stage |

### 8.3 何时更新
| 场景 | 何时更新 | stage 名 |
|---|---|---|
| A 新项目 | 不更新（第一次生成就是最终版） | - |
| B 存量接入 | impl 之后 | `update_code_design` stage |
| C bugfix | impl 之后 | `update_code_design` stage |
| D product_mod | impl 之后 | `update_code_design` stage |

### 8.4 路由链接
- `spec/product.md` 里始终有 markdown 链接 `[code_design](./architecture_code_design.md)`
- 场景 A：链接先指向不存在的文件，impl 后的 `generate_code_design` stage 才创建该文件
- 场景 B/C/D：链接指向已存在的文件

### 8.5 内容结构（穿刺不强制，后面 Standardized_Repository 里定）
- 系统架构图（文字描述）
- 模块划分
- 数据流
- 关键设计决策
- 已知技术债

---

## 9. bug 册

### 9.1 性质
**被动沉淀库**，不是主动 workflow 的 stage。bug 册记录已解决问题的复现+根因+修复方案，供以后查询。

### 9.2 bugfix done 触发沉淀
- 场景 C 的 `done` 命令执行时：
  - 若 `entry == "bugfix"`：自动把 `bug/<主题>.md` 追加到 `bug/index.md`（沉淀）
  - 非 bugfix 场景：不沉淀

### 9.3 结构
```
bug/
  ├─ index.md                       # 索引表（自动维护）
  └─ YYYY-MM-DD_HHmm-<bug描述>.md   # 单个 bug 记录
```

**index.md 结构**：
```markdown
| 日期 | 主题 | 根因 | 修复方案 | 状态 |
|---|---|---|---|---|
| 2026-07-16 | 用户认证系统 | ... | ... | 已修复 |
```

### 9.4 查询用法
任何人遇到重复问题时，先查 `bug/index.md`，有记录直接用，不用重新走 bugfix 流程。

---

## 10. CLI 命令清单

> **设计约束**：每条命令的 stdout 末尾必须以 `───── 下一步：xxx ─────` 结尾（见第 4.6 节）。下面每条命令的"stdout 末尾"字段就是这个下一步。

### 10.1 `start`（两种模式）

**模式 1：不带 `--entry`（替代原 align）**
- **干啥**：打印合法场景值，让 AI 根据用户提问确定场景
- **何时调**：用户提问后，AI 需要知道有哪些合法场景
- **stdout 内容**：
  ```
  可选场景：
    new-project          ← 新项目/空项目
    existing-no-workflow ← 已有项目接入 workflow_loop
    bugfix              ← 修 bug
    product-mod          ← 加功能/改设计
  ```
- **stdout 末尾**：`下一步：根据用户提问确定场景，调 python3 workflow.py start --entry <场景>`
- **写 journal**：无（纯只读提示）

**模式 2：带 `--entry <场景>`（替代原 overview + start）**
- **干啥**：初始化 state、加载 scenario、打印文档概览 + 路线图
- **何时调**：AI 从用户提问确定场景后
- **流程**：
  1. 实例化对应 ScenarioStrategy
  2. 调 `scenario.stages()` 拿 stage 列表
  3. 初始化 state.json（所有 stage pending）
  4. 打印文档概览（原 overview 的内容：spec/plan/bug/qa/acceptance/impl 各是啥、命名规则）
  5. 打印 `scenario.entry_instruction()`（路线图）
  6. 写 journal：工作流启动 / 场景进入 / 文档概览加载
- **entry 取值**：`new-project` / `existing-no-workflow` / `bugfix` / `product-mod`
- **stdout 末尾**：`下一步：调 python3 workflow.py discuss 加载第一个 stage 提示词`

### 10.4 `discuss`
- **干啥**：加载当前 stage 的提示词+规范+角色定义，打印给 AI
- **何时调**：每个 stage 的 S1
- **流程**：
  1. 读 `state.current_stage`
  2. 实例化对应 StageStrategy
  3. 加载 `stage.prompt_doc_path()` 指向的提示词
  4. 加载 `stage.standard_doc_path()` 指向的规范词
  5. 加载 role_doc.py 里该 stage 的角色定义
  6. 打印：提示词全文 + 规范全文 + `stage.instruction()`
  7. 写 journal：提示词加载 / 角色文档加载
- **stdout 末尾**：`下一步：用这个提示词和用户讨论。讨论完用户说"完毕"后，调 python3 workflow.py gate <stage> --discuss-done`

### 10.5 `gate <stage> --discuss-done`
- **干啥**：标记讨论完毕（第 1 道闸）
- **何时调**：用户说"讨论完毕"后
- **前置**：该 stage 已 discuss（journal 里有提示词加载记录）
- **流程**：
  1. 标记 `state.stages.<stage>.gate.discussion_complete = True`
  2. 写 journal：门禁讨论完毕 passed
  3. 打印"讨论完毕，可以写产出了"
- **stdout 末尾**：`下一步：写产出文件 <artifact_paths>。写完调 python3 workflow.py gate <stage>`

### 10.6 `gate <stage>`（无 flag）
- **干啥**：跑 code_validate（第 2 道闸）
- **何时调**：AI 写完产出文件后
- **前置**：`discussion_complete == True`
- **流程**：
  1. 跑 `stage.code_validate(project_root)`
  2. 失败 → 打印"产出文件未就绪"，写 journal：门禁代码校验 failed
  3. 成功 → 标记 `code_validated = True`，打印"请和用户确认已写完"，写 journal：门禁代码校验 passed
- **stdout 末尾**（校验通过）：`下一步：问用户"<stage> 写完了？"，用户确认后调 python3 workflow.py gate <stage> --confirmed`
- **stdout 末尾**（校验失败）：`下一步：产出文件未就绪，补完后再调 python3 workflow.py gate <stage>`

### 10.7 `gate <stage> --confirmed`
- **干啥**：用户确认 + 推进（第 3 道闸）
- **何时调**：用户确认"写完了"后
- **前置**：`code_validated == True`
- **流程**：
  1. 标记 `user_confirmed = True`
  2. 调 `stage.on_advance(project_root)`（spike stage 清理 throwaway 代码）
  3. 推进 `state.current_stage` = 下一 stage
  4. 写 journal：门禁用户确认 passed / 阶段推进 <from>→<to>
- **stdout 末尾**（非最后 stage）：`下一步：调 python3 workflow.py discuss 加载下一 stage 提示词`
- **stdout 末尾**（最后 stage）：`下一步：调 python3 workflow.py done 标记完成`

### 10.8 `status`
- **干啥**：打印 state + journal 摘要
- **何时调**：任何时候想看
- **stdout 内容**：
  - 当前 stage
  - 各 stage 的 gate 状态（3 道闸哪些过了）
  - journal 最近 10 条
  - workflow 进度百分比
- **stdout 末尾**：无（纯只读命令，不驱动下一步）

### 10.9 `done`
- **干啥**：标记 completed + bug 册沉淀（若 bugfix）
- **何时调**：最后一个 stage 的 `gate --confirmed` 之后
- **前置**：`current_stage` 是最后一个 stage 且 `user_confirmed == True`
- **流程**：
  1. 标记 `state.completed_at = now`
  2. 标记 `state.current_stage = "completed"`
  3. 若 `entry == "bugfix"`：沉淀 `bug/<主题>.md` 到 `bug/index.md`
  4. 写 journal：工作流完成
- **stdout 末尾**：`工作流完成。本次 workflow 结束。`

---

## 11. 扩展点

### 11.1 加新 stage
加一个 `StageStrategy` 子类，实现所有 abstract 方法。然后在对应 scenario 的 `stages()` 列表里插入。零改动 workflow.py。

例：加 "review" stage：
```python
class ReviewStage(StageStrategy):
    def name(self): return "review"
    def artifact_paths(self): return ["review/<主题>.md"]
    ...
```

### 11.2 加新 scenario
加一个 `ScenarioStrategy` 子类，实现 `stages()` 返回自己的 stage 序列。在 workflow.py 的 scenario 注册表里加一行映射。

### 11.3 加新门禁类型
重写 `StageStrategy.code_validate()`。默认查文件存在，重写后可查内容结构、查文件大小、查 git 状态等。

### 11.4 加 on_advance 行为
重写 `StageStrategy.on_advance()`。默认 no-op，重写后可做清理、通知、迁移等。

### 11.5 加自动路由（ProjectCharDetector，TBD）
留一个 `ProjectCharDetector` 接口，默认实现 = "AI 显式传 `--entry`"。后面加自动检测（看有没有 `.workflow_loop/`、看代码量、看 README 等），加一个新实现即可。

### 11.6 加 lifecycle hooks
`state.meta.hooks` 留口子，后面加 `after_advance` / `after_discuss` / `after_gate` 等 hook 配置。

---

## 12. 穿刺不做

| 不做的 | 理由 |
|---|---|
| hook / per-turn breadcrumb 注入 | 强制力在门禁上，不在唠叨上 |
| session 指针独立 | 穿刺单窗口，state.current_stage 够用 |
| 内容结构校验 | 只查文件存在，内容结构归 Standardized_Repository 管 |
| 自动路由 | ProjectCharDetector 留口子，默认 AI 显式传 --entry |
| 场景 B/C/D 的完整实现 | 只实现场景 A，其他留接口（stages() 返回 [] + TODO） |
| Template/Standardized 内容 | 只放占位 .md，AI 调 discuss 时加载占位内容 |
| MCP server 包装 | 穿刺直接 CLI，MCP 是 later |
| bug 册的查询命令 | 穿刺只做沉淀，查询是 later |
| journal 的查询/grep 命令 | 穿刺只做追加 + status 摘要 |

---

## 13. agent.md 契约

### 13.1 设计原则：压到最薄
agent.md 只写**入口 + "跟着 stdout 走"**，不写完整流程。流程步骤由 workflow.py 的 stdout 驱动（第 4.6 节）。这样：
- AI 不用记命令清单
- 流程改动只改 workflow.py 的 stdout 逻辑（代码），不用改 agent.md（文字）
- agent.md 永远只有 2 行，不会随流程演进膨胀

### 13.2 内容（2 行）
```markdown
# Agent 契约

本项目由 workflow_loop 管理。用户提出需求后，调 `python3 workflow.py start`，
之后严格按每条命令 stdout 打印的"下一步"执行。
```

### 13.3 AI 怎么用
1. AI 读 agent.md，知道入口是 `python3 workflow.py start`
2. AI 调 `start`（不带 --entry），读 stdout 看合法场景值
3. AI 从用户提问确定场景，调 `start --entry <场景>`
4. 读 stdout 末尾的"下一步"
5. 循环：调命令 → 读 stdout → 按"下一步"调下一条
6. 直到 `done` 的 stdout 说"工作流完成"

**AI 不需要记流程**——流程在 workflow.py 的 stdout 里，AI 只需"调命令 + 读下一步"。
**AI 不需要记场景清单**——`start`（不带 --entry）会打印合法值。

### 13.4 根本边界（无法消除的）
| 能强制 | 不能强制 |
|---|---|
| 不调 gate 就过不了下一 stage（代码强制） | AI 主动调命令的时机（AI 行为，代码管不着） |
| 文件不存在就过不了 code_validate | AI 真去和用户讨论 |
| gate 顺序错了报错 | AI 读 stdout 后真跟着走 |

**最薄一层 agent.md 无法消除**——AI 必须有入口知道"调 start"。但这层只有 2 行，不是命令清单。剩下的全在代码里。

---

## 14. 确认清单

设计到此，以下全部钉死：

- [x] 根问题 + 根解法（第 1 节）
- [x] 部署形态：Python + CLI + opencode/codex（第 2 节）
- [x] 数据模型：state.json + journal.jsonl（第 3 节）
- [x] Stage 7 步模式 + 3 道闸（第 4 节）
- [x] stdout 驱动原则：每条命令末尾打印"下一步"（第 4.6 节）
- [x] StageStrategy + ScenarioStrategy ABC 接口（第 4-5 节）
- [x] 4 个场景的环节序列 + 每 stage 产出（第 5 节）
- [x] spike 特殊行为：throwaway + on_advance 清理（第 6 节）
- [x] 主题规则：plan/fix_plan 定，后面复用（第 7 节）
- [x] architecture_code_design.md 生成/更新规则（第 8 节）
- [x] bug 册被动沉淀（第 9 节）
- [x] 5 条 CLI 命令（start 两种模式 + discuss + gate + status + done）+ 每条 stdout 末尾的"下一步"（第 10 节）
- [x] 扩展点：stage/scenario/gate/on_advance/路由/hooks（第 11 节）
- [x] 穿刺不做清单（第 12 节）
- [x] agent.md 契约压到 2 行（第 13 节）

**等待用户审查。审查通过后改代码：删 align/overview 命令，合并进 start。**
