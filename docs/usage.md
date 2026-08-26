# 使用指南

## 选择入口

| 场景 | 推荐入口 | 环境要求 |
| --- | --- | --- |
| 在Linux项目目录中运行Agent | `agentlens chat` | Linux、Python 3.10+、Node.js 22+ |
| 使用已部署的AgentLens | Web或`agentlens chat --remote` | 现代浏览器或Linux CLI |
| 修改和调试项目 | 本地Web开发 | Python 3.10+、Node.js 18+、npm |
| 自行部署服务 | systemd与HTTPS反向代理 | 推荐Ubuntu 24.04 |

## 安装Linux CLI

```bash
sudo apt-get update
sudo apt-get install -y python3-venv git
curl -fsSL https://raw.githubusercontent.com/cs-xdu-dev-001/AgentLens/main/install.sh | sh
hash -r
agentlens --version
```

配置自己的OpenAI兼容模型：

```bash
agentlens configure
agentlens doctor --cli
agentlens chat --workspace /path/to/project
```

`agentlens`是正式命令，旧版`knowflow`仅作为兼容别名。更新后应重新启动TUI：

```bash
agentlens update
agentlens --version
```

### 可选Shell沙箱

只有需要Agent执行命令时才安装：

```bash
sudo apt-get install -y bubblewrap util-linux ripgrep socat
npm install -g @anthropic-ai/sandbox-runtime
srt echo sandbox-ok
agentlens doctor --cli
```

不要在生产机全局关闭AppArmor或user namespace限制。沙箱不可用时，先用`agentlens doctor --cli`定位缺失依赖，再配置最小化系统策略。

## Windows本地运行Web

```powershell
git clone https://github.com/cs-xdu-dev-001/AgentLens.git
Set-Location "AgentLens"

py -3 -m pip install -r backend\requirements.txt
py -3 -m pip install --no-deps -e backend
Copy-Item backend\.env.example backend\.env

Set-Location frontend
npm install
Set-Location ..
.\start-dev.cmd
```

默认地址：

- Web：<http://127.0.0.1:5173/>
- 后端健康检查：<http://127.0.0.1:8010/api/health>
- OpenAPI：<http://127.0.0.1:8010/docs>

`backend/.env`只用于本机，不得提交。生产密钥也不要写进README、命令行或Issue。

## 本地运行文档站

PowerShell：

```powershell
py -3 -m venv .venv-docs
.\.venv-docs\Scripts\python -m pip install -r requirements-docs.txt
.\.venv-docs\Scripts\python -m mkdocs serve --dev-addr 127.0.0.1:8008
```

Linux：

```bash
python3 -m venv .venv-docs
.venv-docs/bin/python -m pip install -r requirements-docs.txt
.venv-docs/bin/python -m mkdocs serve --dev-addr 127.0.0.1:8008
```

打开<http://127.0.0.1:8008/>。提交前执行严格构建：

```bash
.venv-docs/bin/python -m mkdocs build --strict
```

Windows把命令中的`.venv-docs/bin/python`替换为`.venv-docs\Scripts\python`。

## 项目测试

在仓库根目录运行Python检查：

```powershell
Get-ChildItem tests -Filter "check_*.py" |
  Sort-Object Name |
  ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
```

构建Web与测试TUI：

```powershell
Set-Location frontend
npm ci
npm run build

Set-Location ..\cli-tui
npm ci
npm test
npm run build
```

## 常见错误

### 无法创建Python虚拟环境

Ubuntu/Debian提示`ensurepip is not available`时安装对应venv包：

```bash
sudo apt-get install -y python3-venv
```

### TUI回退或无法启动Ink界面

运行`node --version`。新版Ink TUI要求Node.js 22+；版本不足时会回退Textual。更新Node.js后重新运行`agentlens chat`。

### 工作区是HOME目录

AgentLens会阻止在HOME根目录直接执行任务，避免把用户配置当成项目文件。使用：

```bash
agentlens chat --workspace /path/to/project
```

### HTTP 400：temperature只允许1

部分模型由上游固定采样参数。AgentLens不会把用户温度设置强塞给这类模型；如果旧配置仍报错，请更新CLI并重新保存模型配置。

### HTTP 403或503：无可用渠道

这通常是中转站的模型权限、分组、映射或协议路由问题。确认：

1. 当前Key可在`GET /v1/models`看到精确模型名。
2. Chat Completions模型支持`POST /v1/chat/completions`。
3. Responses模型支持`POST /v1/responses`，不能只改下拉选项代替上游能力。
4. 中转站渠道已启用、额度正常，当前Key所属分组有权限。

AgentLens不会在协议失败后自动降级，以免重复执行工具。

### HTTP 429：请求频率受限

等待界面倒计时结束后继续，或降低并发和工具轮数。不要连续手动重试，否则会进一步占用RPM。

### checkpoint暂不可用

本地CLI确认数据目录和checkpoint文件属于当前用户且可读写；服务部署确认运行用户可写`data/langgraph`。不要删除checkpoint来掩盖权限问题。

### Shell沙箱启动失败

先执行：

```bash
command -v bwrap rg socat srt
srt echo sandbox-ok
agentlens doctor --cli
```

缺少依赖就安装依赖；若被系统安全策略拒绝，使用最小化AppArmor规则，不要全局解除限制。
