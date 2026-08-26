# Audit Logging

Heym writes an audit line for every security-relevant action: who did it, what they did it to, and whether it succeeded. Lines go to the backend's standard output through the `winston.audit` logger, alongside the request access log, and can be read from the **Logs** tab or with `docker logs`.

Audit logging is **always on**. There is nothing to enable and no environment variable to set.

## Line Format

One action produces exactly one self-contained line:

```
2026-08-25 14:02:11 INFO [winston.audit] audit action=credential.delete outcome=success actor_id=8f2c1b04-3d5a-4f21-9c7e-1a2b3c4d5e6f actor_email=alex@example.com target=credential:3a91d7e2-55c8-4b19-b0a1-9e8d7c6b5a43 target_name="OpenAI Prod" credential_type=openai
```

Every line carries these fields:

| Field | Description |
|-------|-------------|
| `action` | What happened, as `resource.verb` — see the table below. |
| `outcome` | `success`, `failure`, or `denied`. |
| `actor_id` | UUID of the user who performed the action. Absent only when nobody was authenticated. |
| `actor_email` | Email of that user. On a failed login this is the address that was tried, not a confirmed account. |
| `target` | The object acted on, as `type:uuid`. |
| `target_name` | Human-readable name of that object, quoted when it contains spaces. |

Action-specific fields follow — for example `credential_type`, `imported`, `grantee_email`, `team_name`. Values containing a space, quote, or `=` are quoted; values longer than 256 characters are cut with a `...(truncated)` marker.

## Reading the Log

The audit logger is a child of the request logger, so both reach the same stream while staying separable:

```bash
# Only audit lines, no access-log noise
docker logs heym-backend 2>&1 | grep '\[winston.audit\]'

# Everything one user did
docker logs heym-backend 2>&1 | grep 'actor_email=alex@example.com'

# Failed logins and refused access
docker logs heym-backend 2>&1 | grep -E 'outcome=(failure|denied)'

# Everything that touched one credential
docker logs heym-backend 2>&1 | grep 'target=credential:3a91d7e2-55c8-4b19-b0a1-9e8d7c6b5a43'
```

In the app, the **Logs** tab reads the same container output. It is gated by `DOCKER_LOGS_ENABLED` and the `DOCKER_LOGS_ALLOWED_EMAILS` allowlist.

## What Is Logged

Every state change is logged. Reads are logged only where reading is itself the sensitive act — viewing a workflow's run history, opening a credential, downloading a file. Ordinary list and detail reads are not audited; the access log already records that a request happened, and auditing every `GET` would bury the lines that matter.

### Authentication

| Action | Notes |
|--------|-------|
| `auth.register` | `outcome=denied` when registration is disabled or when password sign-in is off (`reason=password_login_disabled`), `failure` when the email is taken. |
| `auth.login` | `outcome=failure` records the attempted address and whether the email was unknown or the password wrong. |
| `auth.logout` | The actor is resolved from the refresh cookie, so a logout without one is logged with no identity. |
| `auth.token_refresh` | `outcome=denied` with `reason=refresh_token_replayed_or_revoked` — a token-theft signal worth alerting on. |
| `auth.password_change` | `outcome=failure` when the current password was wrong. |
| `auth.sso_login` | Single sign-on. `outcome=failure` carries the reason the provider response was rejected; `denied` carries `email_not_verified`, `domain_not_allowed`, or `provisioning_disabled`. |
| `sso_settings.update` | An administrator changed the [SSO](./sso.md) configuration. Records `enabled` and `password_login_disabled`, never the client secret. |
| `sso_settings.test` | An administrator ran the SSO connection test. |

### Workflows

`workflow.create` · `workflow.update` · `workflow.delete` · `workflow.version_revert` · `workflow.history_view` · `workflow.history_clear` · `workflow.share_add` · `workflow.share_remove` · `workflow.team_share_add` · `workflow.team_share_remove` · `workflow.execution_token_create` · `workflow.execution_token_revoke`

