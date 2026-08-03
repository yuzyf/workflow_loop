import sys

from workflow_loop.process_runner import ProcessRequest, run_process


TOPIC = "项目修改可恢复且正式测试结果来自真实执行"


def test_process_runner_records_success_and_bounded_machine_facts(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-05 跨平台执行和超时清理
    验收条件：AC-05 程序跨平台真实执行并保存机器事实
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：参数数组不经过 Shell 真实执行并保存平台、路径、摘要和退出码
    测试入口：tests/test_process_runner.py::test_process_runner_records_success_and_bounded_machine_facts
    代码入口：workflow_loop.process_runner.run_process
    """
    result = run_process(
        ProcessRequest(
            argv=[sys.executable, "-c", "print('machine fact')"],
            cwd=str(tmp_path),
            timeout_seconds=5,
        )
    )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.argv == [sys.executable, "-c", "print('machine fact')"]
    assert result.cwd == str(tmp_path)
    assert result.platform == sys.platform
    assert result.output_tail.strip() == "machine fact"
    assert len(result.output_sha256) == 64


def test_process_runner_records_nonzero_exit(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-05 跨平台执行和超时清理
    验收条件：AC-05 程序跨平台真实执行并保存机器事实
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：非零退出保存为失败事实而不是异常丢失
    测试入口：tests/test_process_runner.py::test_process_runner_records_nonzero_exit
    代码入口：workflow_loop.process_runner.run_process
    """
    result = run_process(
        ProcessRequest(
            argv=[sys.executable, "-c", "import sys; print('failed'); sys.exit(7)"],
            cwd=str(tmp_path),
            timeout_seconds=5,
        )
    )

    assert result.status == "failed"
    assert result.exit_code == 7
    assert "failed" in result.output_tail


def test_process_runner_times_out_and_waits_for_cleanup(tmp_path):
    """Workflow-Test
    主题：项目修改可恢复且正式测试结果来自真实执行
    测试项：TC-05 跨平台执行和超时清理
    验收条件：AC-05 程序跨平台真实执行并保存机器事实
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：超时后终止受控进程并返回完整超时机器记录
    测试入口：tests/test_process_runner.py::test_process_runner_times_out_and_waits_for_cleanup
    代码入口：workflow_loop.process_runner.run_process
    """
    result = run_process(
        ProcessRequest(
            argv=[sys.executable, "-c", "import time; print('start', flush=True); time.sleep(30)"],
            cwd=str(tmp_path),
            timeout_seconds=1,
        )
    )

    assert result.status == "timeout"
    assert result.exit_code is None
    assert "start" in result.output_tail
    assert result.finished_at
