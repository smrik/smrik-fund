# Triage roles

This setup stores triage roles in the task body. Existing GitHub labels and boards
remain intact. These values are body fields, not new label names. When using the
triage skill, use this mapping instead of creating labels or rerunning setup.

| Canonical role | Body field | Task status |
| --- | --- | --- |
| `needs-triage` | `Triage role: needs-triage` | Proposed |
| `needs-info` | `Triage role: needs-info` | Needs feedback |
| `ready-for-agent` | `Triage role: ready-for-agent` | Ready |
| `ready-for-human` | `Triage role: ready-for-human` | Needs feedback; name the human action |
| `wontfix` | `Triage role: wontfix` | Not planned; retain the reason |

Use one `Category: bug` or `Category: enhancement` field when triaging. Keep one
current triage role per task. Read the issue and comments, then update only these
fields and the relevant status; preserve the rest. List and filter tasks by these
body fields. An issue without a triage-role field is untriaged.

If the repository already has a documented role-to-label mapping, use it and
reconcile this file before changing a task. No label migration is implied.
Choosing a triage role does not authorize a proposal, start a worker, or approve
closing a task. Use the owner's request and the project workflow for those decisions.