`workflow.history_view` records `owned=false` when a collaborator reads someone else's run history. `workflow.delete` records `outcome=denied` with `reason=not_owner` when a collaborator tries to delete.

### Credentials

`credential.create` · `credential.update` · `credential.delete` · `credential.detail_view` · `credential.share_add` · `credential.share_remove` · `credential.team_share_add` · `credential.team_share_remove`

`credential.detail_view` is audited because opening a credential decrypts it. A miss logs `outcome=denied`, which is what a credential-id enumeration attempt looks like.

### Other resources

| Resource | Actions |
|----------|---------|
| Variables | `variable.create` · `update` · `delete` · `bulk_delete` · `share_add` · `share_remove` · `team_share_add` · `team_share_remove` |
| Vector stores | `vector_store.create` · `update` · `delete` · `clone` · `upload` · `item_delete` · `items_delete_by_source` · `share_add` · `share_remove` · `team_share_add` · `team_share_remove` |
| Alerts | `alert.create` · `update` · `delete` · `event_acknowledge` · `share_add` · `share_remove` · `team_share_add` · `team_share_remove` |
| Data tables | `data_table.create` · `update` · `delete` · `clone` · `row_create` · `row_update` · `row_delete` · `rows_clear` · `rows_bulk_create` · `import_csv` · `export_csv` · `share_add` · `share_remove` · `team_share_add` · `team_share_remove` |
| Boards | `board.create` · `update` · `delete` · `column_create` · `column_update` · `column_delete` · `column_empty` · `card_create` · `card_update` · `card_delete` · `card_move` · `card_run` · `share_add` · `share_remove` · `team_share_add` · `team_share_remove` |
| Drive | `drive.upload` · `download` · `delete` · `delete_all` · `bulk_delete` · `share_create` · `share_revoke` · `team_sharing_update` · `bulk_team_sharing_update` |
| Teams | `team.create` · `update` · `delete` · `member_add` · `member_remove` |
| Folders | `folder.create` · `update` · `delete` · `workflow_move` |

Bulk operations are logged once per request with a count, not once per row. A CSV import of 5,000 rows produces one `data_table.import_csv` line carrying `imported`, `rejected`, and `total`.

## Secrets Are Never Logged

An audit line records identifiers, names, and counts. It never records a credential's contents, a variable's value, a password, or a token.

Two things enforce this. Call sites are written to pass only safe fields, and the audit helper redacts as a backstop: any field whose name contains `password`, `secret`, `token`, `api_key`, `value`, `authorization`, `cookie`, or similar is replaced with `***` before the line is built. Over-redaction is deliberate — an unhelpful line is better than a leaked credential.

Where a secret is genuinely relevant to the record, only its shape is logged. A file share records `password_protected=true`, never the password.

## Retention

**Audit lines live only as long as the container's log output.** They are not written to the database. Recreating the backend container discards its logs.

If you need audit history that survives a redeploy, ship the container's stdout somewhere durable — a log driver, a sidecar collector, or your platform's log aggregation — the same way you would for any other container log.

## For Contributors

Emitting an audit line takes one call:

```python
from app.services.audit_log import audit

audit(
    action="credential.delete",
    actor=current_user,
    target_type="credential",
    target_id=credential.id,
    target_name=credential.name,
)
```

The helper is synchronous, touches no database, and swallows its own errors, so an audit call cannot fail or slow a request.

Three rules when adding one:

1. **Name the action `resource.verb` in snake_case.** `backend/tests/test_audit_log.py` walks every `audit()` call under `app/api/` and fails the build on a name that does not match, and on a covered resource that has lost all of its call sites.

2. **Only read attributes that are certainly present.** The helper's `try/except` protects its own body, not the expressions you pass to it — an `AttributeError` in `target_name=workflow.name` is raised at the call site, before `audit()` runs, and will break the request. Read ORM columns and locals, not optional or lazily-loaded attributes.

3. **Log the deletion before the delete.** After `db.delete(row)` the name and id you want to record may be gone. Place the call above it.
