from pathlib import Path
import sys
import re


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_gateway import ModelGateway


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise AssertionError(f"unexpected {label}: {needle}")


class FakeCipher:
    def decrypt(self, value: str | None) -> str:
        return value or ""


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "pong"}}]}


def capture_chat_call(provider: str, model_name: str) -> tuple[str, dict, dict]:
    calls = []

    def post_model_json(url: str, headers: dict, payload: dict) -> FakeResponse:
        calls.append((url, headers, payload))
        return FakeResponse()

    gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        local_embedding=lambda _text: [0.0],
    )
    gateway.chat(
        [{"role": "user", "content": "ping"}],
        {
            "provider": provider,
            "model_name": model_name,
            "base_url": "https://example.com/v1",
            "api_key_cipher": "secret",
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 4096,
        },
    )
    return calls[0]


def main() -> None:
    settings = read("frontend/react/src/data/settings.js")
    settings_page = read("frontend/react/src/components/SettingsPage.jsx")
    model_list = read("frontend/react/src/components/ModelListPanel.jsx")
    provider_doc = read("rag-test-documents/11_model_provider_config.yaml")
    openai = re.search(r'openai:\s*\{([\s\S]*?)\n  \},\n  siliconflow:', settings)
    if not openai:
        raise AssertionError("unable to isolate OpenAI preset block")
    openai_block = openai.group(1)
    openai_objects = re.findall(r'\{([^{}]+)\}', openai_block)
    for model in ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]:
        matches = [obj for obj in openai_objects if f'label: "{model}"' in obj or f'modelName: "{model}"' in obj]
        if len(matches) != 1 or 'apiMode: "responses"' not in matches[0]:
            raise AssertionError(f"OpenAI preset missing responses protocol: {model}")
    embedding_objects = [obj for obj in openai_objects if 'modelType: "embedding"' in obj]
    if any('apiMode: "responses"' in obj for obj in embedding_objects):
        raise AssertionError("OpenAI embedding presets must not use responses protocol")
    for provider in ["deepseek", "mimo", "siliconflow", "zhipu", "bailian"]:
        block = re.search(rf'{provider}:\s*\{{([\s\S]*?)(?=\n  [a-z]+: \{{|\n  custom:)', settings)
        if block and any('apiMode: "responses"' in obj for obj in re.findall(r'\{([^{}]+)\}', block.group(1))):
            raise AssertionError(f"non-OpenAI provider incorrectly uses responses: {provider}")

    for model in [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "mimo-v2.5-pro",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "text-embedding-3-large",
        "deepseek-ai/DeepSeek-V4-Flash",
        "deepseek-ai/DeepSeek-V4-Pro",
        "glm-5.2",
        "glm-5-turbo",
        "glm-4.7",
        "qwen3.7-max",
        "qwen3.7-plus",
        "qwen3.6-plus",
    ]:
        require(settings, model, "current model preset")

    require(settings, "https://api.xiaomimimo.com/v1", "current MiMo API base URL")
    require(settings_page, 'modelName: "deepseek-v4-flash"', "DeepSeek V4 default model")
    require(model_list, 'mimo: "MiMo"', "MiMo provider display name")

    for old_model in ["deepseek-chat", "deepseek-reasoner", "mimo-v2-pro", "mimo-v2-flash"]:
        forbid(settings, old_model, "deprecated preset model")

    for model in ["deepseek-v4-flash", "gpt-5.6-sol", "qwen3.7-max", "mimo-v2.5-pro"]:
        require(provider_doc, model, "provider reference document model")

    _url, headers, payload = capture_chat_call("openai", "gpt-5.6-sol")
    require(headers["Authorization"], "Bearer secret", "OpenAI bearer header")
    require(str(payload), "max_completion_tokens", "OpenAI modern token limit field")
    if "max_tokens" in payload:
        raise AssertionError("OpenAI chat payload should not use deprecated max_tokens")

    _url, headers, payload = capture_chat_call("mimo", "mimo-v2.5-pro")
    require(headers["api-key"], "secret", "MiMo api-key header")
    require(str(payload), "max_completion_tokens", "MiMo token limit field")

    _url, _headers, payload = capture_chat_call("deepseek", "deepseek-v4-flash")
    require(str(payload), "max_tokens", "generic OpenAI-compatible token limit field")

    print("model provider presets use current compatible model names")


if __name__ == "__main__":
    main()
