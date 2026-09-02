# Smart Nudge

面向 AIA 集团 CEO 的公开 Web 情报研究 Agent POC。

当前交付：P0 监控定义、输出契约和离线校验。P1 所需项目、模型部署及 Bing 连接／配置标识已齐，但本机认证、模型调用和真实搜索尚未验证，Agent 编排及领域 Skills 执行尚未实现。定时、对话、推送和前端不在当前 scope。

**换设备继续工作：先读 [当前进度与交接说明](docs/HANDOFF.md)。** 非敏感连接参数见 [.env.example](.env.example)；这不是已接通的运行配置，Azure 登录须在新设备单独完成。

## 项目文档

- [当前进度、连接信息与下一步](docs/HANDOFF.md)
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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

校验另外一份结果：

```powershell
.\.venv\Scripts\python.exe scripts/validate_p0.py --result examples/intelligence-result.synthetic.json
```

安装依赖需要网络；验证和测试本身离线运行，不读取 Azure 密钥、不执行搜索、不修改云资源。

通过这些检查只表示契约一致，**不是**搜索质量、事实准确率或专家认可。示例均为显式标识的合成数据，不能作为真实情报使用。

## Git 迁移注意事项

不要上传 `.env`、`.venv`、Azure 登录缓存、数据库或 `.tmp`。`.env.example` 只包含用户提供的非敏感资源标识，不含密钥；如仓库将公开，先确认是否保留这些具体标识。此次交接未执行 Git add、commit 或 push，提交检查与新设备恢复步骤见 [交接说明](docs/HANDOFF.md#5-git-提交与迁移检查)。
