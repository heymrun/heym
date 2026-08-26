# OIDC Single Sign-On — Design

Date: 2026-08-26
Status: Approved, ready for implementation planning

## Goal

Let a Heym instance authenticate users against any external OpenID Connect provider,
configured at runtime from the admin settings UI. No identity provider name, URL, or
vendor-specific behavior may appear in Heym's code: the admin supplies an issuer URL and
everything else is derived from OIDC discovery.

Keycloak is used only as the local provider for manual verification. It is not a
dependency, not a code path, and nothing about it is committed to this repository.

## Non-goals

- SAML. OIDC is the default for new products; SAML is a separate future decision.
- Multiple simultaneous providers. One instance connects to one corporate IdP.
- Group or role mapping from IdP claims. Heym has no role model to map onto yet.
- Portal end-user login (`portal_users`). That is a different table and a different
  audience; it stays on its existing password flow.
- Self-service password reset for SSO-provisioned accounts.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Who configures SSO | New `HEYM_ADMIN_EMAILS` env allowlist | Mirrors the existing `HEYM_PLUGIN_ADMIN_EMAILS` pattern exactly. No migration, no new role model, and the break-glass path is already outside the database. |
| Provider count | Single singleton row | A self-hosted instance connects to one IdP. Switching providers means editing one row. |
| Unknown user on first SSO login | Auto-provision, admin toggle (default on) + optional email domain allowlist | What a team connecting Okta/Entra expects. The toggle and allowlist keep a shared IdP from becoming an open door. |
| Password login | Both enabled by default; admin may disable password login | Requested explicitly. Two guards prevent lockout (below). |
| OIDC client | Hand-rolled on `httpx` + `pyjwt[crypto]` | Zero new dependencies — all three libraries are already in `pyproject.toml`. Matches the existing `*_oauth.py` routers. Authlib's ~150 saved lines do not justify a new runtime dependency and a second OAuth style. |
| Client secret at rest | Fernet-encrypted via existing `encrypt_config` | The secret must be replayed to the IdP's token endpoint, so it cannot be hashed. `secret_tokens.py` governs secrets *we* verify; this is a credential we *present*. |

## Data model

### New table `sso_settings`

Singleton, addressed by a fixed sentinel primary key
(`SSO_SETTINGS_ID = UUID("00000000-0000-0000-0000-000000000001")`) so read-modify-write is
an upsert with no race.

| Column | Type | Default | Notes |
|---|---|---|---|
| `id` | UUID PK | sentinel | |
| `enabled` | bool | `false` | |
| `issuer` | String(512) | `""` | The only URL an admin types. Discovery derives the rest. |
| `client_id` | String(255) | `""` | |
| `encrypted_client_secret` | Text | `null` | Fernet, via `encrypt_config({"client_secret": ...})` |
| `scopes` | String(255) | `"openid email profile"` | |
| `button_label` | String(64) | `"Sign in with SSO"` | Keeps the provider's name in data, never in code |
| `auto_provision_users` | bool | `true` | |
| `allowed_email_domains` | String(512) | `""` | Comma-separated; empty means any domain |
| `password_login_disabled` | bool | `false` | |
| `last_test_ok` | bool | `false` | Precondition for `password_login_disabled` |
| `last_test_at` | timestamptz | `null` | |
| `updated_by_id` | UUID FK users.id ON DELETE SET NULL | `null` | Audit trail |
| `created_at` / `updated_at` | timestamptz | now() | |

### `users` changes

- `sso_issuer` String(512) nullable
- `sso_subject` String(255) nullable
- Unique index on `(sso_issuer, sso_subject)`
- `hashed_password` becomes **nullable**

Account resolution order on callback:

1. `(sso_issuer, sso_subject)` match — authoritative, survives email changes at the IdP.
2. Otherwise, a verified `email` match — the row is claimed and `sub` is written to it.
3. Otherwise, provisioning rules apply.

An email counts as verified only when the ID token carries `email_verified: true`. If the
claim is `false` or absent, the login is rejected with `email_not_verified`: claiming an
existing Heym account, or creating a new one, on the strength of an address the provider will
not vouch for is an account-takeover path. A provider that does not emit `email_verified` is
misconfigured for this purpose, and telling the admin so is better than guessing.

