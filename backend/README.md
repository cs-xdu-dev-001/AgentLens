# KnowFlow AI CLI

KnowFlow CLI connects a Linux terminal to a KnowFlow AI server and exposes the
same Agent, tools, MCP, Skills, memory, approvals, and run history as the web
application.

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

Then connect to a server:

```bash
knowflow auth login https://ai.example.com
knowflow chat
```

The default package is the lightweight remote CLI. For local direct mode on a
dedicated Linux machine, install the optional runtime dependencies:

```bash
pipx install "knowflow-ai[local]"
knowflow doctor
```

Local direct mode opens the server database and runtime storage. Do not run it
concurrently with the KnowFlow web service against the same data directory.

## Upgrade and uninstall

```bash
pipx upgrade knowflow-ai
pipx uninstall knowflow-ai
```

Project documentation: <https://github.com/cs-xdu-dev-001/KnowFlow-AI>
