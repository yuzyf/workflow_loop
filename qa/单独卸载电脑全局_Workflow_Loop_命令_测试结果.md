# 【主题测试结果】单独卸载电脑全局 Workflow Loop 命令

- 工作流编号：2026-08-04-0950-product_change
- 验收主题：单独卸载电脑全局 Workflow Loop 命令
- 自动化测试结果：通过
- 人工验收状态：待主题验收
- 测试完成时间：2026-08-05T06:14:40+00:00

## 1. 测试依据

- [验收计划](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md)
- [测试计划](./单独卸载电脑全局_Workflow_Loop_命令_测试计划.md)
- [实施计划和记录](../impl/单独卸载电脑全局_Workflow_Loop_命令_实施记录.md)
- [需求交付追踪表](../需求交付追踪表.md)

## 2. 测试环境和执行说明

- 本主题执行范围：TC-01 至 TC-06。
- 执行顺序：TC-03 先于 TC-05；其它测试项无前置依赖。
- 运行环境：平台=darwin（macOS）；可执行文件=.venv/bin/python；Python 3.13.12；项目根；测试使用隔离命令目录、工具目录和 PATH 样本。
- 未执行项：暂无；Windows PowerShell 5.1/7 的真实自卸载在主题验收阶段交接。

## 3. 测试项结果

### TC-01：全局范围警告和取消保持零修改

- 对应验收条件：[AC-01：全局范围单独确认并明确警告](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-01)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_global_uninstall_warning_cancel_and_single_confirmation_are_read_only"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_global_uninstall_warning_cancel_and_single_confirmation_are_read_only"]
- 机器记录编号：RUN-20260805T061437+0000-f2ff1054
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:37+00:00
- 结束时间：2026-08-05T06:14:37+00:00
- 时长（秒）：0.122
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.03s\n"
- 输出哈希：35d86279d96ed65491ba8ff0748e1c8e7891711531404dc5d4b9cd6ae33de3ec
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明全局卸载会先说明电脑级删除范围和其它项目影响，只确认一次；取消后命令、工具、PATH 和项目均不变。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061437+0000-f2ff1054；退出码 0，输出末尾为 1 passed。

### TC-02：全局卸载不访问或删除项目

- 对应验收条件：[AC-02：全局卸载绝不扩大到项目](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-02)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance.py::test_global_uninstall_never_calls_project_scope"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance.py::test_global_uninstall_never_calls_project_scope"]
- 机器记录编号：RUN-20260805T061437+0000-72be9856
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:37+00:00
- 结束时间：2026-08-05T06:14:37+00:00
- 时长（秒）：0.115
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.03s\n"
- 输出哈希：35d86279d96ed65491ba8ff0748e1c8e7891711531404dc5d4b9cd6ae33de3ec
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明全局卸载不调用项目范围扫描，不读取、修改或删除任意临时项目。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061437+0000-72be9856；退出码 0，输出末尾为 1 passed。

### TC-03：命令和命令搜索路径按来源删除

- 对应验收条件：[AC-03：只删除来源明确的电脑级内容](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-03)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance_scripts.py::test_global_uninstall_removes_only_proven_path_contribution"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance_scripts.py::test_global_uninstall_removes_only_proven_path_contribution"]
- 机器记录编号：RUN-20260805T061437+0000-1a14e98c
- 工作目录：项目根
- 超时（秒）：300
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:37+00:00
- 结束时间：2026-08-05T06:14:39+00:00
- 时长（秒）：2.169
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 2.08s\n"
- 输出哈希：bdc4a033a16622e249556c78c42b2f18fdbdb2bfa4c14d4977c44133effefef7
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明 Workflow Loop 写入的命令和 PATH 贡献可以删除，预先存在或来源不明的路径保留并报告。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061437+0000-1a14e98c；退出码 0，输出末尾为 1 passed。

### TC-04：两种 Windows PowerShell 完成命令自卸载

- 对应验收条件：[AC-04：受支持的 Windows PowerShell 能完成自卸载](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-04)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/test_release_workflow.py::test_windows_powershell_matrix_covers_global_self_uninstall_contract"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_release_workflow.py::test_windows_powershell_matrix_covers_global_self_uninstall_contract"]
- 机器记录编号：RUN-20260805T061439+0000-dd32f870
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:39+00:00
- 结束时间：2026-08-05T06:14:39+00:00
- 时长（秒）：0.112
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.02s\n"
- 输出哈希：a71df3ef716cabe43ead70bd8311cda3aeadcb986bea501da0ea9262f31c3925
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：本地测试通过，证明发布任务同时配置 PowerShell 7 与 Windows PowerShell 5.1、父进程等待、标准输出/错误输出分流和真实退出码处理；未证明 Windows 托管运行结果。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061439+0000-dd32f870；退出码 0，输出末尾为 1 passed。

