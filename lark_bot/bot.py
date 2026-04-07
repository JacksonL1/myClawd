"""
bot.py  —  飞书长连接 Bot（SSE 流式模式）
handle_message 改用 SSE 流式：
  1. 立即发"处理中"卡片
  2. 每收到进度批量更新卡片
  3. 收到 final 更新为最终卡片
  无 HTTP timeout 问题
"""

import json
import logging
import threading
import re

from card_builder import build_reply_card, build_thinking_card, build_error_card
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
    CreateMessageReactionRequest, CreateMessageReactionRequestBody,
    DeleteMessageReactionRequest, PatchMessageRequest, PatchMessageRequestBody,
)
from lark_oapi.api.im.v1.model import Emoji

from config import settings
from superchat_client import superchat

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("lark_bot")

client = lark.Client.builder() \
    .app_id(settings.lark_app_id) \
    .app_secret(settings.lark_app_secret) \
    .log_level(lark.LogLevel.WARNING) \
    .build()


def send_card(chat_id: str, card: dict) -> str | None:
    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        ).build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        log.error(f"发送卡片失败: {resp.code} {resp.msg}")
        return None
    return resp.data.message_id


def update_card(message_id: str, card: dict) -> bool:
    req = PatchMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(
            PatchMessageRequestBody.builder()
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        ).build()
    resp = client.im.v1.message.patch(req)
    if not resp.success():
        log.error(f"更新卡片失败: {resp.code} {resp.msg}")
        return False
    return True


def add_reaction(message_id: str, emoji_type: str = "THINKING") -> str | None:
    req = CreateMessageReactionRequest.builder() \
        .message_id(message_id) \
        .request_body(
            CreateMessageReactionRequestBody.builder()
            .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
            .build()
        ).build()
    resp = client.im.v1.message_reaction.create(req)
    return resp.data.reaction_id if resp.success() else None


def remove_reaction(message_id: str, reaction_id: str) -> None:
    req = DeleteMessageReactionRequest.builder() \
        .message_id(message_id).reaction_id(reaction_id).build()
    client.im.v1.message_reaction.delete(req)


def build_progress_card(user_text: str, progress: str) -> dict:
    """显示实时进度的卡片（处理中状态）"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "🤖 AI Bot · 处理中…"}},
        "elements": [
            {"tag": "markdown", "content": f"**收到：** {user_text[:80]}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"⚙️ **执行进度**\n```\n{progress[-800:]}\n```"},
        ]
    }


# ════════════════════════════════════════════════════════════════
# 核心处理（SSE 流式）
# ════════════════════════════════════════════════════════════════

def handle_message(user_text: str, sender_id: str, chat_id: str,
                   session_id: str, message_id: str):
    log.info(f"[{sender_id[:8]}] 收到: {user_text[:50]}")

    card_msg_id = send_card(chat_id, build_thinking_card(user_text))
    reaction_id = add_reaction(message_id, "THINKING")

    progress_steps: list[str] = []
    update_count   = [0]

    def on_progress(text: str) -> None:
        progress_steps.append(text)
        update_count[0] += 1
        # 每3条更新一次，避免飞书限流（5次/秒）
        if card_msg_id and update_count[0] % 3 == 0:
            update_card(card_msg_id, build_progress_card(
                user_text=user_text,
                progress="\n".join(progress_steps[-12:]),
            ))

    def on_final(reply: str) -> None:
        thinking = "\n".join(progress_steps) if progress_steps else ""
        card = build_reply_card(content=reply, thinking=thinking)
        if card_msg_id:
            update_card(card_msg_id, card)
        else:
            send_card(chat_id, card)
        if reaction_id:
            remove_reaction(message_id, reaction_id)
        log.info(f"[{sender_id[:8]}] 回复完成，进度步骤: {len(progress_steps)}")

    def on_error(msg: str) -> None:
        log.error(f"[{sender_id[:8]}] 错误: {msg}")
        if card_msg_id:
            update_card(card_msg_id, build_error_card(msg))
        else:
            send_card(chat_id, build_error_card(msg))
        if reaction_id:
            remove_reaction(message_id, reaction_id)

    superchat.chat_stream(
        message     = user_text,
        sender_id   = sender_id,
        session_id  = session_id,
        on_progress = on_progress,
        on_final    = on_final,
        on_error    = on_error,
    )


def extract_text(event_body) -> str:
    try:
        body = json.loads(event_body.message.content)
        text = body.get("text", "")
        return re.sub(r"@_user_\d+\s*", "", text).strip()
    except Exception:
        return ""


_bot_open_id: str = ""

def _get_bot_open_id() -> str:
    global _bot_open_id
    if _bot_open_id:
        return _bot_open_id
    try:
        from lark_oapi.api.bot.v3 import GetBotInfoRequest
        resp = client.bot.v3.bot.get(GetBotInfoRequest.builder().build())
        if resp.success():
            _bot_open_id = resp.data.open_id
    except Exception as e:
        log.warning(f"获取 Bot open_id 失败: {e}")
    return _bot_open_id


_processed_ids: set[str] = set()
_id_lock = threading.Lock()

def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    try:
        event      = data.event
        msg        = event.message
        sender     = event.sender
        chat_id    = msg.chat_id
        message_id = msg.message_id
        sender_id  = sender.sender_id.open_id

        if msg.message_type != "text":
            return

        with _id_lock:
            if message_id in _processed_ids:
                return
            _processed_ids.add(message_id)
            if len(_processed_ids) > 500:
                _processed_ids.discard(next(iter(_processed_ids)))

        if msg.chat_type == "group" and settings.group_at_only:
            mentions = getattr(msg, "mentions", []) or []
            bot_id   = _get_bot_open_id()
            if not any(
                getattr(getattr(m, "id", None), "open_id", "") == bot_id
                for m in mentions
            ):
                return

        user_text = extract_text(event)
        if not user_text:
            return

        threading.Thread(
            target=handle_message,
            args=(user_text, sender_id, chat_id, chat_id, message_id),
            name=f"msg-{message_id[-8:]}",
            daemon=True,
        ).start()

    except Exception as e:
        log.exception(f"处理消息异常: {e}")

def do_p2_im_message_reaction_created_v1(data: lark.im.v1.P2ImMessageReactionCreatedV1) -> None:
    print(f'[ do_p2_im_message_reaction_created_v1 access ]')


def do_p2_im_message_reaction_deleted_v1(data: lark.im.v1.P2ImMessageReactionDeletedV1) -> None:
    print(f'[ do_p2_im_message_reaction_deleted_v1 access ]')


def main():
    log.info(f"启动飞书 Bot | App: {settings.lark_app_id} | SuperChat: {settings.superchat_url}")

    dispatcher = lark.EventDispatcherHandler.builder(
        "", "", lark.LogLevel.WARNING,
    ).register_p2_im_message_receive_v1(
        on_message_receive
    ).register_p2_im_message_reaction_created_v1(
        do_p2_im_message_reaction_created_v1
    ).register_p2_im_message_reaction_deleted_v1(
        do_p2_im_message_reaction_deleted_v1
    ).build()
    lark.ws.Client(
        app_id=settings.lark_app_id,
        app_secret=settings.lark_app_secret,
        event_handler=dispatcher,
        log_level=lark.LogLevel.WARNING,
    ).start()


if __name__ == "__main__":
    main()