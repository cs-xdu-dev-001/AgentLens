<div align="center">

# KnowFlow AI

**可自行部署、过程可见的AI Agent与知识库**

把对话、RAG、工具、MCP、Skills、长期记忆和任务执行放在同一个界面中。

<p>
  <a href="./README.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-111111?style=flat-square"></a>
  <a href="./README_EN.md"><img alt="English" src="https://img.shields.io/badge/English-E5E7EB?style=flat-square"></a>
</p>

<p>
  <a href="#选择你的使用方式">快速开始</a> ·
  <a href="#linux-cli">Linux CLI</a> ·
  <a href="#linux部署">部署</a> ·
  <a href="#进一步阅读">文档</a>
</p>

<p>
  <a href="https://github.com/cs-xdu-dev-001/KnowFlow-AI/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cs-xdu-dev-001/KnowFlow-AI/actions/workflows/ci.yml/badge.svg"></a>
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2F855A?style=flat-square"></a>
</p>

</div>

> 当前版本适合个人使用、学习Agent工程和在受控环境中测试。Agent运行时与CLI优先支持Linux；Windows可用于本地开发和浏览器访问。

## 核心能力

- **可观察的Agent执行**：基于LangGraph运行，展示模型、工具、MCP、记忆和审批步骤，支持持久化checkpoint与失败恢复。
- **带引用的知识库问答**：上传常见办公文档，查看命中文本、相关度和引用来源。
- **模型与协议可切换**：支持OpenAI兼容端点，可为模型选择Chat Completions或Responses API。
- **工具、MCP与Skills**：模型可自主联网搜索、调用已授权的MCP服务，并按任务启用Skill。
- **用户隔离**：知识库、模型配置、工具密钥、MCP连接、Skills和长期记忆均按用户隔离。
- **Web与Linux CLI**：浏览器和终端共用同一套Agent、审批、记忆与运行记录。

## 选择你的使用方式

