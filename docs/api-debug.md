# AgentLens接口调试文档

本文档用于配合 FastAPI 自动生成的 Swagger UI 调试接口，作用类似 Spring Boot 项目中的 Knife4j 页面。

## 调试入口

| 入口 | 地址 | 用途 |
| --- | --- | --- |
| Swagger UI | `http://127.0.0.1:8000/docs` | 在线查看接口、填写参数并直接发送请求 |
| ReDoc | `http://127.0.0.1:8000/redoc` | 阅读版接口文档 |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` | 前端或工具导入接口定义 |
| 健康检查 | `http://127.0.0.1:8000/api/health` | 检查服务、数据库和向量后端状态 |

## 接口分组

### 系统调试

- `GET /api/health`：服务健康检查。
- `GET /api/runtime`：查看数据库类型、向量库后端和脱敏后的数据库地址。

### 认证授权

- `POST /api/auth/register`：注册本地账号。
- `POST /api/auth/login`：本地账号登录。
- `GET /api/auth/me`：查询当前登录用户和 OAuth 配置状态。
- `POST /api/auth/logout`：退出登录。
- `GET /api/auth/oauth/github/start`：GitHub OAuth 登录入口。

### 模型配置

- `POST /api/model-configs`：新增模型配置。
- `GET /api/model-configs`：查询模型配置列表，可用 `modelType` 过滤。
- `POST /api/model-configs/{id}/test`：测试模型连接。
- `POST /api/model-configs/{id}/default`：设置默认模型。

### 知识库

- `POST /api/knowledge-bases`：创建知识库，创建时绑定 Embedding 模型配置。
- `GET /api/knowledge-bases`：查询当前用户的知识库列表。
- `PUT /api/knowledge-bases/{id}`：更新名称和描述。
- `DELETE /api/knowledge-bases/{id}`：删除知识库及其文档数据。

### 文档入库

- `POST /api/knowledge-bases/{knowledgeBaseId}/documents`：上传文档，返回 `documentId` 和 `taskId`。
- `GET /api/knowledge-bases/{knowledgeBaseId}/documents`：查询文档列表和最新后台任务。
- `GET /api/documents/{documentId}`：查询文档处理状态。
- `GET /api/documents/{documentId}/tasks`：查询文档后台任务历史。
- `GET /api/documents/{documentId}/chunks`：查看文档切片。
- `POST /api/documents/{documentId}/reindex`：重新解析并向量化文档。

支持格式包括：`txt`、`md`、`pdf`、`docx`、`xlsx`、`pptx`、`html`、`json`、`csv`、`tsv`、`rtf`、`yaml`、`xml`、`log`。

### RAG 调试

- `POST /api/retrieval/debug`：输入知识库 ID、问题和 Top-K，查看召回片段、匹配分数、命中词、质量判断和向量后端。
- `GET /api/retrieval/runs/{run_id}`：查询一次检索运行的持久化详情，包括 `quality`、`hitCount`、`maxScore`、`qualityLevel`、`durationMs` 和关联消息。

示例请求：

```json
{
  "knowledgeBaseId": 1,
  "query": "RAG 如何降低幻觉？",
  "topK": 5
}
```

示例响应中的核心字段：

```json
{
  "quality": {
    "enabled": true,
    "hitCount": 3,
    "maxScore": 0.82,
    "qualityLevel": "strong",
    "reason": "召回片段与问题匹配度较高。",
    "suggestions": []
  },
  "retrievalRun": {
    "id": 12,
    "knowledgeBaseId": 1,
    "status": "success",
    "durationMs": 18
  },
  "chunks": [
    {
      "rank": 1,
      "score": 0.82,
      "matchedTerms": ["RAG", "幻觉"]
    }
  ]
}
```

### 对话问答

- `POST /api/chat`：普通 JSON 问答。
- `POST /api/chat/stream`：SSE 流式问答。
- `POST /api/chat/attachments`：上传对话附件或截图内容。
- `GET /api/messages/{messageId}/references`：查看回答引用了哪些文档片段。

### 会话管理

- `GET /api/sessions`：查询当前用户的会话列表。
- `GET /api/sessions/{sessionId}/messages`：查询会话消息。
- `PUT /api/sessions/{sessionId}`：重命名会话。
- `DELETE /api/sessions/{sessionId}`：删除会话。

### 扩展接口

- `POST /api/agent/chat`：工具增强问答。
- `GET /api/sessions/{sessionId}/tool-calls`：查询会话工具调用记录。
- `POST /api/sync/tasks`：创建内容同步任务记录。
- `POST /api/publish/github`：GitHub 发布预留接口。

## 常见调试流程

1. 打开 `GET /api/health`，确认服务运行正常。
2. 注册或登录账号。
3. 新增 Chat / Embedding 模型配置。
4. 调用 `POST /api/model-configs/{id}/test` 测试模型是否可用。
5. 创建知识库并绑定 Embedding 模型。
6. 上传文档，确认后台任务最终进入 `success / done / 100` 状态。
7. 使用 `POST /api/retrieval/debug` 调试 RAG 召回效果，并用 `GET /api/retrieval/runs/{run_id}` 回看检索质量记录。
8. 使用 `POST /api/chat/stream` 调试最终问答效果。

## 说明

当前版本优先保证模型配置、用户数据隔离、文档后台任务、文档入库、RAG 检索和对话问答主链路。多步工具编排与外部同步接口保留在扩展分组中，不作为第一版核心展示重点。
