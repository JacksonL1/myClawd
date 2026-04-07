"""
models/chat.py
HTTP API 的请求和响应 Schema。
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # 四维隔离键
    workspace_id: str = Field(..., description="工作区 ID，如项目名或空间名")
    agent_id:     str = Field(..., description="智能体 ID，决定人设和可用 Skills")
    sender_id:    str = Field(..., description="发送者 ID，如用户 ID 或机器人 ID")
    session_id:   str = Field(..., description="会话 ID，同一发送者可开多个会话")

    # 消息内容
    message: str = Field(..., description="用户消息")


class ChatResponse(BaseModel):
    workspace_id: str
    agent_id:     str
    sender_id:    str
    session_id:   str
    reply:        str
    session_pk:   str = Field(..., description="会话数据库主键，可用于查询历史")


class SessionInfo(BaseModel):
    id:           str
    workspace_id: str
    agent_id:     str
    sender_id:    str
    session_id:   str
    title:        str | None
    created_at:   str
    updated_at:   str
