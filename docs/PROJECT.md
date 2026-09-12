# HRagent 项目说明

HRagent 是面向本机单用户和受控内部环境的招聘 Agent 工作台，当前定位为 Beta。

## 核心流程

1. HR 编辑岗位资料和筛选偏好，启动时锁定本次判定标准。
2. 从文本 PDF 或猎聘 LPT 获取候选资料。
3. 解析 Agent 提取信息，筛选 Agent 生成分数、理由与观察/追问/排除结果。
4. PDF 直接按已有初筛分数排序；在线任务支持 IM 跟进、回复终判与总结排名。
5. 通过实时日志、历史记录和结构化结果复核执行情况。

BOSS 仅保留扩展入口，真实 RPA 尚未接入。模型输出不代替 HR 的最终录用决策。

## 技术结构

| 目录 | 职责 |
| --- | --- |
| `apps/api` | FastAPI 路由、生命周期、后台任务入口 |
| `apps/console-web` | Vue / TypeScript 控制台 |
| `services/agent_service` | 需求解析、偏好、简历解析、筛选、对话与排名 |
| `services/fetch_worker` | Playwright 页面操作与平台适配 |
| `packages/db` | SQLAlchemy 模型、数据访问与 schema 升级 |
| `packages/runtime_config.py` | 模型密钥、招聘方身份与岗位配置持久化 |
| `packages/runtime_guards.py` | 模型配置与候选人沟通身份检查 |
| `packages/outreach_policy.py` | IM 人工确认策略 |
| `infra` | Docker 镜像、Compose 与依赖约束 |
| `tests` | 合成数据与 mock 回归测试 |

默认单节点模式使用 asyncio 后台任务、SQLite 与 SSE；PostgreSQL、Redis、Temporal 不属于默认部署依赖。仓库中的可选编排代码不等同于已经验证的分布式服务。

## 部署入口

仅维护源码运行和 Docker Compose，不再提供授权码、设备绑定、二进制安装器或桌面打包脚本。MIT 许可证保留，模型 API Key 和平台账号由使用者自行配置。

- [README](../README.md)：项目首页、快速开始与能力边界。
- [部署与更新](DEPLOYMENT.md)：源码、容器、单 worker、数据迁移和版本更新。
- [Docker 部署](DOCKER_STANDALONE.md)：容器环境、卷备份与浏览器限制。
- [HR 操作手册](HR_USER_OPERATING_MANUAL.md)：需求、筛选、追问与结果复核。
- [数据与隐私](DATA_PRIVACY.md)：简历、日志、配置和人才档案的保存范围。
- [Playwright](PLAYWRIGHT.md)：平台自动化实现与调试。

`TECHNICAL.md` 保留早期模块设计资料；涉及历史架构时，以当前代码和部署指南为准。

## 验证边界

自动化测试不得使用真实候选人数据、调用付费模型或发送真实 IM。测试通过仅证明测试覆盖范围内的行为；平台实操和实际部署验收需单独记录。

对外反馈不得提供模型密钥、Cookie、数据库、完整简历或内部岗位资料。公共网络部署必须配置独立的身份验证网关及 HTTPS。
