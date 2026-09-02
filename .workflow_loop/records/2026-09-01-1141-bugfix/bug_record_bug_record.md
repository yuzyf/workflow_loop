# 【缺陷】退回验收计划后新增主题能走通门禁与追踪表

- 工作流编号：2026-09-01-1141-bugfix

## 缺陷信息

| 缺陷编号 | 现象 | 复现步骤 | 实际结果 | 期望结果 | 根因 |
|---|---|---|---|---|---|
| BUG-01 | 轮次已推进过验收计划后执行 workflow return 退回，并向 acceptance/索引.md 新增验收主题，第二道门 workflow gate acceptance_plan 报「索引的主题必须覆盖当前工作流全部主题」拒绝放行；第三道门 --confirmed 又因第二道门未通过被拦，而唯一能把新主题写入 state.topics 的注册代码位于第三道门内部，新主题永远进不了流程。 | 在临时项目用 register_topics 登记 2 个旧主题并构造 state.topics 为这两个旧主题的 acceptance_plan 阶段状态；把 acceptance/索引.md 写成 3 个主题（2 旧 + 1 新）并补齐验收计划与记录表；在沙盒目录执行 workflow gate acceptance_plan --discuss-done 后执行 workflow gate acceptance_plan | 门禁输出唯一报错：acceptance/索引.md 的主题必须覆盖当前工作流全部主题；当前主题 ['打开废纸篓查看已删文件', '从废纸篓恢复文件']，索引主题含第 3 个主题；再执行 workflow gate acceptance_plan --confirmed 报「第二道程序校验还没有通过」，state.topics 保持 2 个旧主题不变。 | 第二道门的校验集应包含 state 已有主题并接纳索引中未使用过的新主题，与 acceptance/索引.md 一致时放行，用户可依次通过第二、第三道门进入下一阶段。 | 根因说明：第二道门取校验集时 or 短路——state 已有主题时 current_workflow_topics 非空，candidate_topics()（实现为 topic in current or topic not in history，本就为收纳索引新主题而写）永不执行，校验集被钉死在旧主题，与索引 3 个主题比对必失败；而注册新主题写入 state 的代码只在第三道门 --confirmed 内部，第三道门又要求第二道门先通过，形成互相等待。根因位置：src/workflow_loop/stages/stages.py 第 333 行 topics = current_workflow_topics(project_root) or candidate_topics(project_root)。根因证据：沙盒 /tmp/wf_repro_deadlock 跑真实命令 workflow gate acceptance_plan，报错「当前主题 [2 个旧主题]，索引主题 [3 个]」；再跑 workflow gate acceptance_plan --confirmed 报「第二道程序校验还没有通过」，state.topics 未变，死锁两端闭合。 |
| BUG-02 | 同一场景下需求交付追踪表不为新增主题补交付行：退回后工作流章节仍存在（旧主题的行在），往索引追加新主题后追踪表没有任何机制为其生成行，第二道门随即报缺少主题的交付记录。 | 在 BUG-01 沙盒中保留需求交付追踪表.md 已含 demo-return 章节（仅 2 个旧主题的行）；调用真实 API traceability.ensure_workflow_section(root, "demo-return", 3 个主题) | 函数返回 False，追踪表正文不变，新主题「删除进废纸篓并入当前轮次」不出现在表中任何一行。 | 章节已存在但索引主题在表内缺行时，ensure_workflow_section 应按与建表相同的初值规则为该主题追加交付行。 | 根因说明：ensure_workflow_section 只负责「章节整体缺失时按主题生成章节」，检测到工作流章节已存在就直接返回，不检查章节内是否缺少索引新增主题的行，新主题没有任何机制获得交付行。根因位置：src/workflow_loop/traceability.py ensure_workflow_section 中 if _workflow_heading_pattern(workflow_id).search(content): return False 分支。根因证据：沙盒中追踪表 demo-return 章节仅含 2 个旧主题行，直接调用 ensure_workflow_section(root, 'demo-return', 3 个主题) 返回 False，grep 确认新主题「删除进废纸篓并入当前轮次」不在表格任何一行。 |
| BUG-03 | 同一场景下 workflow scaffold 与 discuss 环节加载不为新主题生成验收计划记录表：scaffold 只按 state.topics 的 2 个旧主题建表，新主题没有 acceptance_plan 表，门禁报「记录表尚未填写」，需手动 scaffold --topic 指定才能绕行。 | 在 BUG-01 沙盒执行 workflow scaffold；查看 .workflow_loop/records/demo-return/ 下生成的 acceptance_plan 表；执行门禁后确认新主题因缺表被报「验收计划工作记录表尚未填写内容」 | 仅生成 2 个旧主题的 acceptance_plan 表和 topic_relations 表；新主题无表，门禁一度报「主题『…』的验收计划工作记录表尚未填写内容」。 | 与修复后的第二道门校验集口径一致：scaffold 与 ensure_stage_tables 的主题来源应包含索引中未使用过的新主题，为新主题一并建表。 | 根因说明：scaffold 与环节加载生成记录表的主题来源与第二道门同源，均取 current_workflow_topics（即 state.topics），索引中未使用过的新主题拿不到 acceptance_plan 表，门禁报「记录表尚未填写」。根因位置：src/workflow_loop/records.py 第 2094 行 ensure_stage_tables 的 topics = current_workflow_topics(project_root)；src/workflow_loop/cli.py cmd_scaffold 非当前阶段分支同样调用 current_workflow_topics。根因证据：沙盒执行 workflow scaffold 只生成 2 个旧主题的 acceptance_plan 表；补齐第 3 份表前门禁报「主题「打开废纸篓查看已删文件」的验收计划工作记录表尚未填写内容」类错误。 |
| BUG-04 | 同一个 Run 内第一次实施完成并推进出 impl 后，用户 workflow return 退回上游、重走环节再次进入 impl；第二次进入时程序重新冻结入场基线，快照里已包含第一次实施的真实改动，第二道门用新快照做 diff 时，旧主题实施结果登记的代码文件全部「未检测到变化」，批量误报（废纸篓轮实际产生 57 项）。旧主题本轮凌晨真实做过的实施被基线覆盖在校验语义上抹平。 | 在沙盒用真实函数链复现：ensure_impl_recovery_baseline 首次冻结快照A（代码 return 1）；真实修改 src/demo/core.py 为 return 2 并在 impl_record 表登记；clear_stage_gates 模拟 return 清零后 ensure_impl_recovery_baseline 第二次冻结得快照B；分别用两份快照调 actual_implementation_paths_since_entry 对比当前代码 | 相对快照A检出 ['src/demo/core.py']；相对快照B检出 []。同一份真实改动对第二次入场的校验完全不可见；退回后 code_baseline_hash 被清为 None，二次进入重新冻结返回 True 覆盖原快照。 | 同一 Run 重进 impl 继承首次入场基线：入场快照与 code_baseline_hash 不被第二次冻结覆盖，diff 仍是「本轮开始时代码 → 当前代码」，旧主题真实改动照常检出。 | 根因说明：clear_stage_gates 把 impl 的 code_baseline_hash 清为 None，ensure_impl_recovery_baseline 的守卫 code_baseline_hash is not None 因此失效，_freeze_impl_code_baseline 无条件重算并覆盖 meta 中的入场快照——程序隐含假设「一个 Run 只进一次 impl」。根因位置：src/workflow_loop/verification.py clear_stage_gates（stage.code_baseline_hash = None）+ src/workflow_loop/cli.py _freeze_impl_code_baseline / ensure_impl_recovery_baseline 守卫。根因证据：沙盒 /tmp/wf_repro_impl2 实测两次冻结与 diff 相反结果；本 Run journal 11:56 记录过首次入场基线哈希 f4328fab…，退回后 state 里 impl.code_baseline_hash 为 None 而 meta 快照仍是首冻内容。 |
| BUG-05 | impl 第二道门对「登记了实施结果但未检测到变化」的文件无条件报错，报错文案却承诺「补充复用说明，或删除该条实际改动记录」两条出路；实际代码里不存在任何读取复用说明的豁免分支，按提示补了说明仍报错——提示与实现脱节。 | 审阅 rollback.validate_actual_implementation_changes_report 的 recorded_paths - actual 循环（期望文案含「或明确说明这是复用的既有实现」），构造登记未变化文件且修改理由写明复用既有实现的 impl_record 表，调用该报告函数 | 无论实施结果行写什么复用说明，该文件仍无条件产生 impl.actual_changes.recorded_without_change 错误项，门禁失败。 | 报错文案承诺的出路真实存在：实施结果该行修改理由写明「复用既有实现」时豁免该项；未写明的仍报错，防止把无关旧文件冒充本轮实现。 | 根因说明：expected/next_action 文案按「允许复用说明」设计，但循环体对每个未检出变化的登记文件直接 add_error，没有任何判定分支读取说明内容——提示实现了承诺的一条不存在的出路。根因位置：src/workflow_loop/rollback.py validate_actual_implementation_changes_report 中 for path in sorted(recorded_paths - actual) 循环（约 1632-1644 行）。根因证据：函数源码通读无豁免分支；沙盒登记带复用说明的行后调用仍返回该错误项。 |

