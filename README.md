# Smart Nudge

面向 AIA 集团 CEO 的公开 Web 情报研究 Agent POC。

当前交付：P0 监控定义和输出契约；P1 Foundry／Bing 接入与保守留存策略；P2 三市场 Source Registry、安全原文读取和定位解析；P3 首个 `regulatory-change` Skill；P4-A 有界的合成监管研究—分析—核验闭环。Skill 仍待领域批准，真实研究角色和生产闭环尚未实现。定时、对话、推送和前端不在当前 scope。

**换设备继续工作：先读 [当前进度与交接说明](docs/HANDOFF.md)。** 非敏感连接参数见 [.env.example](.env.example)；实际加载根目录 `.env`，新设备须重新安装依赖并单独完成 Azure 登录。

## 项目文档

- [当前进度、连接信息与下一步](docs/HANDOFF.md)
- [P1 实测结果、命令与限制](docs/P1_VALIDATION.md)
- [P1 官方原文访问方案与数据留存边界](docs/P1_ACCESS_RETENTION.md)
- [P2 来源登记册、访问矩阵与获取边界](docs/P2_SOURCE_REGISTRY.md)
- [P3 首个监管 Skill、Loader 与评审流程](docs/P3_SKILLS.md)
- [P4-A 离线监管研究闭环](docs/P4A_OFFLINE_RESEARCH.md)
- [实施计划](docs/IMPLEMENTATION_PLAN.md)
- [P0 业务与输出规范](docs/P0_SPEC.md)
- [AIA CEO Watch Profile](config/watch_profiles/aia-group-ceo.json)
- [六类研究主题](config/topics/insurance-intelligence.json)
- [初始实体映射](config/entities/aia-pilot.json)
- [结构化输出 Schema](schemas/intelligence-result.schema.json)
- [合成输出示例](examples/intelligence-result.synthetic.json)
- [20 个待专家审核的合成案例](evals/cases/p0-synthetic.json)

## 本地验证（Windows / Python 3.11+）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/validate_p0.py
.\.venv\Scripts\python.exe scripts/validate_sources.py
.\.venv\Scripts\python.exe scripts/validate_skills.py
.\.venv\Scripts\python.exe scripts/validate_research.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

校验另外一份结果：

```powershell
.\.venv\Scripts\python.exe scripts/validate_p0.py --result examples/intelligence-result.synthetic.json
```

安装依赖需要网络；以上验证和测试本身离线运行，不读取 Azure 密钥、不执行搜索、不修改云资源。

通过这些检查只表示契约、来源策略、版本化 Skill 和离线控制流一致，**不是**实时连通性、搜索质量、事实准确率、持续覆盖、法律意见或专家认可。草稿 Skill 默认拒绝生产加载；P4-A 只接受 `.example` 合成证据，不能作为真实情报使用。

## P1 本机验证

首次配置时，将 `.env.example` 复制为 `.env`，已有 `.env` 不要覆盖。完成 `az login` 后，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check auth
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check model
.\.venv\Scripts\python.exe scripts/smoke_foundry.py --check search
```

`auth` 只验证 Python 凭据；`model` 和 `search` 各发起一次真实 Responses 请求，产生模型／搜索用量。搜索模式使用已登记的六个香港来源检查原生引用。默认不重试、不创建托管 Agent、不写响应文件；`search` 只打印安全审计元数据和原生引用，不打印 Bing 生成的回答正文。`ok: true` 仅表示接入检查通过，不表示事实核验或覆盖率通过。参数和限制见 [P1 验证记录](docs/P1_VALIDATION.md)，数据边界见 [P1 访问与留存说明](docs/P1_ACCESS_RETENTION.md)。

## Git 迁移注意事项

不要上传 `.env`、`.venv`、Azure 登录缓存、数据库或 `.tmp`。`.env.example` 只包含用户提供的非敏感资源标识，不含密钥；如仓库将公开，先确认是否保留这些具体标识。P0–P3 已推送到 `develop`；当前 P4-A 工作树是否已提交以 `git status` 和提交日志为准。迁移步骤见 [交接说明](docs/HANDOFF.md)。