Migration: `115_add_sso_settings`, on top of head `114_add_workflow_http_method`.
Downgrade drops the table and the two user columns; it cannot restore a plaintext secret
because none was ever stored.

### Password verification guard

`hashed_password` becomes nullable, so `verify_password` must tolerate it. Passing an empty
or `None` hash to `bcrypt.checkpw` raises `ValueError: invalid salt`, turning a failed login
into a 500. One guard at the bottom of the stack covers all three call sites
(`auth.py` login, `auth.py` change-password, `oauth.py` MCP consent form):

```python
def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False
    ...
```

## Backend architecture

One responsibility per module, each independently testable.

| File | Responsibility |
|---|---|
| `app/services/oidc_client.py` | Pure OIDC mechanics: discovery fetch and cache, authorization URL construction, token exchange, ID token verification, userinfo fetch. Knows nothing about Heym. |
| `app/services/sso_settings.py` | Load and upsert the singleton, decrypt the client secret, evaluate the email domain allowlist. |
| `app/api/sso_auth.py` | Public routes: `/api/auth/sso/status`, `/login`, `/callback`. |
| `app/api/sso_admin.py` | Admin routes: `/api/admin/sso` GET/PUT, `/api/admin/sso/test`. |
| `app/api/deps.py` | `require_instance_admin(current_user)` — the twin of `plugins.py::require_plugin_admin`. |
| `app/config.py` | `admin_emails: str = Field(default="", validation_alias="HEYM_ADMIN_EMAILS")` |

### Public endpoints

**`GET /api/auth/sso/status`** — unauthenticated. Returns
`{enabled, button_label, password_login_enabled}` and nothing else. The issuer and client id
are not disclosed to anonymous callers.

**`GET /api/auth/sso/login`** — rate-limited with the existing `login_limiter`. Generates
`state`, `nonce`, and a PKCE `code_verifier`, then 302s to the IdP's `authorization_endpoint`
with `response_type=code`, `code_challenge_method=S256`, the configured scopes, and a
`redirect_uri` derived from `resolve_public_origin(request)`.

**`GET /api/auth/sso/callback`** — exchanges the code, verifies the ID token, resolves or
provisions the user, issues Heym's own tokens via the existing `create_access_token` /
`create_refresh_token` / `store_refresh_token` / `_set_auth_cookies` path, writes an
`audit(action="auth.sso_login", actor=user)` line, and 302s to the stored `next` path.

### Transaction state: cookie, not the `state` parameter

The PKCE `code_verifier` must not travel inside the `state` JWT. `state` round-trips through
the identity provider, and a signed JWT is not an encrypted one: the verifier would be
readable in the authorization URL, in IdP logs, and in any proxy in between, which defeats
the purpose of PKCE.

Instead a short-lived transaction cookie holds it:

- `sso_tx` = JWT signed with `settings.secret_key`, payload `{state, nonce, code_verifier, next, exp: +10m}`
- `HttpOnly`, `SameSite=lax`, `Secure` per the existing `_COOKIE_SECURE` logic, `path=/api/auth/sso/`
- The `state` URL parameter carries only a random identifier; the callback compares it to the
  cookie's copy and rejects a mismatch.

The `next` value is validated before it is stored, not after it comes back: it must be a
relative path beginning with a single `/` and not `//`. Anything else is discarded in favour
of `/`. An unchecked `next` turns the callback into an open redirect that a phishing page can
point anywhere.

`SameSite=lax` is correct here: the return from the IdP is a top-level GET navigation, so the
cookie is sent. No database table is needed for in-flight logins.

### ID token verification

`PyJWKClient(jwks_uri)` supplies the signing key (it caches keys itself). Then
`jwt.decode(token, key, audience=client_id, issuer=issuer, algorithms=...)` where the
algorithm list is the intersection of the provider's advertised
`id_token_signing_alg_values_supported` and an allowlist of asymmetric algorithms. `none` and
symmetric algorithms are rejected. After signature validation, `nonce` is compared to the
cookie's copy.

