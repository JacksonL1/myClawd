"""
session/store.py
SQLite 的底层读写，只负责 SQL，不含业务逻辑。
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config import settings


def _get_db_path() -> Path:
    p = Path(settings.db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """应用启动时调用，确保表已创建"""
    sql = (Path(__file__).parent.parent / "data" / "init.sql").read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(sql)


# ── Sessions ─────────────────────────────────────────────────────

def upsert_session(
    pk: str,
    workspace_id: str,
    agent_id: str,
    sender_id: str,
    session_id: str,
    title: str | None,
    now: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions
                (id, workspace_id, agent_id, sender_id, session_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, agent_id, sender_id, session_id)
            DO UPDATE SET updated_at = excluded.updated_at,
                          title      = COALESCE(excluded.title, sessions.title)
            """,
            (pk, workspace_id, agent_id, sender_id, session_id, title, now, now),
        )


def get_session_pk(
    workspace_id: str, agent_id: str, sender_id: str, session_id: str
) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM sessions WHERE workspace_id=? AND agent_id=? AND sender_id=? AND session_id=?",
            (workspace_id, agent_id, sender_id, session_id),
        ).fetchone()
        return row["id"] if row else None


def list_sessions(
    workspace_id: str | None = None,
    agent_id: str | None = None,
    sender_id: str | None = None,
) -> list[dict]:
    clauses, params = [], []
    if workspace_id:
        clauses.append("workspace_id = ?"); params.append(workspace_id)
    if agent_id:
        clauses.append("agent_id = ?");     params.append(agent_id)
    if sender_id:
        clauses.append("sender_id = ?");    params.append(sender_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM sessions {where} ORDER BY updated_at DESC", params
        ).fetchall()
        return [dict(r) for r in rows]


def delete_session(pk: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (pk,))


# ── Messages ─────────────────────────────────────────────────────

def append_message(
    session_pk: str,
    role: str,
    content: str | None,
    tool_calls: list | None,
    tool_call_id: str | None,
    now: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages (session_pk, role, content, tool_calls, tool_call_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_pk,
                role,
                content,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                tool_call_id,
                now,
            ),
        )


def load_messages(session_pk: str, limit: int) -> list[dict]:
    """加载最近 limit 条消息，按时间升序返回（供 LLM 使用）"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content, tool_calls, tool_call_id
            FROM messages
            WHERE session_pk = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_pk, limit),
        ).fetchall()

    result = []
    for r in reversed(rows):
        msg: dict = {"role": r["role"]}
        if r["content"] is not None:
            msg["content"] = r["content"]
        if r["tool_calls"]:
            msg["tool_calls"] = json.loads(r["tool_calls"])
        if r["tool_call_id"]:
            msg["tool_call_id"] = r["tool_call_id"]
        result.append(msg)
    return result


def clear_messages(session_pk: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_pk = ?", (session_pk,))
