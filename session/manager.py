"""
session/manager.py
会话业务逻辑：创建/获取会话、追加消息、加载历史。
隔离键 = workspace_id + agent_id + sender_id + session_id 四元组。
"""

import uuid
from datetime import datetime, timezone

from config import settings
from session import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_pk() -> str:
    return str(uuid.uuid4())


def ensure_session(
    workspace_id: str,
    agent_id: str,
    sender_id: str,
    session_id: str,
    first_user_message: str | None = None,
) -> str:
    """
    确保会话存在，返回 session 主键（UUID）。
    若不存在则创建；存在则更新 updated_at。
    """
    now = _now()
    pk = store.get_session_pk(workspace_id, agent_id, sender_id, session_id)
    if not pk:
        pk = _gen_pk()
    # title 取首条消息前 40 字
    title = (first_user_message or "")[:40] or None
    store.upsert_session(pk, workspace_id, agent_id, sender_id, session_id, title, now)
    return pk


def get_history(session_pk: str) -> list[dict]:
    """返回该会话的历史消息（供拼接到 LLM messages）"""
    messages = store.load_messages(session_pk, limit=settings.max_history_messages)
    # 过滤掉 role 为 tool 的消息
    return [msg for msg in messages if msg.get("role") != "tool"]


def save_turn(
    session_pk: str,
    user_message: str,
    assistant_reply: str,
    intermediate_messages: list[dict],  # tool_calls + tool results
) -> None:
    """
    保存一次完整的对话轮次：
      user → [tool_call/tool_result ...] → assistant
    """
    now = _now()

    # 1. 用户消息
    store.append_message(
        session_pk=session_pk,
        role="user",
        content=user_message,
        tool_calls=None,
        tool_call_id=None,
        now=now,
    )

    # 2. 中间的 assistant tool_call 和 tool result 消息
    for msg in intermediate_messages:
        store.append_message(
            session_pk=session_pk,
            role=msg["role"],
            content=msg.get("content"),
            tool_calls=msg.get("tool_calls"),
            tool_call_id=msg.get("tool_call_id"),
            now=now,
        )

    # 3. 最终 assistant 回复
    store.append_message(
        session_pk=session_pk,
        role="assistant",
        content=assistant_reply,
        tool_calls=None,
        tool_call_id=None,
        now=now,
    )


def list_sessions(
    workspace_id: str | None = None,
    agent_id: str | None = None,
    sender_id: str | None = None,
) -> list[dict]:
    return store.list_sessions(workspace_id, agent_id, sender_id)


def delete_session(
    workspace_id: str,
    agent_id: str,
    sender_id: str,
    session_id: str,
) -> bool:
    pk = store.get_session_pk(workspace_id, agent_id, sender_id, session_id)
    if not pk:
        return False
    store.delete_session(pk)
    return True


def clear_history(
    workspace_id: str,
    agent_id: str,
    sender_id: str,
    session_id: str,
) -> bool:
    pk = store.get_session_pk(workspace_id, agent_id, sender_id, session_id)
    if not pk:
        return False
    store.clear_messages(pk)
    return True
