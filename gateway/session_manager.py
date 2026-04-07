"""
gateway/session_manager.py
Session 生命周期管理：创建、启动、停止、查询 Agent session。

每个 session 是一个独立的 asyncio.Task，运行 AgentLoop。
SessionManager 持有所有 Task 的引用，负责启动和优雅停止。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Callable, Awaitable

from openai import AsyncOpenAI

from agent.loop import AgentLoop
from messaging.bus import MessageBus, bus as global_bus
from messaging.protocol import AgentMessage, Flags, MessageType
from store.session_store import create_session, list_sessions, get_session
from config import settings

log = logging.getLogger(__name__)

# 默认预启动的 session（平台初始化时自动创建）
DEFAULT_SESSIONS = [
    ("main",      "main"),
    ("planner",   "planner"),
    ("knowledge", "knowledge"),
    ("executor",  "executor"),
]


class SessionManager:
    """
    管理所有 AgentLoop 实例和对应的 asyncio.Task。
    Gateway 启动时初始化，全局单例。
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        bus: MessageBus = global_bus,
    ):
        self.client  = client
        self.model   = model
        self.bus     = bus
        self._loops:  Dict[str, AgentLoop]     = {}
        self._tasks:  Dict[str, asyncio.Task]  = {}
        self._sse_subscribers: Dict[str, list[asyncio.Queue]] = {}
        # per-session 锁，防止并发创建同一个 session 产生竞态
        self._ensure_locks: Dict[str, asyncio.Lock] = {}

    # ── 初始化 ────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Gateway 启动时调用：建表、创建默认 session、并行启动 AgentLoop。"""
        from store.db import init_db
        from skills.memory import init_memory_table
        await init_db()
        await asyncio.to_thread(init_memory_table)
        # 串行启动：确保每个 session 的 run() task 稳定调度后再启动下一个
        for session_id, role in DEFAULT_SESSIONS:
            await self.ensure_session(session_id, role)
        log.info("[SessionManager] started, sessions: " + str(list(self._loops.keys())))

    async def shutdown(self) -> None:
        """优雅停止所有 AgentLoop。"""
        for session_id in list(self._loops.keys()):
            await self.stop_session(session_id)
        log.info("[SessionManager] shutdown complete")

    # ── Session 创建 / 启动 ───────────────────────────────────────

    async def ensure_session(self, session_id: str, role: str = "main") -> AgentLoop:
        """
        确保 session 存在并运行中。
        用 _ensure_lock 防止并发创建同一个 session 产生竞态。
        """
        if session_id in self._loops:
            return self._loops[session_id]

        # 用 per-session 锁防止并发创建同一个 session
        if session_id not in self._ensure_locks:
            self._ensure_locks[session_id] = asyncio.Lock()
        async with self._ensure_locks[session_id]:
            # double-check：加锁后再检查一次
            if session_id in self._loops:
                return self._loops[session_id]

            await create_session(session_id, role)

            loop = AgentLoop(
                session_id        = session_id,
                role              = role,
                bus               = self.bus,
                client            = self.client,
                model             = self.model,
                announce_callback = self._announce,
            )
            self._loops[session_id] = loop

            task = asyncio.create_task(loop.run(), name=f"agent-{session_id}")
            self._tasks[session_id] = task
            task.add_done_callback(lambda t: self._on_task_done(session_id, t))

            # inbox 在 AgentLoop.__init__ 里已经注册到 bus，消息发进去会在 Queue 里等
            # inbox Queue 在 __init__ 里已注册，消息会等到 run() 调度后处理
            log.info(f"[SessionManager] started session: {session_id} (role={role})")
            return loop

    async def stop_session(self, session_id: str) -> None:
        if session_id not in self._loops:
            return
        loop = self._loops[session_id]
        await loop.stop()
        # 发 STOP 系统消息确保循环退出
        stop_msg = AgentMessage(
            from_session="system",
            to_session=session_id,
            content="STOP",
            type=MessageType.SYSTEM,
            flags=Flags.REPLY_SKIP | Flags.ANNOUNCE_SKIP,
        )
        try:
            await self.bus.inbox(session_id).put(stop_msg)
        except KeyError:
            pass
        task = self._tasks.get(session_id)
        if task:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._loops.pop(session_id, None)
        self._tasks.pop(session_id, None)
        self.bus.unregister(session_id)
        log.info(f"[SessionManager] stopped session: {session_id}")

    def _on_task_done(self, session_id: str, task: asyncio.Task) -> None:
        if task.cancelled():
            log.info(f"[SessionManager] session {session_id} was cancelled")
            return
        exc = task.exception()
        if exc:
            log.error(f"[SessionManager] session {session_id} crashed: {exc}", exc_info=exc)
            # 自动重启（简单重试一次）
            asyncio.create_task(self._restart_session(session_id))

    async def _restart_session(self, session_id: str) -> None:
        info = await get_session(session_id)
        if not info:
            return
        role = info.get("role", "main")
        self._loops.pop(session_id, None)
        self._tasks.pop(session_id, None)
        self.bus.unregister(session_id)
        await asyncio.sleep(1)
        await self.ensure_session(session_id, role)
        log.info(f"[SessionManager] restarted session: {session_id}")

    # ── 发消息给 session ──────────────────────────────────────────

    async def send_to_session(
        self,
        session_id: str,
        content: str,
        from_session: str = "user",
        flags: Flags = Flags.NONE,
    ) -> None:
        """
        Gateway HTTP 接口调用此方法把用户消息投入 session 的 inbox。
        ensure_session 在后台创建 session，等 inbox 注册好后再投递消息。
        """
        await self.ensure_session(session_id)

        # 等 inbox 注册到 bus（最多 5 秒）
        for _ in range(50):
            try:
                self.bus.inbox(session_id)
                break
            except KeyError:
                await asyncio.sleep(0.1)

        msg = AgentMessage(
            from_session = from_session,
            to_session   = session_id,
            content      = content,
            type         = MessageType.TASK,
            flags        = flags | Flags.ANNOUNCE_SKIP,
        )
        await self.bus.send(msg, wait_reply=False)

    # ── SSE 广播 ──────────────────────────────────────────────────

    async def _announce(
        self,
        session_id: str,
        text: str,
        is_progress: bool = False,
        is_final: bool = False,
    ) -> None:
        """AgentLoop 回调：把文字推给所有订阅该 session 的 SSE 连接。"""
        subscribers = self._sse_subscribers.get(session_id, [])
        payload = {
            "session_id": session_id,
            "text":       text,
            "progress":   is_progress,
            "final":      is_final,   # True 表示这是最终回复，/chat/sync 收到后才返回
        }
        for q in subscribers:
            await q.put(payload)

    def subscribe_sse(self, session_id: str) -> asyncio.Queue:
        """SSE 连接建立时调用，返回一个专属 queue。"""
        q = asyncio.Queue()
        self._sse_subscribers.setdefault(session_id, []).append(q)
        return q

    def unsubscribe_sse(self, session_id: str, q: asyncio.Queue) -> None:
        subs = self._sse_subscribers.get(session_id, [])
        if q in subs:
            subs.remove(q)

    # ── 查询 ──────────────────────────────────────────────────────

    async def get_all_sessions(self) -> list[dict]:
        return await list_sessions()

    def get_running_sessions(self) -> list[str]:
        return list(self._loops.keys())