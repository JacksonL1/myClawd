"""
messaging/bus.py
Message Bus：Agent 间异步通信的核心。

每个 session 注册一个 asyncio.Queue 作为 inbox。
sessions_send() 把消息投递到目标 session 的 inbox，
并可选择等待回复（ping-pong 模式）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from messaging.protocol import AgentMessage, Flags, MessageType
from store.db import get_db

log = logging.getLogger(__name__)


class MessageBus:
    """
    全局单例消息总线。
    gateway/session_manager.py 持有唯一实例，所有 AgentLoop 共享。
    """

    def __init__(self) -> None:
        # session_id → asyncio.Queue[AgentMessage]
        self._inboxes: Dict[str, asyncio.Queue] = {}
        # 等待特定 ref_id 回复的 Future
        # reply_waiters[msg_id] = Future[AgentMessage]
        self._reply_waiters: Dict[str, asyncio.Future] = {}
        # SSE 广播队列：announce 消息写入这里，Gateway 推给用户
        self._announce_queue: asyncio.Queue = asyncio.Queue()

    # ── Session 注册 / 注销 ──────────────────────────────────────

    def register(self, session_id: str) -> asyncio.Queue:
        """注册 session，返回其 inbox queue。"""
        if session_id not in self._inboxes:
            self._inboxes[session_id] = asyncio.Queue()
            log.debug(f"[Bus] registered session: {session_id}")
        return self._inboxes[session_id]

    def unregister(self, session_id: str) -> None:
        self._inboxes.pop(session_id, None)
        log.debug(f"[Bus] unregistered session: {session_id}")

    def inbox(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._inboxes:
            raise KeyError(f"session '{session_id}' 未注册")
        return self._inboxes[session_id]

    # ── 核心：发送消息 ────────────────────────────────────────────

    async def send(
        self,
        msg: AgentMessage,
        wait_reply: bool = False,
        reply_timeout: float = 120.0,
    ) -> Optional[AgentMessage]:
        """
        发送消息到目标 session 的 inbox。

        wait_reply=True  : 等待目标 session 回复（ping-pong），返回回复消息
        wait_reply=False : fire-and-forget，立即返回 None

        同时写入 agent_messages 表做审计记录。
        """
        # 目标 session 不存在时快速失败
        if msg.to_session not in self._inboxes:
            log.warning(f"[Bus] target session '{msg.to_session}' not registered")
            return None

        # 如果需要等待回复，先注册 Future
        future: Optional[asyncio.Future] = None
        if wait_reply and msg.should_reply():
            loop   = asyncio.get_event_loop()
            future = loop.create_future()
            self._reply_waiters[msg.msg_id] = future

        # 投递到目标 inbox
        await self._inboxes[msg.to_session].put(msg)
        log.debug(f"[Bus] {msg.from_session} → {msg.to_session}: {msg.content[:60]}")

        # 持久化审计记录（非阻塞，失败不影响主流程）
        asyncio.create_task(self._persist_agent_message(msg))

        # 广播给用户（SSE）
        if msg.should_announce():
            await self._announce_queue.put(msg)

        # 等待回复
        if future is not None:
            try:
                reply = await asyncio.wait_for(future, timeout=reply_timeout)
                return reply
            except asyncio.TimeoutError:
                self._reply_waiters.pop(msg.msg_id, None)
                log.warning(f"[Bus] reply timeout for msg {msg.msg_id}")
                return None

        return None

    # ── 回复投递 ──────────────────────────────────────────────────

    async def deliver_reply(self, reply: AgentMessage) -> None:
        """
        子 Agent 调用此方法把回复送达等待中的 Future。
        只解除 Future，不再投入 inbox——调用方已经通过 await bus.send(wait_reply=True)
        拿到了回复内容，不需要再经过 inbox 触发一轮新的消息处理。
        重复投 inbox 会导致 main 把子 Agent 的回复当成新用户消息，产生无限循环。
        """
        if reply.ref_id and reply.ref_id in self._reply_waiters:
            future = self._reply_waiters.pop(reply.ref_id)
            if not future.done():
                future.set_result(reply)

        asyncio.create_task(self._persist_agent_message(reply))

    # ── SSE 广播 ──────────────────────────────────────────────────

    async def next_announce(self) -> AgentMessage:
        """Gateway SSE handler 调用，阻塞等待下一条广播消息。"""
        return await self._announce_queue.get()

    # ── 持久化 ───────────────────────────────────────────────────

    async def _persist_agent_message(self, msg: AgentMessage) -> None:
        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO agent_messages
                       (from_session, to_session, content, reply_to, flags, status)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        msg.from_session,
                        msg.to_session,
                        msg.content[:2000],
                        msg.reply_to,
                        int(msg.flags),
                        "delivered" if msg.type == MessageType.REPLY else "pending",
                    ),
                )
                await db.commit()
        except Exception as e:
            log.warning(f"[Bus] persist failed: {e}")


# 全局单例
bus = MessageBus()