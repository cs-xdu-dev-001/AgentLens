# Skill 管理与按需激活设计

日期：2026-07-27

## 1. 目标

KnowFlow AI 已具备原生 Agent 工具循环、联网搜索、MCP、OAuth、写操作审批和可回放运行轨迹。本阶段在这些能力之上增加可管理、可选择、可自动激活的 Skill 系统。

Skill 是一组任务说明、参考资料和工具依赖声明，不是新的工具权限。用户可以从 GitHub 或 ZIP 安装 Skill，在独立管理页启停，并在对话输入框中通过 `/` 明确选择。未明确选择时，模型可以从当前用户已启用的 Skill 中自主选择一个。

本阶段不执行 Skill 附带脚本，不实现多 Skill 协作、子 Agent、在线 Skill 编辑器、私有 GitHub Token 或通用代码沙箱。

## 2. 已确认的产品原则

- 用户导入的 Skill、配置、启停状态和运行记录按登录用户隔离。
- 内置 Skill 对所有用户可见，但每个用户独立决定是否启用，且不能删除内置包。
- 第一版支持公开 GitHub 仓库导入和 ZIP 上传。
- `scripts/` 可以保存和查看，但不能由服务器执行。
- 每次 Agent 运行最多激活一个 Skill。
- Skill 可以编排当前用户已经授权的原生工具与 MCP，但不能增加权限、读取其他用户配置或绕过审批。
- 管理界面保持轻量，不使用统计仪表盘、厚重卡片或常驻详情面板。
- 对话输入 `/` 打开 Skill 选择器，行为接近 Codex。

## 3. Skill 包格式

每个 Skill 包必须包含一个根级 `SKILL.md`。正文使用 Markdown，文件开头使用 YAML front matter。

最低兼容字段：

```yaml
---
name: notion-research
description: 搜索 Notion 与网络资料，生成带来源的结构化调研。
---
```

KnowFlow 扩展字段放在 `metadata.knowflow` 下，避免污染基础字段：

```yaml
---
name: notion-research
description: 搜索 Notion 与网络资料，生成带来源的结构化调研。
metadata:
  knowflow:
    display_name: Notion 调研整理
    version: 1.2.0
    required_tools:
      - web_search
    required_mcp:
      - notion
---
```

规则：

- `name` 和 `description` 必填。
- `name` 使用稳定的 ASCII slug，安装后不可通过前端修改。
- `display_name`、`version`、`required_tools` 和 `required_mcp` 可选。
- 未声明版本时使用 `0.0.0`。
- `references/` 和静态资源可以被运行器按需读取。
- `scripts/` 只作为不可执行资源保存。
- 未识别的扩展字段保留在元数据中，但不影响权限判断。

## 4. 数据模型

### 4.1 `skill_package`

保存不可变的 Skill 内容快照及来源：

- `id`
- `owner_user_id`：内置包为空，个人包必须绑定用户
- `slug`
- `name`
- `description`
- `version`
- `source_kind`：`builtin`、`github` 或 `upload`
- `source_url`
- `source_ref`
- `source_subpath`
- `content_hash`
- `package_path`
- `manifest_json`
- `created_at`

`package_path` 只保存相对于对应受信根目录的路径。个人包使用 `UNIQUE(owner_user_id, slug, content_hash)` 防止重复快照。

### 4.2 `user_skill`

保存用户与 Skill 快照之间的安装关系：

- `id`
- `user_id`
- `skill_package_id`
- `skill_slug`：与当前快照 slug 一致，用于数据库唯一约束
- `enabled`
- `installed_at`
- `updated_at`

同一用户同一 `slug` 只有一个当前安装关系，数据库使用 `UNIQUE(user_id, skill_slug)` 约束。更新 Skill 时先创建并验证新快照，再原子切换 `skill_package_id`。前端、管理 API 和 `ChatRequest.skillId` 使用稳定的 `user_skill.id`；运行历史另存版本与内容哈希，不能通过当前安装关系反推历史版本。

### 4.3 运行记录

Assistant 消息的运行快照和工具审计记录增加：

- `skill_id`
- `skill_slug`
- `skill_version`
- `skill_content_hash`

运行历史记录实际使用的版本，而不是读取当前安装版本。

### 4.4 文件布局

个人 Skill 使用服务端生成路径：

```text
data/
  skills/
    <user_id>/
      <skill_id>/
        <content_hash>/
          SKILL.md
          references/
          scripts/
```

任何上传文件名、Skill slug 或仓库路径都不能直接参与最终磁盘路径拼接。个人 `package_path` 相对 `KNOWFLOW_SKILL_DIR` 解析；内置 `package_path` 相对仓库内的只读 `backend/knowflow/builtin_skills` 解析。数据库永不保存绝对路径。

## 5. 导入与更新

### 5.1 GitHub

第一版只接受公开 `https://github.com/<owner>/<repo>` 地址。服务端解析 owner、repo、ref 和子目录后，自行构造固定 GitHub 下载地址，不请求用户提供的任意 URL，也不跟随到非 GitHub 主机。

