# Single Sign-On

Heym can authenticate people against any external **OpenID Connect** provider. An administrator enters an issuer URL under **Settings → SSO**, and Heym reads every other endpoint from that provider's discovery document.

No provider is hardcoded. Keycloak, Okta, Entra ID, Auth0, Google and any other OIDC provider connect through the same fields, because the only thing Heym is told is the issuer.

Password sign-in and SSO work side by side. Password sign-in can be switched off once SSO is verified.

## Before You Start

SSO settings are instance-wide, so only instance administrators may change them. Administrators are named by an environment variable, not stored in the database:

```
HEYM_ADMIN_EMAILS=admin@example.com,ops@example.com
```

An empty value grants nobody. Restart the backend after changing it. Accounts on this list also see the **SSO** tab in Settings, and keep password access even when password sign-in is disabled — see [Disabling Password Sign-In](#disabling-password-sign-in).

## Registering Heym With Your Provider

In your identity provider, create a **confidential client** (also called an app registration) with:

| Setting | Value |
|---------|-------|
| Protocol | OpenID Connect |
| Grant type | Authorization Code with PKCE |
| Client authentication | On — Heym uses a client secret |
| Redirect URI | The exact value shown in Heym's SSO tab |
| Scopes | `openid email profile` |

Heym computes the redirect URI from `FRONTEND_URL` and shows it read-only in the settings form with a copy button. It always ends in `/api/auth/sso/callback`. Copy it rather than typing it — a mismatched redirect URI is the most common setup failure, and providers reject it without explanation.

Your provider must return a verified email address. See [Account Mapping](#account-mapping).

## Configuring Heym

Open **Settings → SSO**. The tab only appears for accounts in `HEYM_ADMIN_EMAILS`.

| Field | What it does |
|-------|--------------|
| **Enable single sign-on** | Shows the sign-in button on the login screen. |
| **Issuer URL** | The provider's base URL, for example `https://idp.example.com/realms/your-realm`. Heym appends `/.well-known/openid-configuration` and reads the rest from there. |
| **Client ID** | The client identifier from your provider. |
| **Client secret** | Stored encrypted. Leave the field blank to keep the stored value — Heym never returns a secret it holds. |
| **Redirect URI** | Read-only. Copy this into your provider's allowlist. |
| **Scopes** | `openid email profile` by default. |
| **Sign-in button label** | The text on the login screen button, for example "Sign in with Okta". |
| **Create an account on first sign-in** | Whether unknown people get a Heym account automatically. |
| **Allowed email domains** | Comma-separated. Blank allows any domain the provider authenticates. |
| **Disable password sign-in** | Turns off password authentication instance-wide. |

### Test the connection first

**Test connection** fetches the discovery document and the provider's signing keys, then reports the token endpoint it found. You can run it on an issuer you have typed but not saved yet, so a wrong URL costs a click rather than a save.

A test only *records* a passing result when the issuer tested is the one already stored. A draft test tells you whether the URL resolves; it does not license a configuration that is not saved. Changing the issuer, client ID, scopes, or secret clears the recorded result for the same reason.

## How Sign-In Works

1. Someone clicks the sign-in button on the login screen.
2. Heym redirects them to the provider with a `state`, a `nonce`, and a PKCE challenge.
3. They authenticate with the provider.
4. The provider redirects back to Heym's callback with an authorization code.
5. Heym exchanges the code for tokens and verifies the ID token against the provider's published keys, checking the signature, audience, issuer, expiry, and nonce.
6. Heym resolves the account and issues its own session, exactly as a password sign-in does.

Everything downstream of step 6 is unchanged: the same session cookies, the same token lifetimes, the same permissions.

## Account Mapping

Heym resolves an account in this order:

1. **`(issuer, subject)`** — the identity the provider asserted on a previous sign-in. This is authoritative and survives an email change at the provider.
2. **Verified email** — an existing Heym account with that address is claimed, and the provider's subject is recorded on it from then on.
3. **A new account** — created if **Create an account on first sign-in** is on and the domain is allowed.

An email counts as verified only when the ID token carries `email_verified: true`. If that claim is `false` or missing, the sign-in is refused. Claiming an existing account — or creating a new one — on the strength of an address the provider will not vouch for is an account-takeover path, so Heym does not do it. A provider that never emits `email_verified` needs to be configured to do so.

Accounts created this way have no password. They sign in through the provider only.

## Disabling Password Sign-In

The **Disable password sign-in** switch stays unavailable until three things are true:

1. SSO is enabled.
2. A connection test has passed, so a wrong issuer cannot lock the door behind itself.
3. At least one account in `HEYM_ADMIN_EMAILS` actually has a password.

When it is on, password authentication is refused on all three surfaces that mint or accept one: the login form, **registration**, and the MCP OAuth consent page. Registration counts because it issues a password; leaving it open would make the setting bypassable by anyone who can reach `/register`.

Accounts listed in `HEYM_ADMIN_EMAILS` are exempt from all three. Whoever can edit the environment file can already recover the instance, so this guarantee lives in code rather than in an operator's memory.

### Why the third condition exists

An administrator whose Heym account was created *through* SSO has no password at all. The exemption would let them past the gate, but there is nothing for them to sign in with — so the instance would have no way back if the provider went down. Heym refuses to enter that state and says so.

If you hit that message, sign in through SSO and register a password account on one of your admin addresses (registration is still open to admin addresses for exactly this reason), or add an address that already has a password to `HEYM_ADMIN_EMAILS`.

### Recovering when the provider is down

In order of preference:

1. **Sign in with a break-glass admin password.** The login screen hides the password form when password sign-in is off, so click **Sign in with a password instead** underneath the SSO button to reveal it. The form is not a bypass: every address outside `HEYM_ADMIN_EMAILS` is still refused, and told why.
2. **Add yourself to `HEYM_ADMIN_EMAILS`** in the environment file and restart the backend. An account that already has a password can then sign in.
3. **Re-open password sign-in directly in the database**, if no admin has a password at all:

   ```sql
   UPDATE sso_settings SET password_login_disabled = false;
   ```

   No restart is needed; the setting is read per request.

Portal end-users are unaffected. They authenticate against a separate directory — see [Portal](./portal.md).

## Sign-In Errors

A failed sign-in returns to the login screen with a readable message. Heym never displays the provider's raw error text.

| Message | Cause |
|---------|-------|
| That sign-in attempt expired | The attempt took longer than ten minutes, or the browser dropped the transaction cookie. Try again. |
| Could not reach the identity provider | Discovery or the token exchange failed. Check the issuer URL and that the provider is reachable from the backend. |
| The provider's response could not be verified | The ID token failed signature, audience, issuer, expiry, or nonce validation. Usually a client ID mismatch. |
| The provider did not return an email address | The `email` scope is missing, or the provider does not release the claim. |
| Your email address is not verified | The provider sent `email_verified: false`, or omitted the claim. |
| Your email domain is not allowed | The address is outside **Allowed email domains**. |
| No Heym account exists for you | **Create an account on first sign-in** is off and no account matches. An administrator must create one. |
| Single sign-on is not configured | SSO is disabled, or the issuer, client ID, or secret is missing. |

## Security Notes

- **The client secret is encrypted at rest** and is never returned by any endpoint. The settings form reports only whether one is stored.
- **The PKCE verifier never leaves Heym.** It is held in a short-lived `HttpOnly` cookie rather than in the `state` parameter, which round-trips through the provider in plain view.
- **Only asymmetric signatures are accepted.** `none` and symmetric algorithms are rejected regardless of what the provider advertises.
- **The post-login destination is validated** as a same-origin path, so the callback cannot be used as an open redirect.
- **Every sign-in is audited.** Successes, failures, and refusals appear as `auth.sso_login` lines, and configuration changes as `sso_settings.update` — see [Audit Logging](./audit.md).

## What Is Not Supported

- **SAML.** OIDC is the only protocol.
- **Multiple simultaneous providers.** One instance connects to one provider.
- **Group or role mapping** from provider claims.
- **Single logout.** Signing out of Heym does not sign you out of the provider.
