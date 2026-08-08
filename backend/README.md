# KnowFlow AI CLI

KnowFlow CLI runs a local BYOK LangGraph Agent in a Linux terminal. The React/Ink
TUI streams model and tool progress, keeps native terminal scrollback by default,
and discovers local tools, MCP servers, and Skills at runtime. `Shift+Tab` cycles
permission modes; write, destructive, and unknown-risk calls still pass through
the Agent approval boundary. Connecting to a KnowFlow server remains optional.

## Install

The recommended installation uses `pipx` so the CLI has an isolated Python
environment:

```bash
pipx install "knowflow-ai[agent]"
```

Until the first PyPI release is available, install the current GitHub version:

```bash
pipx install "knowflow-ai[agent] @ git+https://github.com/cs-xdu-dev-001/KnowFlow-AI.git#subdirectory=backend"
```

Configure a model and start the local TUI:

```bash
knowflow configure
knowflow chat
```

Optional local capabilities:

```bash
knowflow tools configure web-search
knowflow mcp add notion https://mcp.notion.com/mcp --auth oauth
knowflow skills install ./my-skill
knowflow memory configure
```

Use the legacy line-oriented interface when native terminal scrollback is more
important than the full-screen UI:

```bash
knowflow chat --plain
```

Connecting to a KnowFlow Web deployment is optional:

```bash
knowflow auth login https://ai.example.com
knowflow chat --remote
```

## Upgrade and uninstall

```bash
pipx upgrade knowflow-ai
pipx uninstall knowflow-ai
```

Project documentation: <https://github.com/cs-xdu-dev-001/KnowFlow-AI>