If the ID token carries no `email`, the `userinfo_endpoint` is queried as a fallback. Keycloak
returns `email` in the ID token under the `email` scope; not every provider does.

`sub` is read from the ID token only, never from userinfo.

The token endpoint's client authentication method is chosen from the provider's advertised
`token_endpoint_auth_methods_supported`, preferring `client_secret_post` and falling back to
`client_secret_basic`. Nothing is hardcoded to one provider's habit.

### Admin endpoints

**`GET /api/admin/sso`** returns the configuration with the secret replaced by
`client_secret_set: bool`, plus a computed read-only `redirect_uri`
(`resolve_public_origin(request) + "/api/auth/sso/callback"`). The admin copies that value
into the IdP's allowlist rather than retyping it, which removes the most common setup error.

**`PUT /api/admin/sso`** saves the configuration. An empty `client_secret` in the payload
**preserves the stored value**. Without this, the masked, empty editor field would overwrite
the real secret on the next save.

**`POST /api/admin/sso/test`** fetches discovery, asserts that `authorization_endpoint`,
`token_endpoint`, and `jwks_uri` are present, downloads JWKS, records the outcome in
`last_test_ok` / `last_test_at`, and returns the discovered endpoints.

### Disabling password login

When `password_login_disabled` is true, both password surfaces reject credentials:

- `POST /api/auth/login`
- the MCP OAuth consent form in `app/api/oauth.py` (currently around line 543)

Closing only the first would make the setting a lie. `portal.py` is out of scope — it
authenticates `portal_users`, a separate table and audience.

Two guards prevent lockout:

1. **Break-glass.** Accounts listed in `HEYM_ADMIN_EMAILS` may always sign in with a password.
   Whoever can edit the environment file can already recover the instance; this makes that
   guarantee explicit in code rather than incidental.
2. **Precondition.** The toggle can only be enabled when SSO is enabled *and* `last_test_ok`
   is true, so a wrong issuer cannot lock the door behind itself.

### Outbound request safety

The issuer is admin-supplied, which makes discovery an outbound-fetch surface. `ssrf_guard`
is deliberately **not** applied: it rejects private and loopback addresses, which is exactly
where a self-hosted IdP lives, and the admin is already a trusted boundary. The narrower
controls are:

- scheme restricted to `http`/`https`
- `follow_redirects=False`
- 10 second timeout
- bounded response size
- discovery cached in-process with a 5 minute TTL, keyed by issuer

## Frontend

### Admin visibility

`UserResponse` (`GET /api/auth/me`) gains `is_admin: bool`, computed from
`HEYM_ADMIN_EMAILS`. The plugins tab currently infers its availability by catching a 404;
the SSO tab should not repeat that. The frontend hides the tab honestly instead of
discovering the answer through a rejected request.

### Files

| File | Change |
|---|---|
| `src/services/sso.ts` | New. `getSsoStatus`, `getAdminSsoConfig`, `saveAdminSsoConfig`, `testSsoConnection` |
| `src/components/Layout/settings/SsoSettingsTab.vue` | New. The whole admin form. |
| `src/components/Layout/UserSettingsDialog.vue` | Tab button plus `<SsoSettingsTab v-if="activeTab === 'sso'">` — roughly ten lines |
| `src/views/LoginView.vue` | SSO button and conditional password form |
| `src/types/auth.ts`, `src/stores/auth.ts` | `is_admin` field |

`UserSettingsDialog.vue` is already 860 lines, past the 300-line guidance. Inlining the form
would push it beyond 1000. Extracting the tab body keeps the dialog's growth to the tab
button, and the new component owns its own state, loading, and handlers.

### SsoSettingsTab form

Enabled toggle · Issuer URL · Client ID · Client Secret (placeholder `••••••` when
`client_secret_set`; leaving it blank preserves the stored value) · Scopes · Button label ·
Auto-provision toggle · Allowed email domains · Redirect URI (read-only, with a copy button) ·
`Test connection` button reporting the discovered endpoints · and, visually separated and
styled as a warning, **Disable password login**, which stays disabled with an explanatory
tooltip until SSO is enabled and a connection test has passed.

### LoginView

On mount, `GET /api/auth/sso/status`.

