# Guardrails

Guardrails let you block unsafe or unwanted user messages before they reach an [LLM](../nodes/llm-node.md) or [Agent](../nodes/agent-node.md) node. When a message matches a blocked category the node throws an error instead of executing, which you can catch with an [Error Handler](../nodes/error-handler-node.md) node.

## Enabling Guardrails

Open the Properties panel for an **LLM** or **AI Agent** node and scroll to the **Enable Guardrails** toggle (shield icon). Checking the box reveals the configuration section.

## Guardrail Credential and Model

When guardrails are enabled, you **must** select a **credential and model** for content safety. The guardrail check uses the selected credential and model from the node — no fallback, no environment variables. Use an OpenAI or Google credential for reliable content filtering, especially when your main model uses a custom provider (e.g. Zhipu, GLM) that may not support guardrails or returns API errors (e.g. 404).

The workflow cannot run until both Guardrail Credential and Guardrail Model are selected.

## Blocked Categories

Select one or more categories to block. A message that matches any checked category is rejected.

| Category | What it blocks |
|---|---|
| **Violence** | Violent, threatening, or physically harmful content |
| **Hate Speech** | Discrimination, racism, or bigotry |
| **Sexual Content** | Explicit sexual content or scenarios |
| **NSFW / Profanity** | Crude language, profanity, explicit slurs, and adult slang in any language |
| **Self-Harm** | Suicide, self-injury, or related content |
| **Harassment** | Personal attacks, insults, bullying, or intimidation |
| **Illegal Activity** | Instructions for committing illegal acts |
| **Political Extremism** | Extremist political content or violent propaganda |
| **Spam / Phishing** | Spam, phishing, or social engineering |
| **Personal Data Request** | Solicitation of private or personally identifiable information |
| **Prompt Injection** | Attempts to override system instructions, inject malicious prompts, or manipulate the model's behavior |

## Sensitivity

The **Sensitivity** setting controls how strictly violations are detected:

| Level | Behaviour |
|---|---|
| **Low** | Flags even borderline or ambiguous cases |
| **Medium** *(default)* | Flags clear violations; ignores borderline cases |
| **High** | Flags only extreme, unambiguous violations |

## How Detection Works

Detection uses the **selected guardrail credential and model**:

- **OpenAI credentials** — uses the [OpenAI Moderation API](https://platform.openai.com/docs/guides/moderation) (free, fast, no token usage) for the five categories it covers natively (Violence, Hate Speech, Sexual Content, Self-Harm, Harassment). Remaining categories are checked with an LLM classification call using the selected guardrail model.
- **Google / custom credentials** — all categories are checked with an LLM classification call using the selected guardrail credential and model.

When your main model uses a custom provider (e.g. Zhipu, Cerebras) that may return 404 or other API errors, select an **OpenAI or Google credential** for guardrails.

## Error Format

When a guardrail is triggered the node raises an error with the message:

```
Guardrail violation: message blocked due to prohibited content.
Violated categories: Violence, Hate Speech
```

The node result's `output` also includes `guardrail_violated_categories` (array of violated category labels) so the Debug Panel and Execution History can display "Blocked by: X, Y" clearly.

Use the node's **Continue on error** option (or an [Error Handler](../nodes/error-handler-node.md)) to route the workflow to a fallback branch when guardrails fire.

## Example Workflow

```
Input → Agent (guardrails: Violence, Illegal Activity, severity: Medium)
          ├── output handle → LLM → Output
          └── error handle  → Error Handler → Set("Sorry, that request was blocked.") → Output
```

## Notes

- **No retries**: Guardrail violations are intentional blocks and are never retried, even if the node has "Retry on failure" enabled.
- No database migration is required — guardrail settings are stored in the workflow's node JSON alongside other node data.
- Guardrails check the resolved **user message** (after template expressions are evaluated) not the raw template.
- Setting **no categories** while guardrails are enabled is equivalent to having them disabled — no check is performed.
- At **Low** severity, LLM classification always runs (best multilingual coverage). OpenAI credentials additionally run the Moderation API.
- At **Medium/High** severity, OpenAI credentials use the Moderation API for natively supported categories and LLM classification for the rest. Google/custom credentials always use LLM classification.
- LLM classification is **language-agnostic** — it detects violations in Turkish, Arabic, Russian, Spanish, and other languages.
