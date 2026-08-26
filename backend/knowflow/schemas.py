from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

from .config import DEFAULT_TOP_K


class ModelConfigIn(BaseModel):
    name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    modelType: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    apiKey: str = ""
    modelName: str = Field(min_length=1)
    temperature: float | None = None
    topP: float | None = None
    maxTokens: int | None = None
    apiMode: str = "chat_completions"


class ModelConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    modelType: str | None = None
    baseUrl: str | None = None
    apiKey: str | None = None
    modelName: str | None = None
    temperature: float | None = None
    topP: float | None = None
    maxTokens: int | None = None
    apiMode: str | None = None


class ToolConfigUpdate(BaseModel):
    enabled: bool
    apiKey: str | None = None


class MemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MemoryContentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=12000)


class KnowledgeBaseIn(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    embeddingModelConfigId: int


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ChatAttachment(BaseModel):
    filename: str
    fileType: str | None = None
    mimeType: str | None = None
    content: str = ""
    previewUrl: str | None = None


class ChatRequest(BaseModel):
    knowledgeBaseId: int | None = None
    sessionId: str | None = None
    question: str = Field(min_length=1)
    chatModelConfigId: int | None = None
    reasoningEffort: Literal[
        "default", "none", "low", "medium", "high", "xhigh", "max"
    ] = "default"
    useRag: bool = False
    autoAgent: bool = True
    enableTools: bool = False
    toolMode: str = "auto"
    enabledTools: list[str] = Field(default_factory=list)
    skillId: int | None = None
    executionMode: Literal["auto", "plan_only"] = "auto"
    attachments: list[ChatAttachment] = []


class RetrievalDebugRequest(BaseModel):
    knowledgeBaseId: int
    query: str = Field(min_length=1)
    topK: int = DEFAULT_TOP_K


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1)


class SessionPinUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pinned: bool


class SessionArchiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archived: bool


class SessionBranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=255)
    beforeMessageId: int | None = Field(default=None, gt=0)


class SessionContextCompactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instructions: str = Field(default="", max_length=2000)


class SyncTaskIn(BaseModel):
    sourceType: str
    sourceUrl: str = ""
    targetType: str = "knowledge_base"
    knowledgeBaseId: int | None = None


class GithubPublishIn(BaseModel):
    repo: str
    branch: str = "main"
    path: str
    content: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    displayName: str | None = None


class LoginIn(BaseModel):
    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class CliDeviceStartIn(BaseModel):
    clientName: str = Field(default="AgentLens CLI", max_length=100)


class CliDeviceDecisionIn(BaseModel):
    userCode: str = Field(min_length=10, max_length=16)
    decision: Literal["approve", "deny"]


class CliDeviceTokenIn(BaseModel):
    deviceCode: str = Field(min_length=32, max_length=200)

class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preset: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, max_length=500)
    authType: Literal["none", "headers", "oauth"] = "none"
    headers: dict[str, str] | None = None
    clientId: str | None = Field(default=None, max_length=255)
    clientSecret: str | None = Field(default=None, max_length=2048)
    enabled: bool = True
    enabledTools: list[str] = Field(default_factory=list)

class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    authType: Literal["none", "headers", "oauth"] | None = None
    headers: dict[str, str] | None = None
    clientId: str | None = Field(default=None, max_length=255)
    clientSecret: str | None = Field(default=None, max_length=2048)
    enabled: bool | None = None
    enabledTools: list[str] | None = None

class McpOAuthStartIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    returnTo: str = Field(min_length=1, max_length=500)

class AgentApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["allow_once", "deny", "timeout"]


class SkillGitHubInspect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="main", min_length=1, max_length=200)
    subpath: str = Field(default="", max_length=500)


class SkillInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False


class SkillPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class SkillUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


McpServerIn = McpServerCreate
