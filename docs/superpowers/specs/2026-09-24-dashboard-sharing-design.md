# Multiple dashboards and dashboard sharing

Date: 2026-09-24
Status: approved, implementing (local diff, no commit)

## Goal

A user can own several dashboards and share any of them with users and teams, with the same
`read` / `write` model the Board (Kanban) tab already uses.

## Decisions

- **Permissions mirror Board.** `read` views and refreshes; `write` also edits widgets and
  their workflows; only the owner renames, deletes and manages sharing.
- **Widgets always run as the dashboard owner.** Credentials, global variables, traces and
  analytics belong to the owner, whoever is looking. One cache per widget stays coherent, and
  a viewer without the owner's credentials still sees data. Board card runs already work this
  way.
- **Widget workflows belong to the dashboard owner**, including widgets a `write` collaborator
  creates or clones. The owner can always edit everything on their dashboard.
- **`write` grants workflow access to the dashboard's widget workflows** through a fourth
  branch in `workflow_access_clause` (IN-subqueries only, no JOIN). `read` grants none. This
  is the same trust as sharing a workflow with edit rights, and the share UI says so.

## Data model

Migration `127_add_dashboard_shares` adds `dashboard_shares` (dashboard_id, user_id,
permission) and `dashboard_team_shares` (dashboard_id, team_id, permission), each unique per
pair and cascading on delete, identical in shape to `board_shares`. `dashboards` already
allows many rows per owner, so no data migration is needed.

## Permission matrix

| Action | owner | write | read |
|---|:-:|:-:|:-:|
| List, open, load widget data, refresh (incl. force) | yes | yes | yes |
| Execution highlights in widget data | yes | yes | no |
| Create / clone / update / delete widgets, AI generate / refine, task checkboxes | yes | yes | no |
| Open a widget workflow in the editor | yes | yes | no |
| Rename / delete the dashboard, manage shares | yes | no | no |

`read` viewers never receive `highlight`: it carries raw intermediate node outputs, which is
more than the chart the owner chose to share.

## API

- `GET /dashboards` returns summaries (owned first, then shared) with `permission`, owner
  identity and widget count; creates a default dashboard when the caller owns none.
- `POST /dashboards`, `GET /dashboards/{id}`, `PATCH /dashboards/{id}` (owner),
  `DELETE /dashboards/{id}` (owner; deletes the hidden widget workflows; the caller's last
  owned dashboard cannot be deleted, 409).
- Widget creation moves under the dashboard: `POST /dashboards/{id}/widgets` and
  `POST /dashboards/{id}/widgets/ai-generate`. Existing `/dashboards/widgets/{widget_id}/…`
  routes resolve permission from the widget's dashboard.
- Sharing: `GET/POST /dashboards/{id}/shares`, `DELETE /dashboards/{id}/shares/{user_id}`,
  `GET/POST /dashboards/{id}/team-shares`, `DELETE /dashboards/{id}/team-shares/{team_id}`.
  Removing a share or downgrading it to `read` revokes execution tokens that lost access.
- Audit: `dashboard.create`, `update`, `delete`, `widget_create`, `widget_delete`,
  `share_add`, `share_remove`, `team_share_add`, `team_share_remove`.

## Frontend

- Pinia `stores/dashboard.ts` holds the list, the open dashboard, `canWrite` and `isOwner`.
- Header: dashboard selector (shared dashboards labelled with their owner), **New dashboard**,
  **Settings** (owner: rename, share with users/teams, delete), and a "Shared by … · Can
  view / Can edit" badge for non-owners.
- Read-only viewers keep Refresh and auto-refresh; editing controls, the widget menu, inline
  title editing, double-click-to-editor and task checkboxes are hidden or disabled.
- The open dashboard lives in the URL (`?tab=dashboard&dashboard=<id>`) and in localStorage,
  so "Back to Dashboard" in the editor returns to the dashboard the widget came from.

## Out of scope

Moving or copying widgets between dashboards, duplicating a dashboard, public (logged-out)
links, and letting a recipient hide a shared dashboard.

## Verification

Backend pytest (permission matrix, run-as-owner, highlight stripping, last-dashboard guard,
share CRUD, access-clause branch and its read-share negative case), ruff, frontend lint +
typecheck + vitest (release tour registry). No new UI tests, per standing preference.
