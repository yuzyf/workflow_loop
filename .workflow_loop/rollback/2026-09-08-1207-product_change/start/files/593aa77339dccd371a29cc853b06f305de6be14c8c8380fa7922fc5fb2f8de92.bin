# 【主题测试结果】从当前项目强制卸载 Workflow Loop

- 工作流编号：2026-08-04-0950-product_change
- 验收主题：从当前项目强制卸载 Workflow Loop
- 自动化测试结果：通过
- 人工验收状态：待主题验收
- 测试完成时间：2026-08-05T06:14:37+00:00

## 1. 测试依据

- [验收计划](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md)
- [测试计划](./从当前项目强制卸载_Workflow_Loop_测试计划.md)
- [实施计划和记录](../impl/从当前项目强制卸载_Workflow_Loop_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

## 2. 测试环境和执行说明

- 本主题执行范围：TC-01 至 TC-08。
- 执行顺序：TC-01 先于 TC-03；TC-03 先于 TC-07；其它测试项无前置依赖。
- 运行环境：平台=darwin（macOS）；可执行文件=.venv/bin/python；Python 3.13.12；项目根；测试使用临时项目、隔离工具目录和故障替身。
- 未执行项：暂无；旧版脚本在三平台的人工观察在主题验收阶段交接。

## 3. 测试项结果

### TC-01：项目卸载范围和取消保持零修改

- 对应验收条件：[AC-01：根目录检查和一次确认](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-01)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_uninstall_scope_cancel_and_child_directory_are_safe"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_uninstall_scope_cancel_and_child_directory_are_safe"]
- 机器记录编号：RUN-20260805T061433+0000-067e2498
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:33+00:00
- 结束时间：2026-08-05T06:14:34+00:00
- 时长（秒）：0.204
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.05s\n"
- 输出哈希：5b19689a97d618d5cdfce632de67285a8efa3c57100a80350a5bb7ca9e05ae34
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明只有项目根允许执行，错误目录和取消确认都不删除文件。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061433+0000-067e2498；退出码 0，输出末尾为 1 passed。

### TC-02：所有轮次状态均可强制卸载

- 对应验收条件：[AC-02：任何轮次状态都能强制卸载](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-02)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_uninstall_ignores_every_run_status"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_uninstall_ignores_every_run_status"]
- 机器记录编号：RUN-20260805T061434+0000-9264244c
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:34+00:00
- 结束时间：2026-08-05T06:14:34+00:00
- 时长（秒）：0.146
- 退出码：0
- 输出摘要："...                                                                      [100%]\n3 passed in 0.04s\n"
- 输出哈希：86288ee89a493b657a4f02c2118272c4f6a9a7afa049f10741e60f3a564db934
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：参数化测试的三个轮次状态全部通过，证明卸载不读取状态来阻止强制删除，也不恢复业务修改。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061434+0000-9264244c；退出码 0，输出末尾为 3 passed。

### TC-03：删除完整或部分项目管理内容

- 对应验收条件：[AC-03：项目管理内容按固定范围删除](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-03)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_uninstall_removes_only_fixed_paths_and_unlinks_symlinks"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_uninstall_removes_only_fixed_paths_and_unlinks_symlinks"]
- 机器记录编号：RUN-20260805T061434+0000-f01ba262
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:34+00:00
- 结束时间：2026-08-05T06:14:34+00:00
- 时长（秒）：0.13
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.03s\n"
- 输出哈希：35d86279d96ed65491ba8ff0748e1c8e7891711531404dc5d4b9cd6ae33de3ec
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明完整或部分残留的固定管理路径都会删除，符号链接只解除链接，不跟随删除目标。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061434+0000-f01ba262；退出码 0，输出末尾为 1 passed。

### TC-04：项目保留内容和全局命令不受影响

- 对应验收条件：[AC-04：项目业务和正式产物保持不变](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-04)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_uninstall_preserves_business_artifacts_and_global_command"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_uninstall_preserves_business_artifacts_and_global_command"]
- 机器记录编号：RUN-20260805T061434+0000-0ea62de1
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:34+00:00
- 结束时间：2026-08-05T06:14:34+00:00
- 时长（秒）：0.137
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.04s\n"
- 输出哈希：f4c77b58e2280613a49ba18da1c4a02d440e862c49a6c8fe5daaf277333ff99d
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明业务代码、测试、版本控制标记、正式产物和电脑全局命令均未被项目卸载改变。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061434+0000-0ea62de1；退出码 0，输出末尾为 1 passed。

### TC-05：旧版本通过两种脚本直接卸载

