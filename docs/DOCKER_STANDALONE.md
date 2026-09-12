# HRagent 单机镜像服务

该部署定义用于单台服务器或公司统一平台的单服务运行：Vue 控制台、FastAPI、SQLite、日志和 Playwright Chromium 都在一个容器中。它不依赖 Postgres、Redis 或 Temporal。

## 启动

```powershell
if (-not (Test-Path .\infra\hragent.container.env)) {
    Copy-Item .\infra\hragent.container.env.example .\infra\hragent.container.env
}
# 编辑 hragent.container.env，或启动后在控制台配置模型 Key 与招聘方身份
docker compose -f .\infra\docker-compose.standalone.yml up -d --build
```

控制台地址：`http://127.0.0.1:8001`。修改端口：`$env:HRAGENT_PORT=8010` 后再执行 compose 命令。

## 持久化与升级

- 命名卷 `hragent_data` 保存 SQLite、浏览器 profile、任务日志和诊断文件。
- 升级镜像时执行同一条 `up -d --build`，不会删除该卷。
- 备份前先在控制台停止任务，再执行下方命令；通过服务名复制实际数据，避免误用不带 Compose 项目前缀的空卷。
- 停止但保留数据：`docker compose -f .\infra\docker-compose.standalone.yml down`。
- 不要使用 `down -v`，否则会删除候选结果、任务记录和浏览器 profile。

```sh
docker compose -f infra/docker-compose.standalone.yml stop hragent
# 请为每次备份选择新的空目录；此处路径为示例。
mkdir hragent-backup
docker compose -f infra/docker-compose.standalone.yml cp hragent:/data/. ./hragent-backup/
docker compose -f infra/docker-compose.standalone.yml start hragent
```

备份包含候选数据和模型配置，不要上传仓库或公开分享。恢复前停止服务，由维护者确认目标卷与文件权限。升级时保持原有 Compose 项目名，避免意外连接到新卷。

默认使用 npm/PyPI 官方软件源，`NPM_REGISTRY` 与 `PIP_INDEX_URL` 构建参数可指向使用者信任的镜像源。运行模式使用单 worker，不提供用户登录认证，也不连接产品授权服务器。

## RPA 限制

容器默认强制 headless，适合 API、PDF 导入和已有容器内登录态的自动化任务。首次猎聘登录需要在同一 Linux 环境中建立 profile；Windows Chromium profile 不应直接复制到容器。可见登录需要额外的受控 VNC/远程浏览器会话，该镜像未内置此能力。需要直接操作登录窗口时使用源码部署。BOSS 真实 RPA 尚未接入。