- `enabled` renders a button labelled `button_label`. Its click handler performs a full
  navigation: `window.location.href = "/api/auth/sso/login"`. An XHR cannot follow the
  cross-origin redirect into the provider's login UI.
- `password_login_enabled === false` hides the password form and the register link, leaving
  only the SSO button.
- With both enabled: password form, divider, SSO button.

### Error surface

A failed callback redirects to `/login?sso_error=<code>` with a code drawn from a fixed set:
`state_mismatch`, `token_exchange_failed`, `invalid_token`, `email_missing`,
`domain_not_allowed`, `provisioning_disabled`, `sso_disabled`, `email_not_verified`. The frontend maps codes to
readable text. The provider's raw error string is never rendered — it is both an XSS surface
and an information leak.

## Testing

Backend tests are required by `AGENTS.md`.

**`backend/tests/test_sso_oidc_client.py`**
- discovery document parsing, including a document missing required endpoints
- authorization URL construction, asserting the `S256` challenge matches the verifier
- token exchange against a mocked `httpx` transport
- ID token verification: valid; wrong `aud`; wrong `iss`; expired; bad signature;
  `nonce` mismatch; `alg: none` rejected

**`backend/tests/test_sso_auth_flow.py`**
- state mismatch produces the error redirect, not an exception
- happy path creates the user and sets auth cookies
- an existing email is claimed and `sub` is written to that row
- `(issuer, sub)` match takes precedence over an email match
- a disallowed email domain is rejected
- auto-provisioning disabled plus an unknown email is rejected
- `email_verified: false` and a missing `email_verified` claim are both rejected, and neither
  claims an existing account
- a `next` value of `//evil.example` or an absolute URL falls back to `/`

**`backend/tests/test_sso_admin_api.py`**
- a non-admin receives 403
- the client secret is never present in any response body
- an empty `client_secret` on PUT preserves the stored value
- the test endpoint records `last_test_ok`

**`backend/tests/test_advisory_sso.py`**
- the stored client secret is not plaintext in the database
- `password_login_disabled` blocks both `/api/auth/login` and the `oauth.py` consent form
- a break-glass admin can still sign in with a password
- `verify_password(x, None) is False` rather than raising

**Frontend tests:** none. The standing instruction for this repository is to verify frontend
work with lint, typecheck, and manual checks rather than UI tests. `AGENTS.md` asks for
Playwright coverage on new UI; the repository owner's instruction takes precedence and was
reconfirmed for this feature.

## Documentation and release tour

This feature crosses the medium/large threshold in `AGENTS.md`, so both are required in the
same change:

- Docs via the `heym-documentation` skill: a new `frontend/src/docs/content/reference/sso.md`,
  plus updates to `reference/user-settings.md` and `reference/features.md`.
- A release tour section in `releaseRegistry.ts` with an animated mock registered in
  `tourVisuals.ts`, and the section id listed in that release's `sectionOrder`.

## Local identity provider

Keycloak runs from the session scratchpad, **not** from this repository — it is example setup
for manual verification, unrelated to the product. A `docker-compose.yml` (Keycloak 26 in dev
mode on port 8080, which is free on this machine) plus a realm import providing a `heym` realm,
a confidential client, and two test users.

Values the admin form receives during verification:

```
issuer        http://localhost:8080/realms/heym
client_id     heym
client_secret heym-local-secret-change-me
scopes        openid email profile
redirect_uri  http://localhost:4017/api/auth/sso/callback   (read-only, shown by the form)
```

The redirect URI resolves to the frontend origin because `vite.config.ts` proxies `/api` to
the backend, and `resolve_public_origin` returns `FRONTEND_URL`, which defaults to
`http://localhost:4017`. The browser only ever sees one origin; no second port is involved.

## Verification checklist

1. `./check.sh` from the repository root, with the backend suite passing.
2. Manual: configure the form, run `Test connection`, sign in as `ada@heym.local`, confirm a
   user row was created with `sso_issuer` and `sso_subject` set.
3. Manual: sign out, sign in again, confirm no second user row is created.
4. Manual: enable `Disable password login`, confirm `/api/auth/login` rejects a normal user
   and still accepts a `HEYM_ADMIN_EMAILS` account.
