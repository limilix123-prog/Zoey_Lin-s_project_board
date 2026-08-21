# rbac

Role-Based Access Control 基础层。

5 角色矩阵 + admin 提升接口 + 首个 admin 自动 seed。

**特性**:
- `feature_role.py` — role 常量 + 角色检查 helper (v0.9.7p1 cleanup: 删 `is_user` / `role_rank` / `role_check` 3 个死函数)
- `feature_require_auth.py` — `@require_role('admin')` 装饰器
- `feature_create_admin.py` — 启动时检查,无 admin 则用 config 自动建

**v0.9.7p1 cleanup**: `feature_storage.py` (144 行, 4 函数 + 10 常量) 整文件物理删 — 内容已 inlined 到 `feature_storage_rbac` (callers) + `feature_role` (constants), 全文 0 hit。

**RBAC 业务级 lock**(7/22 原则):
- 所有写操作走 server 端 account 模块
- SQL 直改 = 绕过鉴权 = 致命漏洞(物理 chmod 没用)
- 单机 + 单一 server 部署,所有写走 server 端 account 模块

**不做**:细粒度权限矩阵(后续 milestone)+ 审计日志(后续)+ 多 server 同步(后续)。