- 对应验收条件：[AC-05：旧版本无需先升级即可卸载](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-05)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/test_maintenance_scripts.py::test_legacy_project_uninstall_script_never_upgrades_global_command"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance_scripts.py::test_legacy_project_uninstall_script_never_upgrades_global_command"]
- 机器记录编号：RUN-20260805T061434+0000-ecd5787c
- 工作目录：项目根
- 超时（秒）：300
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:34+00:00
- 结束时间：2026-08-05T06:14:36+00:00
- 时长（秒）：2.206
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 2.10s\n"
- 输出哈希：207d75cc7cdb9d37eeda57d787b238701f7288959f0c55ac0839b7988e96d460
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明旧版项目可以直接使用旧版项目卸载脚本，不先升级全局命令。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061434+0000-ecd5787c；退出码 0，输出末尾为 1 passed。

### TC-06：重复卸载、部分残留和删除故障可重试

- 对应验收条件：[AC-06：重复卸载和失败结果可以继续处理](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-06)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_uninstall_failure_reports_residue_and_retry_finishes"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_uninstall_failure_reports_residue_and_retry_finishes"]
- 机器记录编号：RUN-20260805T061436+0000-2c1ba1ca
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:36+00:00
- 结束时间：2026-08-05T06:14:36+00:00
- 时长（秒）：0.121
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.03s\n"
- 输出哈希：35d86279d96ed65491ba8ff0748e1c8e7891711531404dc5d4b9cd6ae33de3ec
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明完全未安装按成功处理，失败时保留未删项并报告，解除故障后可继续清理。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061436+0000-2c1ba1ca；退出码 0，输出末尾为 1 passed。

### TC-07：卸载后重新安装得到全新状态

- 对应验收条件：[AC-07：重新安装和公开卸载入口符合边界](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-07)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_project_reinstall_after_uninstall_starts_fresh"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_project_reinstall_after_uninstall_starts_fresh"]
- 机器记录编号：RUN-20260805T061436+0000-e5c7a363
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:36+00:00
- 结束时间：2026-08-05T06:14:36+00:00
- 时长（秒）：0.136
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.05s\n"
- 输出哈希：5b19689a97d618d5cdfce632de67285a8efa3c57100a80350a5bb7ca9e05ae34
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明卸载后重新安装建立当前版本的全新项目状态，不带回旧轮次、历史或回退资料。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061436+0000-e5c7a363；退出码 0，输出末尾为 1 passed。

### TC-08：卸载发布资产和 README 项目入口完整

- 对应验收条件：[AC-07：重新安装和公开卸载入口符合边界](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md#ac-07)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/test_release_workflow.py::test_project_uninstall_release_assets_and_readme_boundary_are_complete"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_release_workflow.py::test_project_uninstall_release_assets_and_readme_boundary_are_complete"]
- 机器记录编号：RUN-20260805T061436+0000-d6e49bd2
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:36+00:00
- 结束时间：2026-08-05T06:14:37+00:00
- 时长（秒）：0.133
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.04s\n"
- 输出哈希：f4c77b58e2280613a49ba18da1c4a02d440e862c49a6c8fe5daaf277333ff99d
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明正式发布附件包含两个卸载脚本，README 明确项目卸载命令、删除范围、保留范围和不可恢复边界。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061436+0000-d6e49bd2；退出码 0，输出末尾为 1 passed。

## 4. 人工验收交接

- 人工验收对象：macOS、Linux、Windows PowerShell 7 和 Windows PowerShell 5.1 上的旧版本项目卸载脚本。
- 人工检查方法：在主题验收阶段从旧版本项目分别运行对应脚本，观察一次确认、固定删除清单、保留内容、真实退出码和失败重试结果；核对发布附件和 README。
- 自动化已经证明：本地固定范围、任意轮次状态、保留范围、旧版脚本调用边界、失败重试、重装和发布入口均通过。
- 还需要用户确认：四种托管环境的真实脚本输出、退出码、删除清单和业务哨兵文件保留情况。
- 人工结果填写位置：`acceptance/从当前项目强制卸载_Workflow_Loop_验收结果.md`

## 5. 未通过或阻塞

暂无

## 6. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/从当前项目强制卸载_Workflow_Loop_验收计划.md) | 说明什么算完成 |
| 上游 | [测试计划](./从当前项目强制卸载_Workflow_Loop_测试计划.md) | 说明本次覆盖哪些测试项 |
| 上游 | [实施记录](../impl/从当前项目强制卸载_Workflow_Loop_实施记录.md) | 说明本次代码怎样实现 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |
| 下游 | [主题验收](../acceptance/从当前项目强制卸载_Workflow_Loop_验收结果.md) | 混合测试在这里接收人工确认 |
