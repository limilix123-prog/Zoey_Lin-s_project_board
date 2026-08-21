# app / feature_config

读 `config.yaml` + 校验必需字段,stdlib-only(手写最小 YAML parser,不用 PyYAML)。

- 必需字段:`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `SECRET_KEY` / `DB_PATH` / `SESSION_LIFETIME_HOURS` / `SESSION_COOKIE_SECURE` / `SESSION_COOKIE_HTTPONLY`
- 环境变量可覆盖 `SECRET_KEY`(`PROJECT_BOARD_SECRET_KEY`)和 `DB_PATH`(`PROJECT_BOARD_DB_PATH`),部署时把机密放到 env 而不是 yaml
- 手写 parser 只支持本项目 config.yaml 用的语法:顶层 `key: value`、`#` 注释、字符串/整数/布尔字面量
- 类型收尾:`SESSION_LIFETIME_HOURS` 必 int,两个 cookie 标志必 bool,三个字符串字段必非空
- 缺字段或类型错 → `ConfigError`(继承 `ValueError`),启动期就崩

上游:`app/feature_app_factory.create_app` 调。
下游:`accounts/feature_storage` 收 `DB_PATH`,`rbac/feature_create_admin` 收 admin 凭据。
