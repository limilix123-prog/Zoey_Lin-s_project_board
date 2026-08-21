# projects / feature_storage_features

`ProjectStorage` Feature Board methods split-out。`project_features` 表 4 个方法 (`create_feature` / `list_features` / `move_feature` / `delete_feature`) 在这里,让 `feature_storage.py` 守 1000 行 cleancode 阈值。

## 4 个 methods(挂到 `ProjectStorage`)

`install_feature_methods()` import 时自动挂载(也由 `feature_storage.py` 底部 defensive 调一次, idempotent):

| Method | 作用 | 守门 |
|---|---|---|
| `create_feature(project_id, name, description, status="backlog", position=0)` | INSERT | name 非空 + status whitelist |
| `list_features(project_id)` | SELECT 4 column kanban | — |
| `move_feature(feature_id, new_status, new_position)` | UPDATE status + position | status whitelist + cross-project guard |
| `delete_feature(feature_id)` | DELETE | — |

`project_features` 表 DDL 留 `feature_storage._SCHEMA_SQL`,`ProjectStorage.init_schema` 是单一建表入口。

## 上游 / 下游

- 上游:`feature_storage` 底部 import + 调
- 下游:无
