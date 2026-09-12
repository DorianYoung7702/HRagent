# 部署与更新

HRagent 以源码和 Docker Compose 两种方式运行，不需要产品激活码、设备绑定或授权服务器。模型 API Key 仍需使用者自行配置。项目采用 MIT 许可证。

## 选择运行方式

| 方式 | 适用场景 | 必需依赖 |
| --- | --- | --- |
| 源码运行 | 本机使用、开发、需要可见浏览器完成猎聘登录 | Python 3.12、Node.js 22、Git；在线操作另需 Playwright Chromium |
| Docker Compose | 单机容器部署、PDF 筛选、已有 Linux 浏览器登录态的任务 | Docker Engine、Compose v2 |

默认业务库为 SQLite，不需要 PostgreSQL、Redis 或 Temporal。使用各自配置的路径和数据库后，不同运行方式的数据不会自动互通。

## 源码启动

```sh
git clone https://github.com/DorianYoung7702/HRagent.git
cd HRagent
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

```sh
# Linux / macOS
. .venv/bin/activate
test -f .env || cp .env.example .env
```

安装依赖并构建控制台：

```sh
python -m pip install -c infra/constraints.docker.txt -e ".[dev]"
npm --prefix apps/console-web ci
npm --prefix apps/console-web run build
```

仅 PDF 筛选不需要浏览器。在线操作安装浏览器：

```sh
python -m playwright install chromium
# Linux 需要系统依赖时，使用 python -m playwright install --with-deps chromium
```

在 `.env` 填入 `DEEPSEEK_API_KEY` 与 `HR_COMPANY_NAME`，也可启动后在控制台顶部保存。在线登录需要可见浏览器时，将 `BROWSER_HEADLESS=false` 写入 `.env`。

```sh
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --workers 1
```

访问 [本机控制台](http://127.0.0.1:8001)；`/health` 为健康检查，`/docs` 为 API 文档。首次启动自动创建 SQLite 表和数据库父目录。

必须使用单 worker：队列、浏览器控制和 SSE 订阅含进程内状态，不应仅通过增加 worker 数扩容。源码更新前先停止运行中的任务，再用 `Ctrl+C` 关闭服务。

Windows 也可在安装依赖后执行 `scripts/start_console_prod.ps1`，构建前端并以前台进程启动 API。该脚本默认仅监听本机，不创建桌面快捷方式。

## Docker 启动

```sh
docker compose -f infra/docker-compose.standalone.yml up -d --build
docker compose -f infra/docker-compose.standalone.yml logs -f --tail=100
```

容器默认只映射 `127.0.0.1:8001`。完整说明见 [Docker 部署](DOCKER_STANDALONE.md)。默认使用官方 Python/npm 软件源，可通过构建参数显式指定你信任的镜像源。

## 数据与配置

| 内容 | 源码默认路径 | 容器路径 |
| --- | --- | --- |
| 业务数据库 | `data/recruiting.db` | `/data/recruiting.db` |
| 用户模型与岗位配置 | `data/config/runtime.json` | `/data/config/runtime.json` |
| 浏览器登录态 | `data/browser_profiles/` | `/data/browser_profiles/` |
| 工作流日志 | `data/logs/workflow_events/` | `/data/logs/workflow_events/` |

`DATABASE_URL`、`BROWSER_PROFILE_DIR` 可写入 `.env`。`HRAGENT_CONFIG_PATH`、`HRAGENT_DATA_DIR`、`HRAGENT_EVENT_LOG_DIR` 是进程环境变量；自定义路径时请在启动命令所在的 shell 或容器环境中设置。

`HRAGENT_DATA_DIR` 用于运行配置和日志等数据目录的默认值，不会自动重写 `DATABASE_URL` 或 `BROWSER_PROFILE_DIR`；需要迁移数据库和登录态时请分别指定。

控制台保存的模型配置会在启动时覆盖同名环境配置。要继续使用 `.env` 的值，应移除运行配置 JSON 中对应字段；不要公开该文件，其中可能含有模型密钥。

### 从旧桌面版迁移

本次代码清理不删除旧数据库、配置、浏览器 profile 或安装目录。旧桌面快捷方式不会自动转为源码启动方式；按本指南启动新服务。

先停止旧进程并备份数据。可显式复用旧路径，无需移动文件：

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///$env:LOCALAPPDATA/HRagent/data/recruiting.db"
$env:HRAGENT_CONFIG_PATH = "$env:APPDATA\HRagent\config.json"
$env:BROWSER_PROFILE_DIR = "$env:LOCALAPPDATA\HRagent\browser_profiles\hr_default"
$env:HRAGENT_EVENT_LOG_DIR = "$env:LOCALAPPDATA\HRagent\logs\workflow_events"
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --workers 1
```

运行前确认上述文件存在且属于目标用户，不要同时让新旧服务写入同一个数据库或浏览器 profile。旧激活缓存不再读取，旧授权开关不会恢复产品授权校验。Windows 登录态不保证能迁移到 Linux 容器。

## 更新与备份

源码更新：停止任务和服务，备份实际数据目录及配置后执行：

```sh
git pull --ff-only
python -m pip install -c infra/constraints.docker.txt -e ".[dev]"
npm --prefix apps/console-web ci
npm --prefix apps/console-web run build
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --workers 1
```

依赖中的 Playwright 版本变更后，重新执行 `python -m playwright install chromium`。

Docker 更新：先停止任务并备份命名卷，再拉取代码并运行 `docker compose -f infra/docker-compose.standalone.yml up -d --build`。保持同一 Compose 项目名和卷配置，不使用 `down -v`。

已有 `/system/db/backup` 与 `/system/diagnostics/export` 维护接口仍保留。数据库备份不包含模型配置、浏览器登录态及外部日志，这些文件须单独备份。数据删除边界见 [隐私说明](DATA_PRIVACY.md)。

## 网络安全

移除产品授权不是增加了用户认证。默认仍为本机单用户应用，不能直接向公网暴露。远程访问需另行部署 HTTPS、身份验证网关和访问控制，上传体积与超时设置也需由运维确认。
