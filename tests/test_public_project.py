import ast
from email import policy
from email.message import Message
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION = "为 AI 驱动的软件开发提供有状态、可验证、可回退的工作流管理。"
REPOSITORY_URL = "https://github.com/yuzyf/workflow_loop"
VERSION = "0.2.0"


def _project_metadata() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def _literal_assignments(path: Path) -> dict[str, object]:
    assignments: dict[str, object] = {}
    for statement in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            assignments[target.id] = ast.literal_eval(statement.value)
        except (ValueError, TypeError):
            continue
    return assignments


def _assert_distribution_metadata(metadata: Message, readme: str) -> None:
    assert metadata["Name"] == "workflow-loop"
    assert metadata["Version"] == VERSION
    assert metadata["Summary"] == DESCRIPTION
    assert metadata["Author"] == "yuzyf"
    assert metadata["Requires-Python"] == ">=3.11"
    assert metadata["Description-Content-Type"] == "text/markdown"
    assert metadata["License-Expression"] == "MIT"
    assert metadata.get_all("License-File") == ["LICENSE"]
    assert set(metadata.get_all("Project-URL", [])) == {
        f"Homepage, {REPOSITORY_URL}",
        f"Repository, {REPOSITORY_URL}",
    }
    description_bytes = metadata.get_payload(decode=True)
    assert isinstance(description_bytes, bytes)
    assert description_bytes.decode("utf-8").strip() == readme.strip()


