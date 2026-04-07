"""
skills/memory.py
记录每个 Skill 历史成功执行的命令，供下次调用时优先参考。

表结构：
  skill_memory(skill_name, command, success_count, last_used_at)

使用方式：
  # 记录一次成功
  record_success("news-aggregator-skill-0.1.0", "python scripts/fetch.py --source all")

  # 查询某个 skill 的成功命令
  get_success_commands("news-aggregator-skill-0.1.0")
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import settings

_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    p = Path(settings.db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_memory_table() -> None:
    """应用启动时调用，确保表存在"""
    with _lock:
        conn = _get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skill_memory (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name    TEXT NOT NULL,
                    command       TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 1,
                    last_used_at  TEXT NOT NULL,
                    UNIQUE(skill_name, command)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sm_skill ON skill_memory(skill_name)"
            )
            conn.commit()
        finally:
            conn.close()


def _normalize_command(command: str) -> str:
    """标准化命令：统一 python3→python，去除多余空格"""
    import re, sys
    cmd = command.strip()
    if sys.platform == "win32":
        cmd = re.sub(r"\bpython3\b", "python", cmd)
    # 合并多余空格
    cmd = re.sub(r" {2,}", " ", cmd)
    return cmd


def record_success(skill_name: str, command: str) -> None:
    """
    记录一条成功命令。
    相同命令再次成功时 success_count +1，并更新 last_used_at。
    记录前先标准化命令格式，避免 python/python3 导致重复记录。
    """
    if not skill_name or not command.strip():
        return
    command = _normalize_command(command)
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _get_conn()
        try:
            conn.execute("""
                INSERT INTO skill_memory(skill_name, command, success_count, last_used_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(skill_name, command)
                DO UPDATE SET
                    success_count = success_count + 1,
                    last_used_at  = excluded.last_used_at
            """, (skill_name, command.strip(), now))
            conn.commit()
        finally:
            conn.close()


def get_success_commands(skill_name: str, limit: int = 3) -> list[dict]:
    """
    返回某个 skill 成功次数最多的前 N 条命令。
    每项：{ command, success_count, last_used_at }
    """
    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute("""
                SELECT command, success_count, last_used_at
                FROM skill_memory
                WHERE skill_name = ?
                ORDER BY success_count DESC, last_used_at DESC
                LIMIT ?
            """, (skill_name, limit)).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def build_memory_hint(skill_name: str) -> str:
    """
    构建注入 system prompt 的经验提示文本。
    无记录时返回空字符串。
    """
    records = get_success_commands(skill_name)
    if not records:
        return ""

    lines = [f"## {skill_name} 历史成功命令（优先使用）"]
    for r in records:
        count = r["success_count"]
        cmd   = r["command"]
        lines.append(f"- （成功 {count} 次）`{cmd}`")
    lines.append("直接使用以上命令，无需重新探索参数。")
    return "\n".join(lines)


def build_all_memory_hints(skill_names: list[str]) -> str:
    """为多个 skill 构建联合提示"""
    hints = []
    for name in skill_names:
        h = build_memory_hint(name)
        if h:
            hints.append(h)
    return "\n\n".join(hints)


def _extract_skill_name_from_path(path: str) -> str:
    """从 SKILL.md 路径提取 skill 目录名"""
    p = Path(path)
    # 取倒数第二段：skills/news-aggregator-0.1.0/SKILL.md → news-aggregator-0.1.0
    if p.name.upper() == "SKILL.MD":
        return p.parent.name
    return p.parent.name