## 缺陷说明

- 三个缺陷同根：验收计划环节把 state.topics 当作唯一主题事实源，而把新主题写进 state.topics 的注册动作只存在于第三道门 --confirmed 内部；第二道门却要求校验集与 acceptance/索引.md 完全一致。于是「索引加了新主题」这一合法操作在该环节形成互相等待：第二道门等 state 先更新，state 等第三道门，第三道门等第二道门。
- 真实触发场景：产品变更轮次推进过 acceptance_plan 后 workflow return 退回补充新验收主题（本仓库 v0.3.6「删除进废纸篓并入当前轮次」轮即为实例），当时通过程序 API 手工提前执行第三道门的主题确定副作用才走通。
- 缺陷一为死锁（无产品内绕行手段）；缺陷二无绕行（追踪表行只能手工按 ensure_workflow_section 初值规则补写）；缺陷三有官方绕行（scaffold --topic）但与其他两项同根，一并对齐口径。
- BUG-04 与 BUG-05 同根：程序假设「一个 Run 只进一次 impl」。退回重走时第二次进入重新冻结基线，把第一次实施的改动在校验语义上抹平（57 项误报）；同时报错文案承诺的「复用说明」豁免没有任何实现，按提示补说明仍报错。两条本应互补的出路都失效。修复方向经用户确认：甲为主（同一 Run 重进 impl 继承首次入场基线，从源头消除误报）、乙为辅（真正实现复用说明豁免作防御兜底）。

