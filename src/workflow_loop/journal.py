import json
import os
from datetime import datetime, timezone

# journal.jsonl 的相对路径（相对于项目根）
# 放在 .workflow_loop/ 下，和 state.json、project.json 同级
JOURNAL_FILE = os.path.join(".workflow_loop", "journal.jsonl")


# 往 journal.jsonl 追加一条记录
# journal 是 append-only 的历史记录（"发生过啥"），不可改
# 和 state.json（"现在在哪"，可重写）分离：崩溃恢复时可以从 journal 重建 state
def append_entry(project_root: str, action: str, actor: str, **kwargs) -> None:
    # 拼出 journal.jsonl 的完整路径
    path = os.path.join(project_root, JOURNAL_FILE)
    # 确保目录存在（第一次写时 .workflow_loop/ 可能还没建）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 组装一条 journal 记录：时间戳 + 动作类型 + 执行者 + 额外字段
    entry = {
        # ISO 8601 UTC 时间戳，去掉微秒让格式更干净
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # 动作类型（中文受控词表：工作流启动/提示词加载/门禁讨论完毕/...）
        "action": action,
        # 执行者：ai / user / workflow.py（谁触发了这个动作）
        "actor": actor,
        # 额外字段（如 stage=xxx, passed=true 等，按 action 类型不同带不同 payload）
        **kwargs,
    }
    # 追加写一行 JSON（不覆盖已有内容），ensure_ascii=False 保留中文
    with open(path, "a", encoding="utf-8") as f:
        # 每条记录一行，jsonl 格式（JSON Lines）
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# 读最近 N 条 journal 记录（status 命令用，默认 10 条）
# 返回 list[dict]，每条是一个 JSON 对象
def read_recent(project_root: str, count: int = 10) -> list[dict]:
    # 拼出 journal.jsonl 的完整路径
    path = os.path.join(project_root, JOURNAL_FILE)
    # 文件不存在说明还没 start 过，返回空列表
    if not os.path.exists(path):
        return []
    # 收集所有记录
    entries = []
    # 逐行读取 jsonl 文件
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # 去掉行首行尾空白
            line = line.strip()
            # 跳过空行
            if line:
                # 解析 JSON 行
                entries.append(json.loads(line))
    # 只返回最后 count 条（最近的记录）
    return entries[-count:]


# 读所有 journal 记录（调试和审计用）
# 返回 list[dict]，按时间顺序（从早到晚）
def read_all(project_root: str) -> list[dict]:
    # 拼出 journal.jsonl 的完整路径
    path = os.path.join(project_root, JOURNAL_FILE)
    # 文件不存在说明还没 start 过，返回空列表
    if not os.path.exists(path):
        return []
    # 收集所有记录
    entries = []
    # 逐行读取 jsonl 文件
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            # 去掉行首行尾空白
            line = line.strip()
            # 跳过空行
            if line:
                # 解析 JSON 行
                entries.append(json.loads(line))
    # 返回所有记录（从早到晚）
    return entries
