"""
card_builder.py
构建飞书消息卡片（Card Kit JSON）。
已修复：value 必须是字典，不能是字符串
"""
import json
import re


def fix_feishu_text(text: str) -> str:
    """
    修复飞书解析问题：
    1. 把 Markdown 表格转为普通列表
    2. 适配飞书纯文本
    3. 把 emoji 前面的 ### 标题移到 emoji 后面
    """

    # 1. 移除 Markdown 表格（| 分隔），替换为列表格式
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        # 3. 多级标题##/###统一转为飞书兼容的### 一级标题
        if "|" in line:  # 表格行
            line = line.strip("|").strip()
            # 检查是否是分隔线（只包含 - 或 =）
            if all(c in "-= " for c in line.replace("|", "")):
                # 跳过分隔线
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 2:
                new_lines.append(f"- {parts[0]}：{parts[1]}")
        elif line.startswith('#'):
            # 检查是否有 emoji：### 🤖 标题 → 🤖 ** 标题 或 # 💡 提示 → 💡 # 提示
            # 匹配模式：###(空格)emoji(空格)内容
            match = re.match(r'(#+)(\s+)([\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251\U0001F900-\U0001F9FF]+)(\s+)(.+)', line)
            if match:
                # 有 emoji，调换顺序
                hashes = match.group(1)
                emoji = match.group(3)
                content = match.group(5)
                if len(hashes) >= 2:
                    # ## 及以上标题，转换为 ** 内容 **
                    new_lines.append(f"{emoji} ** {content} **")
                else:
                    # # 一级标题，保持 #
                    new_lines.append(f"{emoji} {hashes} {content}")
            else:
                # 普通标题，直接转换
                if line.startswith('##'):
                    # 提取标题内容，转换为 ** 内容 ** 格式
                    content = re.sub(r'^#{2,}', '', line).strip()
                    line = f"** {content} **"
                new_lines.append(line)
        # 4. 把"分类：xxx""技能：xxx"整合成列表项，删掉冗余分隔
        elif re.match(r'^[\u4e00-\u9fa5]+[:：]', line) and not line.startswith('-'):
            new_lines.append(f'- {line.strip()}')
        # 5. 保留原有列表项，清理多余空格
        elif line.startswith('-'):
            new_lines.append(line.strip())
        # 6. 普通内容直接保留
        else:
            new_lines.append(line.strip())
    # 7. 清理多余空行，拼接最终内容
    final_text = '\n'.join([l for l in new_lines if l])
    return final_text


def build_reply_card(
    content:   str,
    title:     str = "🤖 AI Bot",
    thinking:  str = "",
) -> dict:
    elements = []
    content = fix_feishu_text(content)
    thinking = fix_feishu_text(thinking)
    # 思考过程
    if thinking:
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {"tag": "plain_text", "content": "💭 思考过程"}
            },
            "elements": [{
                "tag": "markdown",
                "content": thinking[:2000],
            }],
        })

    # 正文
    elements.append({
        "tag": "markdown",
        "content": _truncate(content, 4000),
    })

    # 分割线
    # elements.append({"tag": "hr"})

    # ✅ 正确结构：无card、无schema
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title}
        },
        "elements": elements
    }


def build_thinking_card(user_message: str) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🤖 AI Bot"}
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**收到你的消息：**\n> {user_message[:100]}\n\n⏳ 正在思考中，请稍候…",
            }
        ]
    }


def build_error_card(error_msg: str) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚠️ 出现错误"}
        },
        "elements": [
            {"tag": "markdown", "content": error_msg}
        ]
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n…（内容过长，已截断）"