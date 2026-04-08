"""
store/workspace.py
工作区文件（TODO / NOTES / SUMMARY / ERRORS）的持久化读写。
保留与原 executor.py 相同的文件名语义，但存入 SQLite 而非磁盘。
"""

from __future__ import annotations

from datetime import datetime, timezone

from store.db import get_db

_VALID_FILES = {
    "TODO.md",
    "NOTES.md",
    "SUMMARY.md",
    "ERRORS.md",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def read_workspace_file(session_id: str, filename: str) -> str:
    if filename not in _VALID_FILES:
        return f"ERROR: 不支持的文件名 {filename}"
    async with get_db() as db:
        async with db.execute(
            "SELECT content FROM workspace WHERE session_id=? AND filename=?",
            (session_id, filename),
        ) as cur:
            row = await cur.fetchone()
            return row["content"] if row else f"（{filename} 尚无内容）"


async def write_workspace_file(session_id: str, filename: str, content: str) -> None:
    async with get_db() as db:
        await db.execute(
            """INSERT INTO workspace (session_id, filename, content, updated_at)
               VALUES (?,?,?,datetime('now'))
               ON CONFLICT(session_id, filename)
               DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
            (session_id, filename, content),
        )
        await db.commit()


async def append_workspace_file(session_id: str, filename: str, entry: str) -> None:
    existing = await read_workspace_file(session_id, filename)
    if existing.startswith("（"):
        existing = f"# {filename}\n"
    await write_workspace_file(session_id, filename, existing + f"\n## {_now()}\n{entry}\n")


# ── 工具函数（供 executor 调用）──────────────────────────────

async def update_todo(session_id: str, content: str) -> str:
    if not content.strip():
        return "ERROR: content 不能为空"
    done    = content.count("- [x]")
    pending = content.count("- [ ]")
    text    = f"# Todo List\n_更新于 {_now()}_\n\n{content.strip()}\n"
    await write_workspace_file(session_id, "TODO.md", text)
    return f"✅ TODO.md 已更新（已完成 {done} 项，待完成 {pending} 项）"


async def append_note(session_id: str, note: str) -> str:
    if not note.strip():
        return "ERROR: note 不能为空"
    await append_workspace_file(session_id, "NOTES.md", note.strip())
    return "✅ 已记录到 NOTES.md"


async def record_error(session_id: str, command: str, error: str) -> None:
    entry = f"**命令**: `{command[:300]}`\n**错误**: {error[:600]}"
    await append_workspace_file(session_id, "ERRORS.md", entry)


async def has_failed_before(session_id: str, command: str) -> bool:
    content = await read_workspace_file(session_id, "ERRORS.md")
    return command[:80] in content
