# feature_project_owner

`POST /projects/<int:project_id>/owner` — change a project's owner.

Single endpoint, single form field (`new_owner_id`). The change is
idempotent: re-submitting the current owner is a no-op (302 redirect
with `notice=Owner unchanged`).

## change owner gate (v0.7.2b, T-scale)

| actor rank | target rank | result |
|---|---|---|
| **T0 (admin) / T1 (manager)** | **T2 (project_leader)** | **302 — accepted (normal)** |
| T0 / T1 | T2 (current owner) | 302 — accepted (idempotent no-op) |
| T0 / T1 | T0 / T1 (self) | 302 — accepted (idempotent, only reachable when T0/T1 is the current owner, e.g. the system project) |
| T0 / T1 | T0 / T1 (not current owner) | 400 — `T0/T1 已 auto-own, 不能是 owner target` |
| T0 / T1 | T3 (team_leader) | 400 — `T3 (team_leader) cannot be project owner` |
| T0 / T1 | T4 (user) | 400 — `T4 (user) cannot be project owner` |
| T0 / T1 | system project | 403 — `system project owner is permanent` |
| T2 (project_leader) | any | 403 — `only T0/T1 (admin/manager) can change project owner` (actor gate) |
| T3 / T4 | any | 403 — actor gate |
| anonymous | any | 302 to `/login` (no actor) |

The actor gate is `require_auth` + an explicit
`_is_auto_own(actor)` check; the target rank gate is the v0.7.1
T-scale (rank must be 2). System projects are permanent (cannot have
their owner reassigned, same rule as the delete endpoint).

## what it does

* **accepts** T0/T1 actor + T2 target. The form-level dropdown in
  `feature_view._build_owner_context` already filters candidates to
  `role == project_leader`, so the normal user flow only offers
  T2 targets; the rank check here is the server-side chokepoint for
  hand-crafted POSTs that bypass the UI.
* **rejects** T0/T1 actor with a non-T2 target (400) and T2/T3/T4
  actor regardless of target (403). The actor gate fires before the
  target gate so a T2 actor never sees the rank-check error
  message.
* **rejects** system projects (403). The system project owner stays
  the bootstrap admin forever; this is the same rule that already
  blocks the delete endpoint.
* **idempotent** when the new owner equals the current owner — both
  the "T0/T1 actor + T0/T1 current owner" and the "T0/T1 actor +
  T2 current owner" cases are accepted with a 302 redirect. The
  redirect lands on the project view with a `notice=Owner unchanged`
  query string so the UX matches a successful reassignment.

## why

* **T0/T1 only on the actor side** — matches the v0.5.4
  `admin/manager` accept set, expressed in the v0.7.1 T-scale native
  helper (`_is_auto_own`). Mirrors the v0.7.2a `feature_create`
  endpoint's `@require_role(MANAGER)` gate (T0/T1 only) and the
  `feature_project_members` owner-based gate.
* **T2 only on the target side** — the project's day-to-day lead
  must be a T2 (project_leader). T0/T1 (auto-own) are
  platform-level, not project-level; T3 / T4 (team_leader / user)
  are not leadership. The "T2 must own the project" rule mirrors
  the v0.5.4 "target must be project_leader" rule.
* **idempotent** — keeps the v0.5.4 "no-op 302" behaviour so a
  T0/T1 actor that picks the current owner from the dropdown (or
  hand-crafts a POST setting `new_owner_id = project.owner_id`)
  gets a clean 302 instead of a confusing 4xx error.
