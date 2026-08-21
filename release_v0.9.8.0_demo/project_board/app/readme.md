# app

Flask app factory + 路由注册 + config 加载 + Jinja templates。

把各个 feature 模块的 routes 串起来,对外暴露 WSGI app。

**特性**:
- `feature_app_factory.py` — `create_app()` 入口
- `feature_routes.py` — 注册各模块的路由
- `feature_config.py` — 读 `config.yaml` + 环境变量
- `feature_templates.py` — Jinja template 加载 + base layout

**不做**:业务逻辑(在 accounts/auth/rbac 模块里)。