## 真实复现条件

- 运行环境：macOS，全局 workflow 命令（uv editable 安装，加载本仓库 src/workflow_loop 真实源码，workflow-loop 0.3.6）；复现沙盒 /tmp/wf_repro_deadlock
- 真实输入：intent=product_change 的 acceptance_plan 阶段状态，state.topics 为 2 个已注册旧主题（经 register_topics 真实写入 project.json），acceptance/索引.md 含 3 个主题（第 3 个为主题历史中未使用过的新主题），需求交付追踪表章节已存在且仅含 2 个旧主题行
- 复现前提与用户场景一致：workflow return 退回 acceptance_plan 后 state.topics 不被清空，保留退回前已确定的主题；本仓库 v0.3.6「删除进废纸篓并入当前轮次」轮真实走过该路径并靠手工提前执行第三道门副作用才走通
- BUG-04/05 复现环境：/tmp/wf_repro_impl2 沙盒项目 + 真实函数 cli.ensure_impl_recovery_baseline、verification.clear_stage_gates、rollback.validate_actual_implementation_changes_report、actual_implementation_paths_since_entry；快照A/B 对同一文件 diff 结果相反（A 检出、B 漏检）。
- 第二遍复核补充事实：同一主题在第一遍 reproduce 生成的缺陷文档文件名（无 _2 后缀）与验收主题经第三道门注册后的稳定文件标识（退回…_2）不一致，根因是 bug 类文件标识先占用了同名标识、topic 类注册时碰撞加 _2；该不一致导致 bug/索引.md 出现同一主题双行、旧缺陷文档成为孤儿。已按规范路径（_2 版本）清理：删除孤儿文档与索引旧行，acceptance_plan 表和追踪表中指向旧文件名的链接统一改为 _2 路径。

## 根因证据

- stages.py:333 原文 topics = current_workflow_topics(project_root) or candidate_topics(project_root)；topic.py:114 candidate_topics 实现为 [t for t in 索引主题 if t in current or t not in history]，且内部先调 current_workflow_topics——即使交换 or 顺序，旧主题仍被保留（t in current 分支），复核旧轮次结果不变。
- artifact_validation.py 校验 set(索引主题) != set(校验集) 即报「主题必须覆盖当前工作流全部主题」；沙盒第二道门实际输出该报错且校验集恰为 state 的 2 个旧主题。
- cli.py 第三道门 --confirmed 内「主题确定」逻辑（new_topics 计算、register_topics、wf_state.topics = topics）位于第二道门凭据检查之后；沙盒直接执行 workflow gate acceptance_plan --confirmed 输出「第二道程序校验还没有通过」，state.topics 未变。
- traceability.py ensure_workflow_section 在 _workflow_heading_pattern 命中后 return False；沙盒直接调用返回 False 且新主题不在追踪表。
- records.py:2094 ensure_stage_tables 的 topics = current_workflow_topics(project_root)；沙盒 workflow scaffold 只建 2 个旧主题表。
- 本 Run 自身证据：journal 2026-09-01T11:56 记录「实施代码入场基线」哈希 f4328fab…；12:48 流程退回后 state.json 中 stages.impl.code_baseline_hash=null，而 meta 的 impl_complete_baseline_snapshot 仍是首次冻结内容——下次进 impl 时 ensure_impl_recovery_baseline 将重算并覆盖它。

## 修复仍存在的不确定性

- 文件标识碰撞产生孤儿文档与索引双行的问题本身不在本轮 5 个缺陷修复范围内（本轮按人工清理走通）；已在 BUG-04/05 修复验证中确认基线继承与复用豁免两个改法在沙盒用真实函数可行。

## 修复与验收结果

- 本节由实施、测试与主题验收阶段按实际结果追加。