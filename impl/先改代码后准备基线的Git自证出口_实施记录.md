# 【实施】先改代码后准备基线的Git自证出口

- 工作流编号：2026-09-08-1207-product_change
- 验收主题：先改代码后准备基线的Git自证出口

<a id="1-实施依据"></a>
## 1. 实施依据

| 依据类型 | 依据编号 | 具体内容 | 文档位置 |
|---|---|---|---|
| 验收计划 | AC-01 至 AC-03 | Git 自证放行、不可自证拒绝、采集链路打通三条验收条件 | acceptance/先改代码后准备基线的Git自证出口_验收计划.md |
| 上游实现 | R5 | 第二次准备已实现 _trusted_git_head_baseline（Git HEAD 补齐副本），延伸到首次准备 | src/workflow_loop/rollback.py |

<a id="2-实施前计划"></a>
<a id="2-实施前计划代码计划"></a>
## 2. 实施前计划（代码计划）


<a id="21-预期产品结果"></a>
### 2.1 预期产品结果

- 先写代码后准备基线可用 Git 自证放行并生成清单；不可自证保持拒绝；中途加主题不再死循环。

<a id="22-最低实现设计"></a>
### 2.2 最低实现设计

| 设计项 | 已确认做法 | 选择理由 | 对应验收条件 |
|---|---|---|---|
| 首次准备自证 | 快照差异文件逐个尝试 _trusted_git_head_baseline：进场快照哈希等于 HEAD 版本字节时用 HEAD 补副本 | Git 能证明进场时内容时放行，不能证明时保持拒绝 | AC-01、AC-02 |
| 整体哈希拦截调整 | 有快照时差异已逐文件核对，整体哈希不再重复拦截；无快照旧轮次保持原拦截 | 快照核对覆盖整体哈希语义 | AC-01 |
| 死循环修复 | current_workflow_topics 与 sync_stage_tables 在 state.topics 非空时也合并 topic_relations 表主题；确认门同样合并 | 中途加主题时索引待生成不阻断文档生成与主题登记（断言三） | AC-03 |

<a id="23-代码修改计划"></a>
### 2.3 代码修改计划

| 顺序 | 文件 | 类、函数或配置项 | 当前逻辑 | 计划修改内容 | 数据、状态或输出变化 | 对应验收条件 | 前置步骤 |
|---|---|---|---|---|---|---|---|
| 1 | src/workflow_loop/rollback.py | prepare_impl | 首次准备时快照差异直接拒绝；整体哈希不同直接拒绝 | 快照差异文件逐个 Git 自证（HEAD 字节补副本），不能自证的保持拒绝并列出原因；有快照时整体哈希拦截让位给逐文件核对 | 先写代码后准备基线的场景可用 Git 自证放行，manifest 正常生成 | AC-01、AC-02 | 无 |
| 2 | src/workflow_loop/topic.py | current_workflow_topics | state.topics 非空时只返回 state.topics，读不到表内新增主题 | state.topics 与 topic_relations 表主题合并去重（断言三：表为唯一输入） | 中途加主题后文档生成与确认门都能拿到全部主题 | AC-03 | 无 |
| 3 | src/workflow_loop/records.py | sync_stage_tables 与 cli 确认门 | 主题解析失败回退 state.topics（拿不到新主题）；确认门只读索引 | 索引解析外合并 topic_relations 表主题（sync 与确认门两处） | 中途加主题时验收计划文档正常生成，索引死循环打破 | AC-03 | 2 |

<a id="开发检查计划"></a>
#### 开发检查计划

| 检查命令或方法 | 检查范围 | 预期观察结果 |
|---|---|---|
| .venv/bin/python -m pytest tests/test_rollback.py tests/test_machine_collect_extension.py tests/test_records.py tests/test_workflow_guidance.py -q | Git 自证与主题合并回归 | 全部通过退出码 0 |

<a id="24-未决问题"></a>
### 2.4 未决问题

- 暂无

<a id="3-实施后记录"></a>
<a id="3-实施后记录代码实施与代码结果"></a>
## 3. 实施后记录（代码实施与代码结果）

<a id="31-实施动作记录"></a>
### 3.1 实施动作记录