| 目标 | 推荐入口 | 需要什么 |
| --- | --- | --- |
| 使用已经部署的KnowFlow | [Linux CLI](#linux-cli)或浏览器 | Linux、Python 3.10+或现代浏览器 |
| 在Windows上修改和调试项目 | [本地开发](#windows本地开发) | Python 3.10+、Node.js 18+、npm |
| 部署自己的服务 | [Linux部署](#linux部署) | Ubuntu 24.04、域名与HTTPS |

## Linux CLI

远程CLI很轻量，不会在本机安装Mem0、ChromaDB或服务端运行时。

```bash
curl -fsSL https://raw.githubusercontent.com/cs-xdu-dev-001/KnowFlow-AI/main/install.sh | sh
knowflow auth login https://你的KnowFlow服务器
knowflow chat
```

无桌面的服务器会输出验证地址和一次性验证码，可在另一台设备上完成登录。

常用命令：

```bash
knowflow run "总结当前项目" --events
knowflow runs
knowflow models list
knowflow tools list
knowflow skills list
knowflow mcp list
knowflow memory list
```

CLI默认连接远程KnowFlow服务。`--local`会直接打开本机数据库和运行时存储，只适合独立测试机或停服维护，不能与同一数据目录上的Web服务并发运行。

## Windows本地开发

### 1. 获取代码

```powershell
git clone https://github.com/cs-xdu-dev-001/KnowFlow-AI.git
Set-Location "KnowFlow-AI"
```

### 2. 安装依赖

`start-dev.cmd`使用Windows的`py -3`启动后端，因此后端依赖也安装到该Python环境：

```powershell
py -3 -m pip install -r backend\requirements.txt
py -3 -m pip install --no-deps -e backend
Copy-Item backend\.env.example backend\.env

Set-Location frontend
npm install
Set-Location ..
```

### 3. 启动

```powershell
.\start-dev.cmd
```

打开<http://127.0.0.1:5173/>。默认地址：

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:8010
API文档：http://127.0.0.1:8010/docs
```

只检查端口和启动命令，不启动服务：

```powershell
.\start-dev.cmd --check
```

## 首次使用

1. 注册本地账号并登录。
2. 在“设置”中添加聊天模型；知识库需要语义检索时，再添加Embedding模型。
3. 创建知识库并上传文档，或直接开始对话。
4. 按需配置联网搜索、MCP、Skills和长期记忆。

模型配置保存在当前用户空间。联网搜索的Tavily Key也由每个用户在前端单独配置，后端不会从启动脚本读取全局Key。

## 配置

本地开发无需逐项填写环境变量：复制`backend/.env.example`后即可启动，大多数能力默认关闭或使用安全默认值。

### 生产环境必查

| 变量 | 用途 |
| --- | --- |
| `KNOWFLOW_SECRET_KEY` | 加密用户保存的模型和工具密钥，必须更换默认值 |
| `KNOWFLOW_BASE_URL` | 对外可访问的后端地址，用于OAuth回调 |
| `KNOWFLOW_OAUTH_RETURN_ORIGINS` | OAuth完成后允许返回的前端origin白名单 |
| `KNOWFLOW_COOKIE_SECURE=1` | 使用HTTPS部署时启用安全Cookie |
| `KNOWFLOW_DB_URL` | 默认使用SQLite；需要MySQL时再修改 |

### 按需启用

| 功能 | 配置入口 |
| --- | --- |
| 聊天与Embedding模型 | 前端“设置” |
| Tavily联网搜索 | 前端“工具与MCP” |
| GitHub登录 | `KNOWFLOW_GITHUB_CLIENT_ID`、`KNOWFLOW_GITHUB_CLIENT_SECRET` |
| Mem0长期记忆 | `KNOWFLOW_MEMORY_*` |
| 工作区文件工具 | `KNOWFLOW_WORKSPACE_ENABLED=1` |
| 沙箱Shell | `KNOWFLOW_SANDBOX_ENABLED=1`，并安装Anthropic Sandbox Runtime |
| 私有网络MCP | 仅受控开发环境可设置`KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS=1` |

所有变量、默认值和限制以[`backend/.env.example`](backend/.env.example)为准。不要提交`backend/.env`。

### 模型协议

- **Chat Completions**适合传统OpenAI兼容端点。
- **Responses API**要求上游支持`POST /v1/responses`、SSE流式事件和最终的`response.completed`事件。
- KnowFlow不会在失败后自动降级协议，避免重复请求或重复执行工具。
- Mem0使用独立的服务端LLM与Embedding配置，不受前端聊天模型协议影响。

<details>
<summary>展开高级配置与运行约束</summary>

#### Windows开发排错

Vite固定使用`--strictPort`，并通过以下地址连接后端：

```text
VITE_BACKEND_URL=http://127.0.0.1:8010
```

如果端口8000出现`WinError 10013`，继续使用项目默认的8010端口。修改前端端口时，必须同步更新`KNOWFLOW_OAUTH_RETURN_ORIGINS`。旧数据认领由`KNOWFLOW_ADOPT_LEGACY_DATA`控制，默认关闭。可运行`start-dev.cmd --check`核对实际命令。

#### Auth Mode与GitHub OAuth

本地账号默认启用，密码保存为PBKDF2哈希，登录后使用HttpOnly会话Cookie。GitHub OAuth为可选功能，需要配置`KNOWFLOW_GITHUB_CLIENT_ID`和`KNOWFLOW_GITHUB_CLIENT_SECRET`。本地回调地址为：

```text
http://127.0.0.1:8010/api/auth/oauth/github/callback
```

#### 联网搜索与运行轨迹

`web_search`通过`tool_choice: auto`交给模型自主判断是否搜索。每位用户在设置页保存自己的Tavily Key。后端通过SSE推送脱敏事件，聊天消息显示当前步骤，右侧Agent运行图显示完整过程。

#### 远程MCP

Notion预设使用官方`https://mcp.notion.com/mcp`端点和user OAuth。自定义公共HTTPS服务器使用Streamable HTTP，可选择No authentication、Static headers或标准OAuth。只读操作可automatically执行；写入、删除和未知风险操作必须等待approval。

运行协调器目前要求one backend worker。真实Notion验收请使用非生产工作区和专用test page：先拒绝写入并确认没有变化，再批准一次并确认只发生一次写入。

#### Skills

Skill是以`SKILL.md`为核心的指令包，至少包含`name:`和`description:`；可在`metadata:`下使用`knowflow:`、`display_name:`、`version:`、`required_tools:`和`required_mcp:`声明界面信息与依赖。

GitHub和ZIP安装采用preview后再install的两阶段流程，只接受`https`的`github.com`来源。导入限制覆盖archive大小、extracted大小、files数量、单个file size、路径depth、正文body、preview TTL和下载timeout，具体值见`backend/.env.example`。

Skill以per-user方式隔离，builtin Skill默认为default关闭状态。一次Agent run最多使用one Skill；在输入框键入`/`可显式选择，也可由模型从当前enabled Skill中auto-activate一个。Skill不能启用tool、MCP或跳过approval。`scripts/`只会stored和inspected，当前版本不会执行；`references/`只会在激活后作为有界UTF-8只读文本提供。

backup必须包含database、`data/skills`和`data/skill-imports`策略涉及的数据；服务用户需要write permission。多实例部署必须使用shared persistent volume。升级前运行全部checks和前端build，不要把用户Skill数据提交到Git。

#### 长期记忆（Mem0）

Mem0只负责长期记忆，不会接管Agent循环、工具或计划。召回结果进入LangGraph checkpoint，回答保存后再以ADD-only方式异步提取记忆。进入Mem0前会移除常见Token、Key、密码和Bearer值。

默认存储位于`data/mem0`。使用本地Qdrant时保持单worker；主数据库和整个Mem0目录必须一起备份。

</details>

## Linux部署

推荐Ubuntu 24.04、非root服务用户、单worker、systemd与HTTPS反向代理。Agent运行时暂不支持在Windows或macOS本机执行。

仓库提供：

- [`deploy/knowflow-ai.service.example`](deploy/knowflow-ai.service.example)：systemd服务模板。
- [`deploy/fast-deploy.sh`](deploy/fast-deploy.sh)：CI通过后的服务器快速同步脚本。
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml)：依赖安装、前端构建和全量检查门禁。

启用Shell执行前安装沙箱运行时：

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap util-linux
npm install -g @anthropic-ai/sandbox-runtime
srt --version
```

生产数据建议放在`/var/lib/knowflow-ai`，并确保服务用户可写。备份时应在同一停服快照中保存主数据库、LangGraph checkpoint、`skills`、`workspaces`、`tool-results`和`mem0`数据。

## 关键设计

```text
React Web / Linux CLI
          │
       FastAPI + SSE
          │
       LangGraph
   ┌──────┼──────────┐
  RAG   Tools/MCP   Skills
   │        │          │
引用证据  审批与审计  指令与资源
          │
     Mem0长期记忆
```

写入、删除和未知风险工具会暂停Agent并等待一次性批准；只读工具可自动执行。运行轨迹只展示脱敏后的公开输入和结果摘要，不暴露系统提示词、凭据或隐藏推理。

## 开发检查

在仓库根目录运行全部检查：

```powershell
Get-ChildItem tests -Filter "check_*.py" |
  Sort-Object Name |
  ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
```

构建前端：

```powershell
Set-Location frontend
npm run build
```

## 安全边界

- 不要提交`.env`、数据库、上传文件、用户Skills、Workspace、工具结果、Mem0或checkpoint数据。
- 生产环境必须使用HTTPS并更换`KNOWFLOW_SECRET_KEY`。
- 外部工具密钥虽然加密保存，仍应按生产凭据管理。
- 公网部署不要允许私有网络MCP。
- Shell只能通过沙箱运行，且始终需要用户批准。

## 进一步阅读

- [Web搜索Agent循环](docs/langgraph-web-search-loop.md)
- [MCP写操作审批](docs/langgraph-mcp-write-approval.md)
- [Skills与任务计划](docs/langgraph-skills-and-planning.md)
- [长期记忆生命周期](docs/langgraph-memory-lifecycle.md)
- [API调试](docs/api-debug.md)

## 技术栈

FastAPI、SQLAlchemy、React、Vite、LangGraph、Mem0；默认SQLite与本地检索，可选MySQL和Chroma。

## License

[MIT](LICENSE)
