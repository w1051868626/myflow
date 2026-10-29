# MyFlow

让灵感，流动起来。一个面向文本与图像生成的可视化 AI 工作流平台。

用节点连接「主题输入 → 文案生成 → 配图与文本整理 → 汇总输出」，在画布上查看执行状态和流式输出。

![MyFlow 图文工作流与运行结果](docs/preview.jpg)

## 快速开始

安装 Docker Engine 与 Docker Compose 插件（Windows/macOS 可使用 Docker Desktop），在项目根目录运行：

```sh
docker compose up --build -d
```

打开 [http://localhost:3000](http://localhost:3000)，直接运行预置的「从灵感到图文」工作流。默认使用演示模型，无需 API Key。演示文本是固定规则生成，演示配图是本地 SVG，界面会显示演示标记。

```sh
docker compose logs -f
docker compose down
```

数据库、生成文件和加密密钥保存在根目录 `data/`，停止容器后仍然保留。

## 连接真实模型

1. 点击左下角设置按钮，填写 OpenAI 兼容服务的 Base URL（例如 `https://api.openai.com/v1`）和 API Key。
2. 在节点配置中切换到真实模型。
3. 其他供应商或模型可在 `backend/models.yaml` 添加，`id` 必须与供应商接受的模型名一致。Compose 已挂载这个文件，修改后刷新页面即可。

```yaml
models:
  - id: your-model-id
    name: 我的文本模型
    kind: text          # text 或 image
    provider: openai    # OpenAI 兼容接口
```

当前支持一个 OpenAI 兼容连接，模型列表中的真实模型共享这组地址与密钥。文本使用 `/chat/completions` 流式接口及 `stream_options.include_usage`，图像使用 `/images/generations`，要求接受 `model/prompt/size/n`。供应商的专有图像协议需要额外适配。默认真实模型名称仅用于配置示例，可用性与费用以供应商为准。

API Key 使用 Fernet 加密，不会通过读取接口返回。首次启动自动生成 `data/encryption.key`；请连同数据库备份，丢失密钥后需重新配置 API Key。设置页中密钥留空会保留已存密钥。也可通过环境变量 `MYFLOW_ENCRYPTION_KEY` 指定有效的 Fernet 密钥；Compose 使用时需自行在 backend 服务中传入该变量。

## 使用画布

- 点击底部节点按钮添加，或将它拖到画布中。从节点右侧圆点拖向下游节点左侧圆点完成连线。
- 点击节点，在右侧配置模型和提示词。点击空白区域可修改工作流名称。
- 提示词支持 `{{node_id.output}}`；开始节点的输入可通过 `{{start.topic}}` 引用。输入 `{` 或点击「插入上游变量」查看已连接的上游变量。
- 开始节点的字段用逗号分隔，例如 `topic,style`。运行前会显示输入表单。
- 选中节点或连线，按 Delete / Backspace 删除；节点也可在配置面板中删除。
- 运行时会先保存当前工作流。图中必须有一个开始和一个输出节点，所有节点都必须位于开始到输出的路径上，且没有循环。
- 文本节点可连接文本、图像、模板与输出节点；图像输出只能接到输出节点。MVP 暂不支持图像输入 LLM。
- 输出节点自动收集直接上游结果。点击节点可查看输入、输出、耗时和供应商返回的 token 用量。
- 运行结果页可以停止当前运行。历史页显示最近 50 次运行，点击记录会重放事件并展示当时的画布快照；点击「返回编辑」继续编辑。
- SSE 断线会自动重连，使用事件 ID 从断点继续。刷新页面后，可从历史页重新打开正在运行的记录。

## 本地开发

项目使用 Node.js 24.19.0（根目录 `.nvmrc`）、Python 3.12 和 pnpm 10.18.3（`frontend/package.json`）。Docker 同样使用 Node.js 24 系列。

### 首次准备：nvm + Conda

以下命令在项目根目录执行一次即可。`environment.yml` 会创建独立 Python 环境并安装后端运行、测试依赖，Conda base 环境只用于管理环境。

Windows 下将环境放到 D 盘（路径可自行更换）：

```powershell
conda env create --prefix D:/Programs/miniforge/envs/myflow --file environment.yml
```

安装前端工具及锁定依赖：

```powershell
nvm install 24.19.0
nvm use 24 --local
cd frontend
npm install --global pnpm@10.18.3
pnpm install --frozen-lockfile
```

`nvm use 24 --local` 从本地已安装的 24.x 版本中选择最新版本，不读取在线版本列表。本项目已验证版本为 24.19.0。普通 `nvm use <版本>` 可能先联网解析版本，下载源不可达时会超时。

前端 `.npmrc` 将 pnpm 包存储放到项目根目录 `.pnpm-store/`，该目录已被 Git 忽略。新安装 nvm 或修改 PATH 后，重开终端；若编辑器内仍找不到命令，请重启编辑器。

### 日常启动

终端一，从项目根目录激活环境并启动后端：

```powershell
conda activate D:/Programs/miniforge/envs/myflow
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

终端二，从项目根目录启动前端：

```powershell
cd frontend
pnpm dev
```

每个新后端终端都需要激活 Conda；环境和依赖无需重新安装。Node 保持 24 为默认版本时无需再次切换；从其他版本切回时执行 `nvm use 24 --local`。本机 nvm 使用 link 模式，不会根据 `.nvmrc` 自动切换；shim 模式则支持自动识别。

若 PowerShell 尚未初始化 Conda，可在 `backend/` 中直接启动，无需修改 PowerShell 配置：

```powershell
conda run --no-capture-output --prefix D:/Programs/miniforge/envs/myflow python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端将 `/api` 和 `/artifacts` 代理到 `http://127.0.0.1:8000`，无需配置 CORS。若改变后端地址，在启动前端前设置 `BACKEND_URL`；生产构建需在 `pnpm build` 前设置。

后端 API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。本地开发默认数据目录是 `backend/data/`，可通过 `MYFLOW_DATA_DIR` 指定。

### 一次性修复 nvm 目录

若 `nvm list` 显示没有版本，但 `D:/Programs/nvm/installs/v24.19.0/node.exe` 确实存在，请在**报错的同一个终端**、项目根目录运行：

```powershell
.\scripts\repair-local-nvm.ps1
```

脚本先验证现有 Node 文件，再修正当前终端读取的 nvm 配置（版本目录、link 模式），并更新当前终端和用户 PATH；不会下载 Node 或修改 Conda 环境。默认版本目录为 `D:/Programs/nvm/installs`，命令通过 nvm 管理的 `D:/Programs/nvm/.link/nodejs` 链接访问所选版本。

**修复成功后无需每次执行。** 重开其他终端或编辑器即可刷新 PATH。可通过脚本参数 `-VersionRoot`、`-Version` 指定其他安装目录和版本；脚本针对 nvm-windows 2.x。

### 更新依赖与验证

后端依赖变化时，在项目根目录更新已有环境；前端依赖变化时，在 `frontend/` 中重新运行 `pnpm install --frozen-lockfile`：

```powershell
conda env update --prefix D:/Programs/miniforge/envs/myflow --file environment.yml
```

```sh
# backend/（激活虚拟环境后）
python -m pytest -q

# frontend/
pnpm test
pnpm typecheck
pnpm build
```

### 不使用 Conda：venv 备选

在 `backend/` 中运行 `python -m venv .venv`，激活后执行 `python -m pip install -r requirements-dev.txt`，再按上述方式启动后端。Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`，macOS/Linux 为 `source .venv/bin/activate`。前端工具和启动步骤相同。

## 当前边界

这是单机、单用户 MVP，默认仅通过本机 `127.0.0.1:3000` 访问，未提供登录鉴权。后端依靠进程内 asyncio 调度，必须使用一个 Uvicorn worker。每次运行中的独立节点最多并发执行 4 个；失败会取消同次运行的其他任务，并记录未执行节点。服务重启后，未完成运行会标记为中断，可以重新发起。

运行历史保存工作流版本、图快照及事件；编辑冲突返回 409。当前不支持版本回滚、失败续跑和条件分支。图像接口返回 base64 时会保存到本地；返回 URL 时保留供应商链接，可能过期，请及时保存。

完整方案与后续范围见 [DESIGN.md](DESIGN.md)。
