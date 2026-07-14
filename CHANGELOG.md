# Changelog

## Unreleased

## 1.0.0 - 2026-07-14

+ [新增] 二次开发版本基线，仓库地址切换为 `owen891/chatgpt2api`。
+ [新增] 生图上游管理：Base URL、API Key、模型映射、默认渠道、超时、代理、连通性测试。
+ [新增] `/v1/images/generations` 与 `/v1/images/edits` 支持账号池优先、上游故障回退。
+ [新增] 多上游按优先级故障切换，支持上游返回图片 URL 后下载保存到本地图库。
+ [新增] 独立注册机页面与菜单入口，支持常驻监控、额度不足自动补池、实时日志与运行指标。
+ [新增] 生图任务支持单张停止、停止剩余生成与停止后重新生成。
+ [调整] 前端 GitHub 链接、版本展示与版本检查改为指向二改仓库。
+ [安全] 增加 `config.example.json`，本地 `config.json`、`data/`、`logs/`、`.env` 等运行期敏感数据不再作为提交内容。

## Source Baseline

- 源项目：[basketikun/chatgpt2api](https://github.com/basketikun/chatgpt2api)
- 源项目基线版本：`v1.7.0`
