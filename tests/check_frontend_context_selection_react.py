from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_many(paths: list[str]) -> str:
    return "\n".join(read(path) for path in paths)


def require_text(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def forbid_text(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"unexpected {label}: {needle}")


def main() -> None:
    controller_surface = read_many([
        "frontend/react/src/controller/knowflowController.js",
        "frontend/react/src/controller/controllerState.js",
        "frontend/react/src/controller/bridgeBindings.js",
        "frontend/react/src/controller/chatFlow.js",
        "frontend/react/src/controller/catalogSync.js",
    ])

    for token, label in [
        ("selectedChatModelConfigId", "controller chat model selection state"),
        ("selectedChatKnowledgeBaseId", "controller chat knowledge selection state"),
        ("selectedDocumentKnowledgeBaseId", "controller document knowledge selection state"),
        ("selectedRetrievalKnowledgeBaseId", "controller retrieval knowledge selection state"),
        ("resolveChatModelConfigId", "chat model resolver"),
        ("state.selectedChatModelConfigId = value", "chat model event updates state"),
        ("state.selectedChatKnowledgeBaseId = value", "chat knowledge event updates state"),
        ("state.selectedDocumentKnowledgeBaseId", "document knowledge state used for refresh"),
        ("const knowledgeBaseId = retryRequest?.payload?.knowledgeBaseId", "chat payload still supports retry snapshot"),
        ("state.selectedChatKnowledgeBaseId ? Number(state.selectedChatKnowledgeBaseId) : null", "chat payload reads React-owned kb state"),
        ("state.selectedChatModelConfigId ? Number(state.selectedChatModelConfigId) : null", "chat payload reads React-owned model state"),
    ]:
        require_text(controller_surface, token, label)

    for needle, label in [
        ('$("#chat-model-select")', "legacy chat model select read"),
        ('$("#chat-kb-select")', "legacy chat knowledge select read"),
        ('$("#composer-kb-select")', "legacy composer knowledge select read"),
        ('$("#doc-kb-select")', "legacy document knowledge select read"),
        ('$("#retrieval-kb-select")', "legacy retrieval knowledge select read"),
        ('$("#kb-embedding-select")', "legacy embedding select read"),
        ('$("#active-session")', "legacy active session input write"),
        ("function restoreSelectValue", "legacy select value restorer"),
        ("function syncMainSelectFromComposer", "legacy composer-to-main select sync"),
    ]:
        forbid_text(controller_surface, needle, label)

    print("context selections are tracked through React events instead of DOM selects")


if __name__ == "__main__":
    main()
