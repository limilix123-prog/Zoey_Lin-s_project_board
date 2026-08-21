# profile / feature_change_password

改密码端点:POST `/profile/password`。端点 URL 保留, 渲染层用共享 `projects/templates/projects/me.html` (v0.9.7p1 从 `app/templates/` 迁入)。

**保护**:`@require_auth`。未登录 → 302 → /login。

**流程**:
1. 拿 `old_password` / `new_password` / `confirm_password`
2. 从 storage 重新读 current user(避免 g 缓存陈旧)
3. `verify_password(old, user.password_hash)` 失败 → 渲染 projects/me.html(失败态)
   + "wrong old password"(400)
4. new empty → "new password must not be empty"
5. new != confirm → "new passwords do not match"
6. `hash_password(new)` → `UserStorage.update_password(user_id, new_hash)`
7. success → 302 → `/me?changed=1`(me 页读 `?changed=1` 显示一行 notice)

**错误消息合并**:user 不存在 vs 旧密码错都映射为同一句 "wrong old password",
不向调用方暴露 user 是否存在。校验错误(empty / mismatch)用各自独立的提示,
跟"身份失败"分开。

**失败路径上下文**:失败时用 `projects/feature_me.build_project_items` /
`owner_username_lookup` 重建完整 me.html context(owned / member 项目列表),
保证失败渲染的页面形状跟 GET /me 出来的形状完全一致(只是 error 替换 notice)。

**密码 verify**:走 `accounts/feature_password.verify_password`,内部已用
`hmac.compare_digest` 做常数时间比较。

**v0.9.7p1 cleanup 删**:
- `_DESCRIPTION_PREVIEW_CHARS = 100` 常量 (0 caller, 真实 preview 在 `projects/feature_me.py`)
- `_preview(text, limit)` 函数 (0 caller, 同上)
