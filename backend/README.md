# AgentLens CLI

AgentLens CLI runs a local BYOK LangGraph Agent in a Linux terminal. The React/Ink
TUI streams model and tool progress, keeps native terminal scrollback by default,
and discovers local tools, MCP servers, and Skills at runtime. `Shift+Tab` cycles
permission modes; write, destructive, and unknown-risk calls still pass through
the Agent approval boundary. Connecting to an AgentLens server remains optional.

## Install

The recommended installation uses `pipx` so the CLI has an isolated Python
environment:

```bash
pipx install "knowflow-ai[agent]"
```

Until the first PyPI release is available, install the current GitHub version:

```bash
pipx install "knowflow-ai[agent] @ git+https://github.com/cs-xdu-dev-001/AgentLens.git#subdirectory=backend"
```

Configure a model and start the local TUI from the project directory:

```bash
agentlens configure
cd /path/to/project
agentlens
```

The bare `agentlens` command asks once before trusting the current directory, then opens Chat with that directory as the workspace. The explicit `agentlens chat` form remains available for scripts and advanced flags.

Optional local capabilities:

```bash
agentlens tools configure web-search
agentlens mcp add notion https://mcp.notion.com/mcp --auth oauth
agentlens skills install ./my-skill
agentlens memory configure
```

Use the legacy line-oriented interface when native terminal scrollback is more
important than the full-screen UI:

```bash
agentlens chat --plain
```

Connecting to an AgentLens Web deployment is optional:

```bash
agentlens auth login https://ai.example.com
agentlens chat --remote
```

## Upgrade and uninstall

```bash
pipx upgrade knowflow-ai
pipx uninstall knowflow-ai
```

Project documentation: <https://github.com/cs-xdu-dev-001/AgentLens>
