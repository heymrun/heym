# Security Policy

We take the security of Heym seriously. Thank you for helping keep Heym and its
users safe.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.** Public disclosure before a fix is available puts
all users at risk.

Instead, report privately through one of these channels:

- **Preferred — GitHub Private Vulnerability Reporting:** open a private report at
  <https://github.com/heymrun/heym/security/advisories/new>. This lets us
  collaborate on a fix in a private temporary fork and request a CVE where
  appropriate.
- **Email (fallback):** support@heym.run

### What to include

To help us triage quickly, please include as much of the following as you can:

- A clear description of the vulnerability and its security impact.
- The affected component, file(s), and the version or commit hash you tested
  against.
- Step-by-step reproduction instructions or a proof of concept.
- The deployment configuration relevant to the issue (impact can be
  deployment-dependent).
- Any suggested remediation, if you have one.

Non-destructive proofs of concept are greatly appreciated.

## Coordinated Disclosure

We follow a coordinated disclosure process:

- We aim to acknowledge your report within **3 business days**.
- We will confirm the issue, assess its impact, and keep you updated on progress.
- We develop and test the fix in a private temporary fork before any public
  change is pushed.
- We coordinate the disclosure timeline with you and request a CVE where
  appropriate.
- We credit reporters in the published advisory unless you ask to remain
  anonymous.

Please give us a reasonable amount of time to investigate and ship a fix before
any public disclosure.

## Testing Guidelines

When researching vulnerabilities, please:

- Only test against your own self-hosted instance. **Do not** test against
  instances you do not own or operate.
- Never access, modify, or exfiltrate data that does not belong to you.
- Avoid actions that could degrade service availability (e.g. denial of service).

## Supported Versions

Heym is distributed as a self-hosted application. Security fixes are released
against the latest version, and we recommend always running the most recent
release.

| Version               | Supported          |
| --------------------- | ------------------ |
| Latest release / main | :white_check_mark: |
| Older versions        | :x:                |

## Acknowledgments

We are grateful to the security researchers who responsibly disclose
vulnerabilities in Heym:

- [@jashidsany](https://github.com/jashidsany) for a sandbox escape in
  user-defined Python tools (GHSA-wcgw-9hfw-f6f2).
- [@okcomputerfan](https://github.com/okcomputerfan) (also known as pixileaf) for
  authentication and RCE issues across the condition evaluator, Slack and
  Telegram webhooks, OAuth `redirect_uri` validation, and token storage
  (GHSA-pm6h-x3h5-j38h).
- [@sajdakabir](https://github.com/sajdakabir) for four reports: SSRF in the MCP
  HTTP/SSE transports and a template IDOR (GHSA-5748-x76g-v68m), a missing
  creator gate in team member management (GHSA-vxpw-x7j7-8723), unsandboxed
  Agent Python skills (GHSA-hcv7-mg77-pg73), and command execution via the MCP
  `stdio` transport (GHSA-378x-q589-34mv).
- [@EQSTLab](https://github.com/EQSTLab) (reporter) and
  [@min8282](https://github.com/min8282) (finder) for backend RCE via the
  Playwright node's custom `playwrightCode` field (GHSA-mp23-7m6r-jfw4).
- [@0neOfU4](https://github.com/0neOfU4) for SSRF in the HTTP workflow node,
  which was guarded on the MCP transports but not there (GHSA-8wj7-v2w6-wfcx).
- [@euriconicacio](https://github.com/euriconicacio) for SSRF in the WebSocket
  Send and WebSocket Trigger egress paths (GHSA-mqw6-g845-w596), and for
  contributing the remediation.
- [@SashaMIT](https://github.com/SashaMIT) for three reports: an
  expression-engine sandbox escape via DotList item expressions and the
  simpleeval fallback (GHSA-87x2-9jwx-7gh4), SSRF in the LLM image-edit input
  loader, where a caller-controlled URL got a scheme-only check instead of the
  egress guard, and contributing that fix (GHSA-6rph-qqcv-jqh4), and a cluster
  of capability secrets stored or returned in plaintext across webhook auth,
  MCP keys, portal sessions, and Discord interactions (GHSA-6x65-w7q7-wg93).
- [@fatihkaratash](https://github.com/fatihkaratash) for the Redis node reading
  an inaccessible or missing credential as an empty configuration, so an
  authorization result fell through to the `localhost:6379` connection defaults
  instead of failing closed (GHSA-fmpw-hj3m-xvj6), and for contributing the
  remediation.
