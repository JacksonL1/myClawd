"""
messaging/protocol.py
Agent 间通信的消息结构定义。

核心概念：
  - AgentMessage : 一条在 session 之间传递的消息
  - Flags        : 控制消息行为（REPLY_SKIP / ANNOUNCE_SKIP）
  - MessageType  : 消息类型（task / reply / notify / system）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntFlag
from typing import Any


class Flags(IntFlag):
    """
    消息行为控制标志，可组合使用。

    REPLY_SKIP    : 收到消息的 Agent 执行后不回复（fire-and-forget）
    ANNOUNCE_SKIP : 执行结果不推送给用户 SSE 流，只返回给发送方
    """
    NONE          = 0
    REPLY_SKIP    = 1
    ANNOUNCE_SKIP = 2


class MessageType:
    TASK   = "task"    # 主 Agent 给子 Agent 派发任务
    REPLY  = "reply"   # 子 Agent 回复任务结果
    NOTIFY = "notify"  # 单向通知，不需要回复
    SYSTEM = "system"  # 系统内部控制消息（停止/重置等）


@dataclass
class AgentMessage:
    """
    Agent 间传递的消息单元。

    from_session : 发送方 session id
    to_session   : 接收方 session id
    content      : 消息内容（文字）
    type         : MessageType
    flags        : Flags 组合
    reply_to     : 期望结果回复给哪个 session（默认回给发送方）
    msg_id       : 消息唯一 ID
    ref_id       : 关联的上游消息 ID（reply 时填写对应 task 的 msg_id）
    meta         : 附加数据（如步骤编号、工具名等）
    """
    from_session : str
    to_session   : str
    content      : str
    type         : str                = MessageType.TASK
    flags        : Flags              = Flags.NONE
    reply_to     : str | None         = None
    msg_id       : str                = field(default_factory=lambda: uuid.uuid4().hex)
    ref_id       : str | None         = None
    meta         : dict[str, Any]     = field(default_factory=dict)

    def should_reply(self) -> bool:
        return not bool(self.flags & Flags.REPLY_SKIP)

    def should_announce(self) -> bool:
        return not bool(self.flags & Flags.ANNOUNCE_SKIP)

    def make_reply(self, content: str) -> "AgentMessage":
        """生成对本消息的回复消息。"""
        return AgentMessage(
            from_session = self.to_session,
            to_session   = self.reply_to or self.from_session,
            content      = content,
            type         = MessageType.REPLY,
            flags        = Flags.ANNOUNCE_SKIP,  # 回复默认不广播给用户
            ref_id       = self.msg_id,
        )