| 实施顺序 | 对应计划步骤 | 文件 | 代码位置（最终文件） | 实际执行的动作 | 当步反馈 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 1 | src/workflow_loop/rollback.py | L2128-L2200 | prepare_impl 首次准备加 Git 自证出口：快照差异文件逐个核对——进场快照记录不存在的文件直接放行（新文件）；存在且快照哈希等于 Git HEAD 版本时用 HEAD 字节补副本；不能自证的按文件列出原因拒绝；有快照时整体哈希拦截让位给逐文件核对，无快照旧轮次保持原拦截 | 本轮真实触发：非 git 证明文件被正确列出拒绝原因（records.py 快照为中间态无法自证，AC-02 实证）；tests/test_git_baseline_exit.py 4 项通过 | 已完成 |
| 2 | 2 | src/workflow_loop/topic.py | L86-L112 | current_workflow_topics 改为 state.topics 与 topic_relations 表主题合并去重（原逻辑 state.topics 非空时不再读表） | 合并测试通过；本轮中途加第三主题后确认门正确登记全部三主题 | 已完成 |
| 3 | 3 | src/workflow_loop/records.py | L3028-L3060 | sync_stage_tables 主题解析外合并 topic_relations 表主题（索引待生成时文档仍能生成）；cli 确认门索引读取外同样合并表主题 | 死循环实测打破：中途加主题后验收计划文档生成、索引回填真链接、门禁通过 | 已完成 |
| 3b | 3 | src/workflow_loop/cli.py | L4808-L4820 | sync_stage_tables 主题解析外合并 topic_relations 表主题（索引待生成时文档仍能生成）；cli 确认门索引读取外同样合并表主题 | 死循环实测打破：中途加主题后验收计划文档生成、索引回填真链接、门禁通过 | 已完成 |

<a id="32-实施中问题与处理"></a>
### 3.2 实施中问题与处理

- 本轮自身即真实触发：进场快照拍到代码中间态（records.py 快照哈希既非 HEAD 也非当前），Git 自证正确拒绝——该文件行号仍手算；自证放行路径由自动化测试覆盖，真实放行场景待下轮干净流程验证。
- 既有测试 test_prepare_rejects_unregistered_change_after_impl_entry 的断言从匹配旧报错清单改为匹配新按文件拒绝原因（语义等价：非 git 环境无法自证仍拒绝）。

<a id="33-未完成内容"></a>
### 3.3 未完成内容

状态：无

<a id="34-代码结果"></a>
### 3.4 代码结果

<a id="341-实际代码修改"></a>
#### 3.4.1 实际代码修改

| 文件 | 代码位置（最终文件） | 实际修改的代码逻辑 | 数据、状态或输出的实际变化 | 修改理由 | 对应验收条件 | 测试证据 |
|---|---|---|---|---|---|---|
| src/workflow_loop/rollback.py | L2128-L2200 | 首次准备的 Git 自证出口：快照差异分类处理（不存在→新文件放行；快照哈希=HEAD→HEAD 字节副本；否则拒绝列原因）；整体哈希拦截在有快照时不再重复 | 先写代码后准备基线：Git 可证明时放行，不可证明时按文件给出具体拒绝原因 | 真实工作流先写代码后准备无出口（本轮实证）；复用第二次准备已有的 _trusted_git_head_baseline | AC-01、AC-02 | tests/test_git_baseline_exit.py 自证放行/新文件放行/不可自证拒绝 三项通过 |
| src/workflow_loop/topic.py | L86-L112 | current_workflow_topics 合并 state.topics 与 topic_relations 表主题（断言三：表为唯一输入） | 中途加主题后所有读取方都能拿到完整主题清单 | 原逻辑 state.topics 非空时读不到表内新主题 | AC-03 | test_current_workflow_topics_merges_table 通过 |
| src/workflow_loop/records.py | L3028-L3060 | sync_stage_tables 主题解析失败或缺失时从 topic_relations 表合并（不再只回退 state.topics） | 索引待生成占位不再阻断文档生成 | 索引需要文档、文档需要主题解析、主题解析需要索引合法——死循环 | AC-03 | 本轮实测：第三主题验收计划文档生成、门禁通过 |
| src/workflow_loop/cli.py | L4808-L4820 | 验收计划确认门读索引外合并 current_workflow_topics（含表主题） | 中途加主题在确认门正确登记 state.topics | 确认门原只读索引，索引待生成时新主题登记不到 | AC-03 | 本轮实测：--confirmed 后 state.topics 含全部三主题 |

<a id="342-开发检查记录"></a>
#### 3.4.2 开发检查记录

| 检查命令或方法 | 检查范围 | 实际反馈 | 是否需要继续修改 |
|---|---|---|---|
| .venv/bin/python -m pytest tests/test_git_baseline_exit.py tests/test_rollback.py tests/test_machine_collect_extension.py tests/test_machine_collect.py tests/test_empty_result_table_guard.py tests/test_records.py tests/test_workflow_guidance.py tests/test_gate_rework_stability.py tests/test_return_rework_flow.py tests/test_commands.py -q --basetemp=/tmp/wf-git | Git 自证、主题合并与既有回退/表流程回归 | 183 passed（含 1 处既有断言随新报错文案更新），退出码 0 | 否 |

<a id="4-上下游文档"></a>
## 4. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/先改代码后准备基线的Git自证出口_验收计划.md) | 本主题要达到的用户结果和验收条件 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整交付链路 |
| 下游 | `qa/先改代码后准备基线的Git自证出口_测试计划.md`（待生成） | 代码结果确认后，在测试验证开始时确认范围和通过标准 |
| 下游 | `qa/先改代码后准备基线的Git自证出口_测试结果.md`（待生成） | 同一测试验证阶段连续完成测试代码、登记、执行和结果 |
| 下游 | `acceptance/先改代码后准备基线的Git自证出口_验收结果.md`（待生成） | 正式测试后执行主题验收 |
