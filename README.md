# ChatGPT2API 二次开发版

当前二改版本：`1.0.0`

本仓库是基于源项目的二次开发版本，主要围绕生图能力、注册机、账号池与上游故障回退做了增强，同时保留原有账号池、生图、CPA、Sub2API、文本对话等入口。

- 二改仓库：[owen891/chatgpt2api](https://github.com/owen891/chatgpt2api)
- 源项目：[basketikun/chatgpt2api](https://github.com/basketikun/chatgpt2api)

## 二改内容

- 新增“生图上游”管理：Base URL、API Key、模型映射、默认渠道、超时、代理与连通性测试。
- `/v1/images/generations`、`/v1/images/edits` 支持账号池优先，外部生图上游作为故障回退。
- 多个生图上游按优先级故障切换，降低单渠道不可用影响。
- 上游返回图片 URL 时支持下载并保存到本地图库，避免外链过期。
- 新增独立“注册机”页面与菜单入口，补充常驻后台监控、额度不足自动补池、实时日志等能力。
- 注册成功账号可进入生图账号池，并参与生图调度。
- 生图任务支持单张停止与停止剩余生成，已完成图片保留，停止后可重新生成。
- 前端 GitHub 链接、版本展示与版本检查已改为指向二改仓库。

## 敏感信息处理

以下文件或目录属于运行期数据，不应提交到 GitHub：

- `config.json`
- `.env`
- `.env.local`
- `data/`
- `logs/`
- 本地生成的图片、备份、账号池快照等数据

首次部署请复制示例配置：

```bash
cp config.example.json config.json
```

然后在 `config.json` 中填写自己的：

- 管理密码 / `auth-key`
- 代理地址
- 生图上游 Base URL 与 API Key
- 邮箱服务 Key
- 备份存储密钥
- WebDAV 或其他私有存储配置

不要在 README、Issue、截图、提交记录中粘贴完整 API Key、Access Token、Refresh Token、邮箱密码、代理鉴权串或备份密钥。

## 快速开始

### Docker 部署

```bash
git clone https://github.com/owen891/chatgpt2api.git
cd chatgpt2api
cp config.example.json config.json
docker compose up -d
```

默认访问：

- Web 面板：`http://localhost:3000`
- 后端 API：`http://localhost:8000`
- OpenAI 兼容接口：`http://localhost:8000/v1`

### 本地开发

后端：

```bash
uv sync
uv run main.py
```

前端：

```bash
cd web
npm install
npm run dev
```

本地默认：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8000`

## 主要功能

### 生图 API

- `POST /v1/images/generations`
- `POST /v1/images/edits`
- 支持账号池优先、上游回退、模型映射、失败重试与本地图库保存。

### 生图工作台

- 支持文本生图、图片编辑、多图参考。
- 支持多张并行生成。
- 支持生成中停止、停止剩余任务、重新生成单张。
- 支持历史会话、本地图片缓存和图库管理。

### 账号池

- 支持账号导入、刷新、重登、额度识别、状态筛选和批量维护。
- 注册成功账号可自动进入生图调度。
- 支持账号池优先、上游故障回退的混合调度策略。

### 注册机

- 独立页面与菜单入口。
- 支持常驻后台监控。
- 支持按目标额度或可用账号数自动补池。
- 支持实时日志、运行指标、代理配置、邮箱来源管理与 Cloudflare 清障配置。

### 上游管理

- 支持多个生图上游渠道。
- 支持优先级、默认渠道、模型映射、超时、代理、并发、限速、冷却与连通性测试。
- 支持上游状态展示和故障切换。

## 版本

- 当前二改版本：`1.0.0`
- 源项目基线：`basketikun/chatgpt2api` `v1.7.0`

## 免责声明

本项目仅用于个人学习、技术研究与自托管测试。使用者需要自行承担账号、网络、服务条款、数据安全与合规风险。
