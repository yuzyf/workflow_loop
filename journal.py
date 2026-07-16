"""
journal.py：journal.jsonl 的追加模块。

职责：
- 把 workflow.py 发生的每个动作追加到 journal.jsonl
- append-only，不重写、不删除、不查询（查询是 later）
- 每条一行 JSON，UTF-8，含时间戳、action 类型、actor

设计模式：
- 用 dataclass 做 journal entry 的数据模型
- 用函数封装追加逻辑，调用方传 dict 即可，不用管 JSON 序列化

为什么用 JSONL 不用 markdown：
- append-only：每条追加一行，不重写整个文件（安全、快）
- crash-safe：写一半挂了最多污染一行
- streamable：可以 tail 看最新、grep 搜关键字
- schema 灵活：每条 action 不同、payload 不同，不用固定 schema
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


# journal.jsonl 的存放路径：被管理项目的 .workflow_loop/journal.jsonl
JOURNAL_FILE = os.path.join(".workflow_loop", "journal.jsonl")


def _now_iso() -> str:
    """生成 ISO 8601 UTC 时间戳，microsecond=0。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_entry(project_root: str, action: str, actor: str, **payload) -> None:
    """往 journal.jsonl 追加一条记录。

    参数：
    - project_root：被管理项目的根目录
    - action：动作类型（中文受控词表，如"工作流启动"/"门禁代码校验"等）
    - actor：谁干的（"ai" / "user" / "workflow.py"）
    - **payload：动作特定字段（如 stage="spec", passed=True, details="文件存在"）

    追加格式：一行一个 JSON 对象，UTF-8，ensure_ascii=False 让中文不被转义。
    """
    # 拼出 journal.jsonl 的完整路径
    path = os.path.join(project_root, JOURNAL_FILE)
    # 确保目录存在（第一次写时 .workflow_loop/ 可能还没建）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 组装 entry：ts + action + actor + payload 里的所有字段
    entry = {"ts": _now_iso(), "action": action, "actor": actor}
    # 把 payload 里的额外字段合并进 entry
    entry.update(payload)
    # 追加写：mode="a" 追加，不覆盖
    # 每条一行 JSON + 换行，就是 JSONL 格式
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent(project_root: str, count: int = 10) -> list[dict]:
    """读最近 count 条 journal 记录，供 status 命令用。
    读整个文件、split 行、取最后 count 条、parse JSON。
    穿刺阶段 journal 不会很大，全读没问题。"""
    path = os.path.join(project_root, JOURNAL_FILE)
    # 文件不存在说明还没 start，返回空列表
    if not os.path.exists(path):
        return []
    # 读整个文件
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    # 去掉空行、parse JSON、取最后 count 条
    entries = []
    for line in lines:
        line = line.strip()
        if line:  # 跳过空行
            entries.append(json.loads(line))
    return entries[-count:] if count > 0 else entries
