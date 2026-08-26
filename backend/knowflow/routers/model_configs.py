from fastapi import APIRouter

from ..runtime import *
from ..services.model_gateway import test_model_protocols

router = APIRouter()

MODEL_TAGS = ["Model Configuration"]
ALLOWED_API_MODES = {"chat_completions", "responses"}


def validate_api_mode(model_type: str, api_mode: str) -> None:
    if api_mode not in ALLOWED_API_MODES:
        raise HTTPException(status_code=400, detail="apiMode must be chat_completions or responses.")
    if api_mode == "responses" and model_type != "chat":
        raise HTTPException(status_code=400, detail="responses API mode is only supported for chat models.")


@router.post("/api/model-configs", tags=MODEL_TAGS, summary="Create a model configuration")
def create_model_config(payload: ModelConfigIn, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    validate_api_mode(payload.modelType, payload.apiMode)
    model_id = execute(
        """
        INSERT INTO model_config(
          user_id, name, provider, model_type, base_url, api_key_cipher, model_name,
          temperature, top_p, max_tokens, api_mode, created_at, updated_at
        )
        VALUES (
          :user_id, :name, :provider, :model_type, :base_url, :api_key_cipher, :model_name,
          :temperature, :top_p, :max_tokens, :api_mode, :created_at, :updated_at
        )
        """,
        {
            "user_id": user_id,
            "name": payload.name,
            "provider": payload.provider,
            "model_type": payload.modelType,
            "base_url": payload.baseUrl,
            "api_key_cipher": cipher.encrypt(payload.apiKey),
            "model_name": payload.modelName,
            "temperature": payload.temperature,
            "top_p": payload.topP,
            "max_tokens": payload.maxTokens,
            "api_mode": payload.apiMode,
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    row = fetch_one("SELECT * FROM model_config WHERE id=:id AND user_id=:user_id", {"id": model_id, "user_id": user_id})
    return api_success(normalize_model_config(row))


@router.get("/api/model-configs", tags=MODEL_TAGS, summary="List model configurations")
def list_model_configs(request: Request, modelType: str | None = None) -> dict[str, Any]:
    user_id = current_user_id(request)
    if modelType:
        rows = fetch_all("SELECT * FROM model_config WHERE model_type=:model_type AND user_id=:user_id ORDER BY id DESC", {"model_type": modelType, "user_id": user_id})
    else:
        rows = fetch_all("SELECT * FROM model_config WHERE user_id=:user_id ORDER BY id DESC", {"user_id": user_id})
    return api_success([normalize_model_config(row) for row in rows])


@router.get("/api/model-configs/{config_id}", tags=MODEL_TAGS, summary="Read a model configuration")
def read_model_config(config_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    row = fetch_one("SELECT * FROM model_config WHERE id=:id AND user_id=:user_id", {"id": config_id, "user_id": user_id})
    if not row:
        raise HTTPException(status_code=404, detail="Model configuration not found.")
    return api_success(normalize_model_config(row))


@router.put("/api/model-configs/{config_id}", tags=MODEL_TAGS, summary="Update a model configuration")
def update_model_config(config_id: int, payload: ModelConfigUpdate, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    current = fetch_one("SELECT * FROM model_config WHERE id=:id AND user_id=:user_id", {"id": config_id, "user_id": user_id})
    if not current:
        raise HTTPException(status_code=404, detail="Model configuration not found.")
    data = payload.model_dump(exclude_unset=True)
    mapping = {
        "name": "name",
        "provider": "provider",
        "modelType": "model_type",
        "baseUrl": "base_url",
        "apiKey": "api_key_cipher",
        "modelName": "model_name",
        "temperature": "temperature",
        "topP": "top_p",
        "maxTokens": "max_tokens",
        "apiMode": "api_mode",
    }
    effective_type = data.get("modelType", current["model_type"])
    effective_mode = data.get("apiMode", current.get("api_mode") or "chat_completions")
    validate_api_mode(effective_type, effective_mode)
    assignments: list[str] = []
    params: dict[str, Any] = {"id": config_id, "user_id": user_id, "updated_at": now_str()}
    for key, value in data.items():
        column = mapping[key]
        assignments.append(f"{column}=:{column}")
        params[column] = cipher.encrypt(value) if key == "apiKey" and value is not None else value
    if assignments:
        assignments.append("updated_at=:updated_at")
        execute(f"UPDATE model_config SET {', '.join(assignments)} WHERE id=:id AND user_id=:user_id", params)
    return read_model_config(config_id, request)


@router.delete("/api/model-configs/{config_id}", tags=MODEL_TAGS, summary="Delete a model configuration")
def delete_model_config(config_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    execute("DELETE FROM model_config WHERE id=:id AND user_id=:user_id", {"id": config_id, "user_id": user_id})
    return api_success(True)


@router.post("/api/model-configs/{config_id}/test", tags=MODEL_TAGS, summary="Test a model connection")
def test_model_config(config_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    config = fetch_one("SELECT * FROM model_config WHERE id=:id AND user_id=:user_id", {"id": config_id, "user_id": user_id})
    if not config:
        raise HTTPException(status_code=404, detail="Model configuration not found.")
    result = test_model_protocols(gateway, config)
    status = result["status"]
    execute("UPDATE model_config SET status=:status, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"status": status, "updated_at": now_str(), "id": config_id, "user_id": user_id})
    return api_success(result)


@router.post("/api/model-configs/{config_id}/default", tags=MODEL_TAGS, summary="Set the default model")
def set_default_model(config_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    config = fetch_one("SELECT * FROM model_config WHERE id=:id AND user_id=:user_id", {"id": config_id, "user_id": user_id})
    if not config:
        raise HTTPException(status_code=404, detail="Model configuration not found.")
    execute("UPDATE model_config SET is_default=0 WHERE model_type=:model_type AND user_id=:user_id", {"model_type": config["model_type"], "user_id": user_id})
    execute("UPDATE model_config SET is_default=1, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"updated_at": now_str(), "id": config_id, "user_id": user_id})
    return api_success(True)
