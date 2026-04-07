"""
routers/chat.py
HTTP 路由：对话（非流式 + 流式 SSE）、会话查询、删除、历史清空。
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent.runner import AgentRunner
from models.chat import ChatRequest, ChatResponse, SessionInfo
from session import manager

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """非流式对话，返回完整 JSON"""
    session_pk = manager.ensure_session(
        workspace_id=req.workspace_id,
        agent_id=req.agent_id,
        sender_id=req.sender_id,
        session_id=req.session_id,
        first_user_message=req.message,
    )
    history = manager.get_history(session_pk)
    runner  = AgentRunner(agent_id=req.agent_id, session_id=session_pk)
    reply, intermediate = runner.run(user_message=req.message, history=history)
    manager.save_turn(
        session_pk=session_pk,
        user_message=req.message,
        assistant_reply=reply,
        intermediate_messages=intermediate,
    )
    return ChatResponse(
        workspace_id=req.workspace_id,
        agent_id=req.agent_id,
        sender_id=req.sender_id,
        session_id=req.session_id,
        reply=reply,
        session_pk=session_pk,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """
    流式对话接口（SSE）。
    事件格式：
      data: {"tool": "bash", "args": {...}}   <- 工具调用进度
      data: {"text": "..."}                   <- 回复分块
      data: [DONE]                            <- 结束
    """
    session_pk = manager.ensure_session(
        workspace_id=req.workspace_id,
        agent_id=req.agent_id,
        sender_id=req.sender_id,
        session_id=req.session_id,
        first_user_message=req.message,
    )
    history    = manager.get_history(session_pk)
    runner     = AgentRunner(agent_id=req.agent_id, session_id=session_pk)
    full_reply: list[str] = []
    inter:      list[dict] = []

    def event_gen():
        gen = runner.run_stream(user_message=req.message, history=history)
        for line in gen:
            if line.startswith("data: ") and line.strip() != "data: [DONE]":
                try:
                    obj = json.loads(line[6:].strip())
                    if "text" in obj:
                        full_reply.append(obj["text"])
                    if "tool" in obj:
                        inter.append({
                            "role":    "assistant",
                            "content": f"[tool: {obj['tool']}]",
                        })
                except Exception:
                    pass
            yield line

        manager.save_turn(
            session_pk=session_pk,
            user_message=req.message,
            assistant_reply="".join(full_reply),
            intermediate_messages=inter,
        )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    workspace_id: str | None = None,
    agent_id:     str | None = None,
    sender_id:    str | None = None,
) -> list[SessionInfo]:
    """按维度查询会话列表"""
    rows = manager.list_sessions(workspace_id, agent_id, sender_id)
    return [SessionInfo(**r) for r in rows]


@router.get("/sessions/{workspace_id}/{agent_id}/{sender_id}/{session_id}/history")
async def get_history(
    workspace_id: str,
    agent_id:     str,
    sender_id:    str,
    session_id:   str,
) -> list[dict]:
    """获取某个会话的完整历史消息"""
    from session.store import get_session_pk, load_messages
    from config import settings
    pk = get_session_pk(workspace_id, agent_id, sender_id, session_id)
    if not pk:
        raise HTTPException(status_code=404, detail="会话不存在")
    return load_messages(pk, limit=settings.max_history_messages)


@router.delete("/sessions/{workspace_id}/{agent_id}/{sender_id}/{session_id}")
async def delete_session(
    workspace_id: str, agent_id: str, sender_id: str, session_id: str,
) -> dict:
    ok = manager.delete_session(workspace_id, agent_id, sender_id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True}


@router.post("/sessions/{workspace_id}/{agent_id}/{sender_id}/{session_id}/clear")
async def clear_history(
    workspace_id: str, agent_id: str, sender_id: str, session_id: str,
) -> dict:
    ok = manager.clear_history(workspace_id, agent_id, sender_id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"cleared": True}