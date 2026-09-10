# 主题：临时产物不再卡实施门禁
# Workflow-Test: TC-01 非代码临时文件不算实际改动
# 产品入口：workflow gate impl（实施门禁实际改动清单）
# 代码入口：src/workflow_loop/rollback.py::list_actual_working_tree_changes
# 测试入口：tests/test_gate_tmp_artifacts.py::test_html_prototype_not_counted_as_actual_change
# 准备数据：Git 仓库内建一个进场后新增的未提交 HTML 原型图和真实代码文件
# 执行动作：调用实际改动清单读取函数
# 预期结果（关键断言）：原型图不在实际改动清单，代码文件在清单，输出说明白名单口径
# 预期证据：pytest JUnit XML 报告
import os
import subprocess

from workflow_loop import rollback as rollback_mod


def _git_init_with_commit(root, filename, content):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    path = os.path.join(root, filename)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(content)
    subprocess.run(["git", "add", filename], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return path


def test_html_prototype_not_counted_as_actual_change(tmp_path):
    """AC-01/AC-02/AC-04：原型图不算实际改动；草稿目录豁免；提示不阻塞。"""
    root = str(tmp_path)
    _git_init_with_commit(root, "code_file.py", "print('base')\n")

    # 场景一：项目根目录的未提交 HTML 原型图（AC-01）
    prototype = os.path.join(root, "原型.html")
    with open(prototype, "w", encoding="utf-8") as stream:
        stream.write("<html><body>prototype</body></html>\n")

    # 场景二：修改真实代码文件（应照常识别）
    with open(os.path.join(root, "code_file.py"), "a", encoding="utf-8") as stream:
        stream.write("print('changed')\n")

    changes, detail = rollback_mod.list_actual_working_tree_changes(root)
    assert changes is not None
    assert "code_file.py" in changes, "代码文件必须照常算实际改动"
    assert "原型.html" not in changes, "HTML 原型图不能算实际改动"
    assert "白名单" in detail, "输出说明应标注白名单口径"
    assert "原型.html" in detail, "疑似临时产物应附存放约定提示（AC-04）"


def test_scratch_directory_excluded_from_changes(tmp_path):
    """AC-02：轮次草稿目录内的文件完全不参与检查。"""
    root = str(tmp_path)
    _git_init_with_commit(root, "code_file.py", "print('base')\n")

    scratch_dir = os.path.join(root, ".workflow_loop", "scratch", "wf-1")
    os.makedirs(scratch_dir, exist_ok=True)
    with open(os.path.join(scratch_dir, "原型.html"), "w", encoding="utf-8") as stream:
        stream.write("<html></html>\n")
    with open(os.path.join(scratch_dir, "notes.md"), "w", encoding="utf-8") as stream:
        stream.write("draft\n")

    changes, detail = rollback_mod.list_actual_working_tree_changes(root)
    assert changes is not None
    assert changes == [], "草稿目录内容不应出现在改动清单"
    assert "原型" not in detail and "notes" not in detail, (
        "草稿目录内容不应出现在提示中"
    )


def test_extra_code_suffixes_extend_whitelist(tmp_path):
    """AC-03：项目级登记 .html 后缀后，HTML 修改被算成实际改动。"""
    root = str(tmp_path)
    _git_init_with_commit(root, "page.html", "<html>base</html>\n")

    # 未登记时：.html 修改不算改动
    with open(os.path.join(root, "page.html"), "w", encoding="utf-8") as stream:
        stream.write("<html>changed</html>\n")
    changes, _ = rollback_mod.list_actual_working_tree_changes(root)
    assert changes is not None
    assert "page.html" not in changes, "未登记后缀时 .html 不算实际改动"

    # 登记后：.html 修改被算成改动
    project_dir = os.path.join(root, ".workflow_loop")
    os.makedirs(project_dir, exist_ok=True)
    with open(os.path.join(project_dir, "project.json"), "w", encoding="utf-8") as stream:
        stream.write('{"installer_version": "0.3.9", "extra_code_suffixes": [".html"]}\n')
    changes, _ = rollback_mod.list_actual_working_tree_changes(root)
    assert changes is not None
    assert "page.html" in changes, "登记 .html 后缀后真实修改必须算实际改动"
