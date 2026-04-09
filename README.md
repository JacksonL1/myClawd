# SuperChat

一个基于 **FastAPI + Async OpenAI 协议 + 多 Agent 会话编排** 的智能对话系统。

专为**本地开发**和**快速原型验证**设计，零配置启动，5 分钟跑通。

---

## 核心能力

- **零配置启动**：SQLite 内置，无需额外数据库，一键运行
- **会话隔离**：每个 `session_id` 独立上下文，支持多会话并行
- **流式输出**：SSE 实时推送，同步/异步接口双支持
- **多 Agent 协作**：main/planner/knowledge/executor 自动分工
- **Skill 扩展**：自动扫描 `skills/*/SKILL.md`，热加载技能
- **飞书 Bot**：原生 Lark 卡片交互，群聊即问即答

---

## 快速开始（3 分钟）

### 1. 安装依赖

```bash
git clone https://github.com/JacksonL1/superChat.git
cd superChat
pip install -r requirements.txt
```

### 2. 配置（极简）

创建 `.env` 文件，只需填 LLM 接口：

```bash
# 必须的：OpenAI 兼容接口
SGLANG_BASE_URL=https://api.openai.com/v1
SGLANG_API_KEY=sk-your-key
SGLANG_MODEL=gpt-4o-mini

# 可选的：想换本地模型？
# SGLANG_BASE_URL=http://localhost:8000/v1
# SGLANG_MODEL=Qwen2.5-7B
```

> **开发提示**：没有 API Key？用 [Ollama](https://ollama.com/) 本地跑模型，改 `SGLANG_BASE_URL=http://localhost:11434/v1` 即可。

### 3. 启动服务

```bash
python cli.py serve
```

看到 `Uvicorn running on http://0.0.0.0:8000` 即成功。

### 4. 测试对话

```bash
# 方式 1：CLI（推荐开发调试）
python cli.py chat "你好，请介绍自己"

# 方式 2：curl
curl -X POST http://localhost:8000/chat/sync \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","message":"你好"}'

# 方式 3：SSE 流式（开两个终端）
# 终端 A：监听流
curl -N http://localhost:8000/stream/demo

# 终端 B：发送消息
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","message":"讲个笑话"}'
```

---

## 开发指南

### 目录结构

```
.
├── cli.py                 # 命令行入口
├── config.py              # 配置（pydantic-settings，.env 自动加载）
├── agent/
│   ├── loop.py            # Agent 主循环
│   ├── executor.py        # 工具执行（bash/文件/工作区）
│   ├── prompts.py         # 各角色 system prompt
│   └── tools.py           # 工具定义
├── gateway/
│   ├── main.py            # FastAPI 路由
│   └── session_manager.py # 会话生命周期管理
├── store/
│   ├── db.py              # SQLite 连接
│   ├── session_store.py   # 消息历史持久化
│   └── workspace.py       # TODO/NOTES/SUMMARY/ERRORS 虚拟工作区
├── skills/
│   ├── loader.py          # Skill 扫描加载
│   └── */SKILL.md         # 技能定义
└── lark_bot/              # 飞书机器人（可选）
```

### 添加新工具

1. **定义 Schema**（`agent/tools.py`）：

```python
{
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "参数1"}
            },
            "required": ["arg1"]
        }
    }
}
```

2. **实现逻辑**（`agent/executor.py`）：

```python
async def execute_my_tool(arg1: str) -> str:
    # 你的逻辑
    return f"Result: {arg1}"
```

3. **注册到 Agent**（`agent/loop.py` 工具白名单）：

```python
executor_tools = ["bash", "read_file", "my_tool"]  # 加上新工具
```

### 开发模式配置（`.env`）

```bash
# 开发优化：关闭安全层，提升便利性
BASH_ALLOW_SHELL_OPERATORS=true      # 允许管道、重定向等
BASH_ALLOWED_COMMANDS=               # 空=不限制命令（谨慎！）
MAX_TOOL_ROUNDS=30                   # 更多轮次，方便调试

# 日志
LOG_LEVEL=DEBUG

# 关闭飞书（如不需要）
# LARK_APP_ID=  # 留空不启用
```

---

## API 速查

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat` | POST | 异步对话（配合 SSE） |
| `/chat/sync` | POST | 同步对话（阻塞等结果） |
| `/stream/{session_id}` | GET | SSE 流式订阅 |
| `/sessions` | GET | 列出所有会话 |
| `/sessions/{id}/history` | GET | 查看会话历史 |
| `/sessions/{id}/reset` | POST | 清空会话 |

---

## 飞书机器人（可选）

```bash
cd lark_bot
pip install -r requirements.txt

# 配置
export LARK_APP_ID=cli_xxx
export LARK_APP_SECRET=xxx
export SUPERCHAT_URL=http://localhost:8000

python bot.py
```

群聊中 @机器人即可对话。

---

## 与 OpenClaw 的关系

本项目是 **OpenClaw 的简化学习版**，做了以下**开发友好**的调整：

| 特性 | superChat（本分支） | OpenClaw |
|------|---------------------|----------|
| 部署复杂度 | 单容器，SQLite 零依赖 | 多服务，需向量库/外部存储 |
| 认证 | 可选关闭，开发零摩擦 | 强制 OAuth2/JWT |
| 沙箱 | 本机执行（便于调试文件） | 强制 Docker 沙箱 |
| 向量记忆 | 可选关闭 | 默认启用 |
| 审计日志 | 简单记录 | 完整追踪 |

**适用场景**：
- ✅ 本分支：本地开发、快速原型、内部工具
- ✅ OpenClaw：生产环境、多租户 SaaS、高安全要求

---

**未来计划**

- 完善Memory机制
- 内部每一个Agent可以指定模型

## License

MIT

这个版本的特点：

| 方面 | 优化 |
|------|------|
| **启动速度** | 强调 3 分钟/5 分钟启动，降低心理门槛 |
| **配置简化** | 只保留最必要的 LLM 配置，其他都有默认值 |
| **安全降级** | 明确说明「开发友好」定位，bash 限制放宽 |
| **开发工作流** | 添加工具、调试、热加载的具体步骤 |
| **与 OpenClaw 对比** | 诚实说明取舍，避免用户困惑 |
| **生产提示** | 保留安全升级路径，不误导用户 |
