# AgentLens

AgentLens是一个可自行部署、过程可见的AI Agent与知识库。它把对话、RAG、工具、MCP、Skills、长期记忆和任务执行统一在Web与Linux TUI中。

!!! info "当前定位"
    当前版本适合个人使用、学习Agent工程和在受控Linux环境中测试。Web可在Windows上开发和访问，Agent执行与TUI优先支持Linux。

## 核心能力

- **观察Agent如何工作**：实时查看模型、工具、MCP、记忆、审批与验证步骤。
- **从失败处恢复**：LangGraph checkpoint保存运行状态，支持继续和按范围重试。
- **连接自己的模型**：可配置OpenAI兼容端点，并为模型选择Chat Completions或Responses API。
- **安全使用外部能力**：联网搜索、MCP、Skills、Mem0和工作区工具按需启用，写操作需要确认。
- **Web与TUI双入口**：浏览器适合知识库与运行观察，Linux TUI适合在项目目录中执行任务。

## 从这里开始

| 你想做什么 | 前往 |
| --- | --- |
| 安装Linux CLI或启动本地Web | [使用指南](usage.md) |
| 理解Web、TUI、LangGraph和数据层如何协作 | [系统架构](architecture.md) |
| 接入或消费运行事件 | [Agent事件协议](agent-event-protocol.md) |
| 理解搜索、审批、Skills与记忆链路 | [开发者指南](langgraph-web-search-loop.md) |

## 五分钟体验Linux CLI

```bash
sudo apt-get update && sudo apt-get install -y python3-venv git
curl -fsSL https://raw.githubusercontent.com/cs-xdu-dev-001/AgentLens/main/install.sh | sh
agentlens configure
agentlens doctor --cli
agentlens chat --workspace /path/to/project
```

`agentlens configure`会通过隐藏输入保存API Key。不要把Key写进命令、截图、Issue或仓库文件。

## 运行边界

- 工作区是Agent可见、可改和可执行工具的范围，不等同于任意当前目录。
- 读取工具可以自动执行；写入、删除和未知风险操作会暂停等待确认。
- Shell仅通过受限沙箱执行，不应通过关闭系统安全策略来换取可用性。
- 用户模型、工具密钥、MCP连接、Skills、知识库和长期记忆相互隔离。
- 生产部署使用HTTPS、非root服务用户和单worker，并备份全部运行状态。

## 项目入口

- [GitHub仓库](https://github.com/cs-xdu-dev-001/AgentLens)
- [使用指南](usage.md)
- [系统架构](architecture.md)
- [问题反馈](https://github.com/cs-xdu-dev-001/AgentLens/issues)
