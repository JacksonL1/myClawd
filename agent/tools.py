"""
agent/tools.py
工具 JSON Schema 定义，在原有基础上新增 sessions_send。
"""

TOOLS: list[dict] = [
    # ── Skill 相关 ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "读取某个 Skill 的完整 SKILL.md 指令。当判断某个 skill 与当前任务相关时，先调用此工具获取详细指令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_path": {
                        "type": "string",
                        "description": "SKILL.md 的路径，取自 available_skills 中的 path 属性",
                    }
                },
                "required": ["skill_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skill_files",
            "description": "列出某个 skill 目录下所有文件的完整路径",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "skills/ 下的子目录名"}
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在本机执行 shell 命令或 Python 脚本并返回真实输出。必须真正执行，不能伪造结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的完整 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60", "default": 60},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件文本内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    # ── 工作记忆 ──────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "更新任务清单（TODO.md）。用 Markdown checklist 格式写入所有任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "完整的 Markdown checklist"}
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_note",
            "description": "向 NOTES.md 追加一条结论或重要发现。只记结论，不记过程。",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace",
            "description": "读取工作区文件内容（TODO.md / NOTES.md / SUMMARY.md / ERRORS.md）",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": ["TODO.md", "NOTES.md", "SUMMARY.md", "ERRORS.md"],
                    }
                },
                "required": ["file"],
            },
        },
    },
    # ── Agent 间通信 ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "sessions_send",
            "description": (
                "向另一个 Agent session 发送消息并等待回复。"
                "用于把子任务委派给专门的 Agent（planner / knowledge / executor）。"
                "子 Agent 在完全独立的上下文中运行，只返回结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to_session": {
                        "type": "string",
                        "description": "目标 session id，如 'planner'、'executor'、'knowledge'",
                    },
                    "message": {
                        "type": "string",
                        "description": "发给目标 Agent 的完整任务描述，需包含足够背景",
                    },
                    "announce": {
                        "type": "boolean",
                        "description": "是否把执行过程推送给用户（默认 false，结果才推送）",
                        "default": False,
                    },
                },
                "required": ["to_session", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sessions_list",
            "description": "列出当前所有活跃的 Agent session 及其状态",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