不保存 GitHub Token。私有仓库使用 ZIP 上传。

### 5.2 ZIP

上传和 GitHub 下载共享同一套归档校验：

- 限制压缩体积、解压总体积、文件数量、单文件体积和目录深度。
- 拒绝绝对路径、`..` 路径穿越、符号链接、硬链接和设备文件。
- 拒绝嵌套压缩包。
- 允许 Markdown、纯文本、JSON、YAML、CSV、常见脚本源码、PNG、JPEG、GIF、WebP、SVG 和 PDF；脚本源码只能作为文本资源读取，不能执行。
- 拒绝 EXE、DLL、共享库、安装包、磁盘映像以及 ZIP、TAR、GZIP、7Z、RAR 等嵌套归档。
- 激活后可通过内部只读能力读取当前快照 `references/` 下的 UTF-8 文本；拒绝 `scripts/`、路径穿越、链接、二进制内容和超过 20,000 字符的结果。图片和 PDF 第一版只保存与展示元数据，不送入当前纯文本模型网关。
- 临时目录和最终目录都由服务端生成。
- 校验完成前不得进入正式 Skill 目录或数据库安装关系。

默认限制为：压缩下载或上传不超过 5 MiB、解压总量不超过 20 MiB、文件不超过 200 个、单文件不超过 2 MiB、目录深度不超过 8 层、`SKILL.md` 正文不超过 50,000 个字符、临时导入 15 分钟后过期。所有限制通过有上限约束的环境变量配置，生产环境不能关闭。

### 5.3 两阶段安装

1. `inspect` 下载或接收归档，在用户私有临时目录解析并返回预览。
2. 用户确认后使用短期 `import_id` 安装。

临时导入记录绑定 `user_id`、内容哈希和过期时间。错误用户访问与不存在记录使用相同响应。安装成功或过期后清理临时目录。

### 5.4 更新与卸载

- GitHub Skill 可以检查来源 ref 的新内容哈希。
- 更新先完整下载、校验并创建新快照，再切换安装关系。
- 更新失败继续保留原版本。
- 上传 Skill 不支持自动检查更新，可以重新上传替换。
- 卸载时先提交数据库删除，再尽力清理不再引用的文件快照。
- 内置 Skill 不能卸载，只能按用户停用。

## 6. API

所有接口从认证会话获取用户，不接受客户端传入 `user_id`。

- `GET /api/skills`
- `GET /api/skills/{skill_id}`
- `GET /api/skills/{skill_id}/content`
- `POST /api/skills/import/github/inspect`
- `POST /api/skills/import/upload/inspect`
- `POST /api/skills/import/{import_id}/install`
- `PATCH /api/skills/{skill_id}`
- `POST /api/skills/{skill_id}/check-update`
- `POST /api/skills/{skill_id}/update`
- `DELETE /api/skills/{skill_id}`

`PATCH` 第一版只允许修改 `enabled`。

错误使用稳定机器码：

- `skill_not_found`
- `skill_invalid_manifest`
- `skill_import_rejected`
- `skill_import_too_large`
- `skill_import_expired`
- `skill_dependency_missing`
- `skill_disabled`
- `skill_slug_conflict`
- `skill_unavailable`

访问不存在的资源和其他用户资源都返回相同的 `404 skill_not_found`。原始异常、服务器路径和堆栈不返回前端。

## 7. 管理界面

左侧导航增加独立 `Skills` 入口。页面使用轻量列表：

- 页头只有标题、说明和“安装”按钮。
- “已安装”和“内置”两个标签页。
- 一个搜索框，状态筛选固定为“全部、已启用、未启用、不可用”。
- 每行显示图标、名称、一行描述、依赖摘要、启停开关和 `⋯` 菜单。
- 更新、查看 `SKILL.md` 和卸载放入 `⋯` 菜单。
- 点击名称时临时打开详情侧栏；侧栏不常驻。
- 缺依赖只在对应行显示一条简短提示。

安装使用单个轻量弹窗。GitHub 和 ZIP 使用两个标签页；检查成功后在同一弹窗展示名称、版本、文件摘要和依赖状态。加载、失败和成功在原位置替换，不增加独立流程页。

启停采用请求完成后再确认状态的方式。请求失败时恢复原开关状态并显示简短就地提示。

## 8. `/` 选择器

在空白处或词首输入 `/` 打开当前用户的 Skill 选择器：

- 继续输入时按名称、slug 和描述模糊筛选。
- 支持鼠标、方向键、Enter 和 Escape。
- 只展示已启用且当前依赖可用的 Skill。
- 列表显示名称、一行描述和“个人/内置”来源。
- 底部提供“管理 Skills”入口。
- 没有可用 Skill 时显示“前往安装 Skill”。

选中后，输入内容中的查询文本替换为不可编辑的 Skill 标签。每条消息最多选择一个 Skill。前端发送稳定 `skillId`，不能把显示名称作为授权依据。

未显式选择 Skill 时，模型仍可自主选择。

## 9. Agent 激活

