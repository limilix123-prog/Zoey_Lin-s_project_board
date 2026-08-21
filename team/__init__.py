"""Team module — POST /team/_internal/report (copy-editor shared-secret write).

GET /team was retired in v0.9.7 (302 → /projects). The write endpoint
stays because the copy-editor agent pushes agent status into
``agent_team_status`` via shared-secret auth.
"""
