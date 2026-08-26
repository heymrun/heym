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

**Test connection** fetches the discovery document and the provider's signing keys, then reports the token endpoint it found. Run it before enabling SSO. Changing the issuer, client ID, scopes, or secret clears the recorded result, because a passing test belongs to the settings it was run against.

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

The **Disable password sign-in** switch stays unavailable until SSO is enabled **and** a connection test has passed, so a wrong issuer cannot lock the door behind itself.

When it is on, password authentication is refused on both surfaces that accept one: the normal login form and the MCP OAuth consent page.

Accounts listed in `HEYM_ADMIN_EMAILS` are always exempt. Whoever can edit the environment file can already recover the instance, so this guarantee lives in code rather than in an operator's memory. Keep at least one such account with a working password.

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