def _distribution_metadata_evidence(metadata: Message) -> dict:
    return {
        "author": metadata["Author"],
        "description_content_type": metadata["Description-Content-Type"],
        "license_expression": metadata["License-Expression"],
        "license_files": metadata.get_all("License-File"),
        "name": metadata["Name"],
        "project_urls": sorted(metadata.get_all("Project-URL", [])),
        "requires_python": metadata["Requires-Python"],
        "summary": metadata["Summary"],
        "version": metadata["Version"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _print_evidence(label: str, evidence: dict) -> None:
    print(f"{label}: {json.dumps(evidence, ensure_ascii=False, sort_keys=True)}")


def test_source_identity_and_current_links_are_consistent():
    """Workflow-Test
    主题：公开项目身份和中文说明保持一致
    测试项：TC-01 当前项目与公开仓库身份一致
    验收条件：AC-01 公开项目身份一致
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：核对源码、命令身份、安装脚本和当前公开链接使用已确认的三种名称映射及新仓库地址
    测试入口：tests/test_public_project.py::test_source_identity_and_current_links_are_consistent
    代码入口：pyproject.toml；src/workflow_loop/__init__.py；src/workflow_loop/cli.py；install.sh；install.ps1；README.md
    """
    configuration = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = configuration["project"]
    package_identity = _literal_assignments(ROOT / "src" / "workflow_loop" / "__init__.py")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    shell_installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    powershell_installer = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")

    assert readme.startswith("# Workflow Loop\n")
    assert (ROOT / "src" / "workflow_loop" / "cli.py").is_file()
    assert project["name"] == "workflow-loop"
    assert configuration["project"]["scripts"] == {
        "workflow": "workflow_loop.cli:main"
    }
    assert package_identity["PRODUCT_NAME"] == "workflow-loop"
    assert package_identity["__version__"] == VERSION
    assert 'PRODUCT_NAME="workflow-loop"' in shell_installer
    assert f'PRODUCT_VERSION="{VERSION}"' in shell_installer
    assert '$ProductName = "workflow-loop"' in powershell_installer
    assert f'$ProductVersion = "{VERSION}"' in powershell_installer

    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (source_path, environment.get("PYTHONPATH", ""))
        if part
    )
    version_result = subprocess.run(
        [sys.executable, "-m", "workflow_loop.cli", "--version"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert version_result.returncode == 0, version_result.stderr
    assert version_result.stdout.strip() == f"workflow-loop {VERSION}"

    current_public_files = {
        "README.md": readme,
        "pyproject.toml": (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        "install.sh": shell_installer,
        "install.ps1": powershell_installer,
        ".github/workflows/release.yml": (
            ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8"),
    }
    assert all("workflow_loop_spike" not in text for text in current_public_files.values())

    project_links = re.findall(
        r"https://github\.com/yuzyf/[^\s)\]?'\"]+", readme
    )
    assert project_links
    assert all(link.startswith(REPOSITORY_URL) for link in project_links)
    assert project["urls"] == {
        "Homepage": REPOSITORY_URL,
        "Repository": REPOSITORY_URL,
    }
    _print_evidence(
        "PUBLIC_SOURCE_IDENTITY",
        {
            "command_identity": version_result.stdout.strip(),
            "current_public_files": sorted(current_public_files),
            "distribution_name": project["name"],
            "display_name": "Workflow Loop",
            "import_package": "workflow_loop",
            "project_urls": project["urls"],
            "script_entry": configuration["project"]["scripts"]["workflow"],
            "version": package_identity["__version__"],
        },
    )


def test_readme_has_the_confirmed_chinese_structure_and_entries():
    """Workflow-Test
    主题：公开项目身份和中文说明保持一致
    测试项：TC-02 README 结构正确且内容可理解
    验收条件：AC-02 中文 README 内容完整
    测试方式：自动化测试 + 人工验收
    测试层级：模块测试
    测试目标：核对中文 README 的徽章、章节、流程、三系统安装入口、源码开发入口、链接和排除内容
    测试入口：tests/test_public_project.py::test_readme_has_the_confirmed_chinese_structure_and_entries
    代码入口：README.md
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    badges = (
        "https://img.shields.io/github/v/release/yuzyf/workflow_loop",
        "https://img.shields.io/pypi/v/workflow-loop",
        "https://img.shields.io/badge/Python-%3E%3D3.11-3776AB",
        "https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-MIT-green",
    )
    assert all(readme.count(badge) == 1 for badge in badges)
    assert f"]({REPOSITORY_URL}/releases)" in readme
    assert "](https://pypi.org/project/workflow-loop/)" in readme

    required_headings = (
        "## 能力与边界",
        "### 能做什么",
        "### 不做什么",
        "## 工作流程",
        "## 环境要求",
        "## 安装 0.2.0",
        "### macOS",
        "### Linux",
        "### 原生 Windows",
        "## 最小使用示例",
        "## 命令概览",
        "## 源码开发",
        "## 仓库结构",
        "## 详细文档",
        "## 许可证",
    )
    assert all(heading in readme for heading in required_headings)

    assert "```mermaid" in readme
    assert "flowchart TD" in readme
    for intent in (
        "from_scratch：从零创建",
        "product_change：修改产品",
        "bugfix：修复缺陷",
        "light_task：无需开发任务",
    ):
        assert intent in readme
    for gate in ("第一道门：讨论完成", "第二道门：程序检查", "第三道门：用户确认"):
        assert gate in readme

    shell_install = (
        "curl -fsSL "
        f"{REPOSITORY_URL}/releases/download/v{VERSION}/install.sh | bash"
    )
    powershell_install = (
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm '
        f'{REPOSITORY_URL}/releases/download/v{VERSION}/install.ps1 | iex"'
    )
    assert readme.count(shell_install) == 2
    assert readme.count(powershell_install) == 1
    assert "latest" in readme and "不会跟随" in readme

    for command in (
        f"git clone {REPOSITORY_URL}.git",
        "cd workflow_loop",
        "uv sync --extra dev",
        "uv run pytest",
        "uv run python -m build",
    ):
        assert command in readme
    for documentation_link in (
        "spec/产品总说明.md",
        "spec/功能_安装到项目.md",
        "spec/代码架构设计.md",
        "DESIGN.md",
        "CONTEXT.md",
        "需求交付追踪表.md",
    ):
        assert f"]({documentation_link})" in readme

    headings = {
        line.strip()
        for line in readme.splitlines()
        if line.startswith("#")
    }
    excluded_headings = {
        "## English README",
        "## 英文 README",
        "## 安装故障手册",
        "## 安装故障排查",
        "## 外部贡献指南",
        "## 贡献指南",
        "## 维护者发布操作",
        "## 发布流程",
    }
    assert headings.isdisjoint(excluded_headings)
    assert "twine upload" not in readme
    assert "gh release create" not in readme
    assert "git tag" not in readme
    _print_evidence(
        "README_STRUCTURE",
        {
            "badges": list(badges),
            "excluded_headings_absent": sorted(excluded_headings),
            "gates": [
                "第一道门：讨论完成",
                "第二道门：程序检查",
                "第三道门：用户确认",
            ],
            "headings": list(required_headings),
            "intents": [
                "from_scratch：从零创建",
                "product_change：修改产品",
                "bugfix：修复缺陷",
            ],
            "install_commands": {
                "linux": shell_install,
                "macos": shell_install,
                "windows": powershell_install,
            },
            "linked_documents": [
                "spec/产品总说明.md",
                "spec/功能_安装到项目.md",
                "spec/代码架构设计.md",
                "DESIGN.md",
                "CONTEXT.md",
                "需求交付追踪表.md",
            ],
            "source_commands": [
                f"git clone {REPOSITORY_URL}.git",
                "cd workflow_loop",
                "uv sync --extra dev",
                "uv run pytest",
                "uv run python -m build",
            ],
        },
    )


def test_license_and_source_distribution_metadata_are_consistent():
    """Workflow-Test
    主题：公开项目身份和中文说明保持一致
    测试项：TC-03 许可证和源码分发元数据一致
    验收条件：AC-03 许可证和分发元数据完整
    测试方式：自动化测试
    测试层级：模块测试
    测试目标：核对根目录 MIT 许可证、版权文字和 Python 源码分发元数据逐项等于已确认内容
    测试入口：tests/test_public_project.py::test_license_and_source_distribution_metadata_are_consistent
    代码入口：LICENSE；pyproject.toml；README.md
    """
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    project = _project_metadata()

    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 yuzyf\n")
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert project == {
        "name": "workflow-loop",
        "version": VERSION,
        "description": DESCRIPTION,
        "readme": "README.md",
        "requires-python": ">=3.11",
        "license": "MIT",
        "license-files": ["LICENSE"],
        "authors": [{"name": "yuzyf"}],
        "dependencies": ["packaging>=24.0"],
        "scripts": {"workflow": "workflow_loop.cli:main"},
        "optional-dependencies": {
            "dev": ["build>=1.2", "pytest>=7.0", "PyYAML>=6.0"]
        },
        "urls": {
            "Homepage": REPOSITORY_URL,
            "Repository": REPOSITORY_URL,
        },
    }
    assert (ROOT / project["readme"]).is_file()
    assert all("workflow_loop_spike" not in url for url in project["urls"].values())
    _print_evidence(
        "SOURCE_DISTRIBUTION_METADATA",
        {
            "license_copyright": "Copyright (c) 2026 yuzyf",
            "license_sha256": hashlib.sha256(
                license_text.encode("utf-8")
            ).hexdigest(),
            "project": project,
        },
    )


def test_built_distributions_include_readme_metadata_and_license(tmp_path: Path):
    """Workflow-Test
    主题：公开项目身份和中文说明保持一致
    测试项：TC-04 构建产物携带正确说明和许可证
    验收条件：AC-03 许可证和分发元数据完整
    测试方式：自动化测试
    测试层级：集成测试
    测试目标：从临时目录中的最终源码真实构建并解析 wheel、sdist 的元数据、中文长说明、许可证和文件清单
    测试入口：tests/test_public_project.py::test_built_distributions_include_readme_metadata_and_license
    代码入口：pyproject.toml；README.md；LICENSE；src/workflow_loop
    """
    source_root = tmp_path / "source"
    source_root.mkdir()
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / filename, source_root / filename)
    shutil.copytree(
        ROOT / "src",
        source_root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )

    distribution_directory = tmp_path / "dist"
    build_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--outdir",
            str(distribution_directory),
        ],
        cwd=source_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert build_result.returncode == 0, (
        f"构建 stdout（标准输出）：\n{build_result.stdout}\n"
        f"构建 stderr（错误输出）：\n{build_result.stderr}"
    )

    wheels = list(distribution_directory.glob("*.whl"))
    source_distributions = list(distribution_directory.glob("*.tar.gz"))
    assert [path.name for path in wheels] == [
        f"workflow_loop-{VERSION}-py3-none-any.whl"
    ]
    assert [path.name for path in source_distributions] == [
        f"workflow_loop-{VERSION}.tar.gz"
    ]

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_files = wheel.namelist()
        metadata_path = next(
            path for path in wheel_files if path.endswith(".dist-info/METADATA")
        )
        license_path = next(
            path for path in wheel_files if path.endswith(".dist-info/licenses/LICENSE")
        )
        metadata = BytesParser(policy=policy.default).parsebytes(
            wheel.read(metadata_path)
        )
        _assert_distribution_metadata(metadata, readme)
        assert wheel.read(license_path).decode("utf-8") == license_text
        assert "workflow_loop/__init__.py" in wheel_files
        wheel_metadata = _distribution_metadata_evidence(metadata)
        wheel_key_files = [
            metadata_path,
            license_path,
            "workflow_loop/__init__.py",
        ]
        wheel_package_data_files = sum(
            path.startswith("workflow_loop/data/") for path in wheel_files
        )

    with tarfile.open(source_distributions[0], mode="r:gz") as source_distribution:
        source_files = source_distribution.getnames()
        archive_root = f"workflow_loop-{VERSION}"
        expected_files = {
            f"{archive_root}/LICENSE",
            f"{archive_root}/README.md",
            f"{archive_root}/PKG-INFO",
            f"{archive_root}/pyproject.toml",
            f"{archive_root}/src/workflow_loop/__init__.py",
        }
        assert expected_files.issubset(source_files)

        package_info_member = source_distribution.extractfile(
            f"{archive_root}/PKG-INFO"
        )
        readme_member = source_distribution.extractfile(
            f"{archive_root}/README.md"
        )
        license_member = source_distribution.extractfile(
            f"{archive_root}/LICENSE"
        )
        assert package_info_member is not None
        assert readme_member is not None
        assert license_member is not None
        package_info = BytesParser(policy=policy.default).parsebytes(
            package_info_member.read()
        )
        _assert_distribution_metadata(package_info, readme)
        assert readme_member.read().decode("utf-8") == readme
        assert license_member.read().decode("utf-8") == license_text
        source_metadata = _distribution_metadata_evidence(package_info)
        source_package_data_files = sum(
            "/src/workflow_loop/data/" in path for path in source_files
        )

    _print_evidence(
        "BUILT_DISTRIBUTIONS",
        {
            "build": {
                "command": [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--sdist",
                    "--outdir",
                    str(distribution_directory),
                ],
                "stderr_tail": build_result.stderr[-2000:],
                "stdout_bytes": len(build_result.stdout.encode("utf-8")),
                "stdout_sha256": hashlib.sha256(
                    build_result.stdout.encode("utf-8")
                ).hexdigest(),
                "stdout_tail": build_result.stdout[-2000:],
            },
            "readme_sha256": hashlib.sha256(readme.encode("utf-8")).hexdigest(),
            "sdist": {
                "bytes": source_distributions[0].stat().st_size,
                "filename": source_distributions[0].name,
                "key_files": sorted(expected_files),
                "metadata": source_metadata,
                "package_data_file_count": source_package_data_files,
                "sha256": _sha256(source_distributions[0]),
                "total_file_count": len(source_files),
            },
            "wheel": {
                "bytes": wheels[0].stat().st_size,
                "filename": wheels[0].name,
                "key_files": wheel_key_files,
                "metadata": wheel_metadata,
                "package_data_file_count": wheel_package_data_files,
                "sha256": _sha256(wheels[0]),
                "total_file_count": len(wheel_files),
            },
        },
    )
