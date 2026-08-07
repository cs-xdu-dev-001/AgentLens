# KnowFlow AI CLI

KnowFlow CLI runs a local BYOK LangGraph Agent in a Linux terminal. Interactive
sessions use a full-screen TUI with streaming output, tool progress, and write
approval. Connecting to an existing KnowFlow server remains optional.

## Install

The recommended installation uses `pipx` so the CLI has an isolated Python
environment:

```bash
pipx install knowflow-ai
```

Until the first PyPI release is available, install the current GitHub version:

```bash
pipx install "git+https://github.com/cs-xdu-dev-001/KnowFlow-AI.git#subdirectory=backend"
```

Configure a model and start the local TUI:

```bash
knowflow configure
knowflow chat
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