### 9.1 显式激活

聊天请求增加可选 `skillId`。后端在第一次模型调用前验证：

- Skill 对当前用户可见。
- 已安装并启用。
- 所需原生工具已配置。
- 所需 MCP 已连接并启用。
- 内容快照仍存在且哈希匹配。

通过后加载 `SKILL.md`，记录 Skill 运行节点，并将正文包在固定安全边界中加入本轮上下文。

### 9.2 自动激活

没有 `skillId` 时，只向模型提供当前用户已启用 Skill 的 `slug`、名称和描述。内部注册只读的 `activate_skill` 能力。模型调用后，服务端重新执行所有权限和依赖校验，再把完整说明返回给下一轮模型调用。

每次运行只允许成功激活一个 Skill。激活后移除或拒绝后续 `activate_skill` 调用。

### 9.3 指令与权限边界

基础系统规则始终优先。Skill 内容会附带固定说明：

- Skill 是用户安装的任务指导，不是新的系统权限。
- 不能覆盖安全策略、用户隔离或审批要求。
- 不能直接访问密钥、数据库或文件系统。
- 只能调用本轮 `ToolRegistry` 已注册的能力。
- 写操作继续进入现有审批流程。

显式 Skill 不可用时请求返回明确错误。自动激活失败时，将结构化、脱敏的错误作为工具结果交还模型，允许模型不用 Skill 继续回答。

## 10. 运行图与历史

激活 Skill 时产生真实 `skill` 类型步骤，展示名称、版本、来源和依赖摘要。完整 Skill 正文不写入公开 trace。

后续由该 Skill 发起的 MCP、Tool 和 Model 步骤使用 Skill 步骤作为 `parentId`：

```text
MODEL 选择能力
  └─ SKILL Notion 调研整理
       ├─ MCP notion-search
       ├─ TOOL web_search
       └─ MODEL 整理结果
```

显式 Skill 在第一次模型调用前显示为已激活。自动 Skill 先显示模型选择步骤，再显示 Skill 激活步骤。历史回放使用消息保存的名称、版本和内容哈希，不依赖当前安装状态。

## 11. 失败处理

- 导入校验失败不创建正式 Skill 或安装关系。
- 缺依赖的 Skill可以安装但默认停用；用户连接依赖后再启用。
- 启用时再次检查依赖，避免使用过期页面状态。
- Skill 文件丢失或哈希不匹配时标记为不可用，不能静默加载其他版本。
- 数据库写入失败时不删除当前有效快照。
- 文件清理失败记录脱敏日志，不回滚已提交的数据库卸载。
- 前端根据稳定错误码显示中文文案，不打印原始服务端异常。

## 12. 测试与验收

后端新增检查覆盖：

- YAML front matter 和 KnowFlow 扩展字段解析。
- GitHub URL 规范化、主机限制和重定向限制。
- ZIP 路径穿越、链接、嵌套压缩包和各项资源上限。
- 临时导入的用户隔离、过期和重复安装。
- Skill 列表、详情、启停、更新和卸载的用户隔离。
- 内置 Skill 的用户级启停和禁止卸载。
- 显式 Skill 激活、自动激活、单 Skill 上限和依赖检查。
- Skill 内容不能扩大 ToolRegistry 权限或绕过审批。
- Trace 嵌套、脱敏、持久化和历史回放。
- SQLite 与 MySQL 的结构初始化和升级。

前端新增检查覆盖：

- Skills 导航、轻量列表和安装弹窗。
- `/` 打开、过滤、键盘操作、选择、移除和发送 `skillId`。
- 空列表、依赖缺失、启停失败和 401 登录状态同步。
- Skill 运行节点与现有 Tool/MCP 运行图兼容。
- 窄屏和宽屏下输入框与选择器不溢出。

完整验证：

```text
所有 tests/check_*.py
frontend npm run build
git diff --check
敏感信息与忽略文件检查
```

不得提交 `backend/.env`、数据库、用户 Skill 包、上传文件、`frontend/dist`、Token 或 Key。

## 13. 配置与部署

`backend/.env.example` 和 README 记录 Skill 导入限额、临时导入过期时间和持久化目录。默认配置必须适合单机部署并保持脚本执行关闭。

代码通过 Git 提交和推送到 `origin/main`。服务器拉取代码后运行数据库升级和全量检查，再重启服务。用户安装的 Skill 数据与数据库保存在服务器持久化目录，不进入 Git，也不会因代码更新被覆盖。

生产服务用户必须对 Skill 数据目录具有读写权限。部署检查不得回显任何环境变量值、OAuth Secret、Token 或 Skill 私有内容。

## 14. 本阶段不做

- 执行 Skill 自带 Python、Shell、Node 或其他脚本
- 通用文件系统或终端工具
- 私有 GitHub OAuth/Token
- 在线编辑或创建 Skill
- 多 Skill 同时激活
- Skill 调用子 Agent
- Skill 市场、评分和公开分享
- 跨用户共享个人 Skill
- 后台定时运行 Skill