### TC-05：全局部分删除失败后报告并重试

- 对应验收条件：[AC-05：部分失败可以核实和重试](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-05)
- 测试方式：自动化测试
- 测试入口：["tests/test_maintenance_scripts.py::test_global_uninstall_failure_keeps_residue_and_retry_cleans_it"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_maintenance_scripts.py::test_global_uninstall_failure_keeps_residue_and_retry_cleans_it"]
- 机器记录编号：RUN-20260805T061439+0000-5ca8a941
- 工作目录：项目根
- 超时（秒）：300
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:39+00:00
- 结束时间：2026-08-05T06:14:40+00:00
- 时长（秒）：0.991
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.91s\n"
- 输出哈希：85c3e34df3337375b023792993d5880ace51098d60f8a6d4b62bb027a039340d
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明部分删除失败时保留残留清单和原因，解除故障后重试只清理剩余内容。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061439+0000-5ca8a941；退出码 0，输出末尾为 1 passed。

### TC-06：README 区分两种卸载范围

- 对应验收条件：[AC-06：公开说明区分项目卸载和全局卸载](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md#ac-06)
- 测试方式：自动化测试 + 人工验收
- 测试入口：["tests/test_release_workflow.py::test_readme_separates_project_and_global_uninstall_boundaries"]
- 执行命令：[".venv/bin/python","-m","pytest","-q","tests/test_release_workflow.py::test_readme_separates_project_and_global_uninstall_boundaries"]
- 机器记录编号：RUN-20260805T061440+0000-6447d996
- 工作目录：项目根
- 超时（秒）：120
- 运行环境：平台=darwin；可执行文件=.venv/bin/python
- 开始时间：2026-08-05T06:14:40+00:00
- 结束时间：2026-08-05T06:14:40+00:00
- 时长（秒）：0.106
- 退出码：0
- 输出摘要：".                                                                        [100%]\n1 passed in 0.02s\n"
- 输出哈希：a71df3ef716cabe43ead70bd8311cda3aeadcb986bea501da0ea9262f31c3925
- 输出字节数：98
- 产品代码哈希：96884caf6b554f90522cfeaf3bedf56f857658cdb38ff9e69324cd927285581f
- 测试代码哈希：8ab7d2c3d34c7f31fc67a4af5420c4be3708dfe1176d15998f6fe95b1165415b
- 实际结果：测试通过，证明 README 分开说明项目卸载和全局卸载命令、删除范围、保留范围以及全局卸载对依赖项目的影响。
- 自动化测试结果：通过
- 证据：机器记录 RUN-20260805T061440+0000-6447d996；退出码 0，输出末尾为 1 passed。

## 4. 人工验收交接

- 人工验收对象：Windows PowerShell 5.1/7 全局自卸载脚本和 README 对用户的范围说明。
- 人工检查方法：在主题验收阶段核对两个 Windows 托管任务的原始输出、父命令退出后的命令入口和工具目录、真实退出码，再检查 README 的两种命令和影响警告。
- 自动化已经证明：本地全局范围隔离、来源明确的 PATH 清理、失败重试、PowerShell 矩阵配置和 README 文本边界均通过。
- 还需要用户确认：Windows 两种 PowerShell 的真实自卸载结果、输出流未误报和退出码，以及公开说明是否满足使用边界。
- 人工结果填写位置：`acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收结果.md`

## 5. 未通过或阻塞

暂无

## 6. 上下游文档

| 关系 | 文档 | 说明 |
|---|---|---|
| 上游 | [验收计划](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收计划.md) | 说明什么算完成 |
| 上游 | [测试计划](./单独卸载电脑全局_Workflow_Loop_命令_测试计划.md) | 说明本次覆盖哪些测试项 |
| 上游 | [实施记录](../impl/单独卸载电脑全局_Workflow_Loop_命令_实施记录.md) | 说明本次代码怎样实现 |
| 全局 | [需求交付追踪表](../需求交付追踪表.md) | 查看完整链路 |
| 下游 | [主题验收](../acceptance/单独卸载电脑全局_Workflow_Loop_命令_验收结果.md) | 混合测试在这里接收人工确认 |
