# Decision

The **Decision** node asks a decision model typed questions about the run's current state and returns probabilities. It does not generate text. Reach for it when a workflow needs a judgment it can branch on — routing, triage, ranking, verification, or gating a step that cannot be undone.

Decision models (also called *System One* models) are a different kind of model from an LLM. There is no prompt, no system instruction, no temperature and no tool calling. You send a **state** plus a map of **questions**, and each answer comes back as a number with a probability distribution behind it. Because an answer is only a few tokens, these models are fast and cheap compared with asking an [LLM](./llm-node.md) to produce JSON and parsing it.

For text generation, use the [LLM](./llm-node.md) node. For a model that calls tools, use the [Agent Node](./agent-node.md).

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | The provider response verbatim — `$nodeLabel.answers.<id>`, `$nodeLabel.model`, `$nodeLabel.usage` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | A *Decision Model* credential. Not an LLM credential. |
| `model` | string | Model name, for example `jev-latest` |
| `state` | expression | What the model should read (default `$input.text`) |
| `questions` | array | Ordered question rows; at least one |
| `imagesEnabled` | boolean | Send the image rows with the request (default: off) |
| `images` | array | Ordered `{ name, source }` rows; see [Images](#images) |
| `customBodyEnabled` | boolean | Send a hand-written request body instead of the form |
| `customBody` | expression (JSON) | The body to send when the toggle is on |
| `requestTimeoutSeconds` | number | Max seconds to wait (default: 60) |

### State

**State** is the situation the model judges. It accepts a string, an object or an array.

A field holding exactly one expression keeps its own type, so `$input` sends the object itself rather than its text. A template with an expression inside it (`Ticket: $input.text`) resolves to a string. Give each question enough to answer with: source text, identities, relationships, policies and current facts.

## Question types

Each question has an `id`, a `type`, `instructions`, and criteria that depend on the type.

The `id` is how your workflow reads the answer back. It is **never sent to the model**, so the whole meaning has to live in `instructions`. Writing `id: is_urgent` with `instructions: "Is it?"` gives the model nothing to work with.

### Noul

Whether a condition holds. Returns the probability that the answer is yes, from 0 to 1.

Criteria are optional: **Yes means** and **No means** describe what each side covers. A value near 0.5 means the model finds yes and no about equally likely — not "medium intensity".

```json
{
  "id": "is_urgent",
  "type": "noul",
  "instructions": "Does this message convey urgency?",
  "criteriaTrue": "Explicitly time-sensitive or blocking work",
  "criteriaFalse": "No urgency expressed"
}
```

Read it with `$triage.answers.is_urgent.noul`.

### Choice

Picks one option from a set you define. Returns the chosen option, the full distribution, and a confidence derived from it.

Add an option covering "none of these" whenever nothing may fit — the model cannot choose an option you did not offer.

```json
{
  "id": "department",
  "type": "choice",
  "instructions": "Which team should handle this request?",
  "options": [
    { "key": "billing", "description": "Payments, invoicing, refunds" },
    { "key": "technical", "description": "Bugs, outages, integrations" },
    { "key": "other", "description": "Nothing above fits" }
  ]
}
```

Read it with `$triage.answers.department.choice`, `.probabilities.billing` and `.confidence`.

### Score

Rates the state along an ordered rubric. Returns a probability-weighted value that can land **between** levels, plus the legend and the distribution.

Levels run lowest first, at least two and at most ten. Each level should describe a concrete situation and stand on its own.

```json
{
  "id": "frustration",
  "type": "score",
  "instructions": "How frustrated is the customer?",
  "levels": ["Calm", "Frustrated", "Very angry"]
}
```

Read it with `$triage.answers.frustration.score`, `.legend` and `.confidence`.

### Box

Finds where something is in an image. Returns the four edges of a bounding box, each a fraction of the image's width or height measured from the top-left corner, plus a confidence.

A box takes instructions only, no criteria. Name the target and the image it is in: "the dog in `photo`" is enough. It needs at least one [image](#images) and the model `jev-1.14.0` or `jev-preview`.

A box always comes back as a box, even when the target is not in the image. Ask a **noul** alongside it and ignore the box when that answer is low.

```json
[
  { "id": "is_dog", "type": "noul", "instructions": "Is there a dog in `photo`?" },
  { "id": "dog", "type": "box", "instructions": "the dog in `photo`" }
]
```

Read it with `$check.answers.dog.box.left`, `.top`, `.right`, `.bottom` and `$check.answers.dog.confidence`. To get pixels, multiply `left` and `right` by the image width and `top` and `bottom` by its height.

## Images

Turn on **Send images** to let the questions look at pictures: "Is this a dog?", "Is the dog in `photo` the same dog as in `poster`?", "Did the door open between `before` and `after`?".

> Images and box questions are experimental at TypeSafe. They are good for prototypes and trying ideas, but the provider does not yet recommend them for production decisions, and the request format and accuracy may change between releases.

Each row has a **name** and a **source**:

- **Name** is how questions refer to the image, in backticks: `` `photo` ``. Use letters, digits and underscores, starting with a letter or underscore. Names must be unique.
- **Source** is an expression that resolves to an `http(s)` image URL, a `data:image/...` URL, or plain base64, the same forms the [LLM](./llm-node.md) node accepts for image input. URLs are fetched with Heym's outbound address guard, so a private or loopback address needs `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`.

At run time each image joins the **State** under its name:

| State resolves to | What the model reads |
|-------------------|----------------------|
| empty | `{ "photo": <image> }` |
| an object | the object with `photo` added; a field already named `photo` is an error |
| text or a list | `{ "context": <state>, "photo": <image> }` |

So a question about a text state together with an image reads "Does the dog in `photo` match the description in `context`?".

Heym prepares every image before sending it, because the provider rejects images outside its limits instead of resizing them:

- the photo is rotated upright using its EXIF orientation,
- an animated image is reduced to its first frame,
- the longest side is scaled down to at most 1568 pixels,
- a side shorter than 280 pixels is scaled up, or padded when scaling would make the other side too long,
- the result is re-encoded as JPEG, or PNG when it has transparency.

Heym also adds the `TypeSafe-Danger-Zone-Images: true` header that turns images on at the provider. You do not need to set it yourself. A request with too many or too large images fails with a 413; send fewer images, or split the work across two Decision nodes.

Images count as input tokens, so they show up in `usage.input_tokens` and in [Traces](../tabs/traces-tab.md). Traces record each image's size, not its data.

## Generate with AI

**Generate with AI** turns a plain sentence into a suggested state template and a set of question rows. Describe what you want judged — "triage an incoming support ticket: how urgent it is, which team owns it, and how frustrated the customer sounds" — and review what comes back before adding it to the node.

The drafting is done by an LLM, so the dialog asks for an LLM credential. The decision model answers the questions later, when the workflow runs. Generated ids are de-duplicated against the rows the node already holds, so generating twice never overwrites an existing answer key.

When **Send images** is on, the dialog passes the image names along, so the drafted questions refer to them (`` `photo` ``) and may include a box question. Without images it never drafts a box.

Each generation is recorded in the [Traces](../tabs/traces-tab.md) tab under the **Decision Questions** source, alongside the `decision.systemone` traces written by the node itself at run time.

## Custom request body

Turn on **Custom request body** to send JSON you write yourself instead of the form. Use it for an endpoint whose contract differs from the one the form builds.

The editor is seeded from the current form, and expressions inside it are resolved before the request is sent. While the toggle is on, the State field, the images and the question rows are ignored. The response is passed through unchanged either way, so a different contract simply produces a different shape for your expressions to read.

To send images from a custom body, write the provider's `assets` map yourself. Heym still adds the image opt-in header whenever the body has assets or a box question.

## Output

The node returns exactly what the provider returned. Nothing is renamed or flattened.

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_urgent": { "type": "noul", "noul": 0.95 },
    "department": {
      "type": "choice",
      "choice": "billing",
      "probabilities": { "billing": 0.88, "technical": 0.12, "other": 0.0 },
      "confidence": 0.81
    },
    "frustration": {
      "type": "score",
      "score": 1.05,
      "legend": { "0": "Calm", "1": "Frustrated", "2": "Very angry" },
      "probabilities": { "0": 0.0, "1": 0.95, "2": 0.05 },
      "confidence": 0.92
    }
  },
  "usage": { "input_tokens": 296, "output_tokens": 20 }
}
```

## Branching on an answer

A [Switch](./switch-node.md) node routes on the chosen option, and a [Condition](./condition-node.md) node can send low-confidence cases somewhere a person will see them:

```
Input → Decision (triage) → Condition ($triage.answers.department.confidence > 0.7)
                              ├─ true  → Switch on $triage.answers.department.choice
                              └─ false → Send Email (human review)
```

A typed answer guarantees the shape, not the truth. Pick thresholds against your own data and consequences rather than copying a number from an example.

## Credential

Create a **Decision Model** credential in the [Credentials](../tabs/credentials-tab.md) tab with:

- **Base URL** — the endpoint, for example `https://api.typesafe.ai`. Heym appends `/v1/systemone`.
- **API Key** — optional. Endpoints that need no key can be left blank.

Editing a credential keeps the stored key when the key field is left blank; retype it only to replace it.

The same credential can judge [Evals](../tabs/evals-tab.md) runs: with **LLM-as-Judge** selected, pick it as the judge and the decision model scores every answer against the expected output.

Heym blocks outbound requests to private and loopback addresses by default, so a decision endpoint you run yourself on `localhost` or a private range needs `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`.

Decision models do not appear in the LLM pricing tables Heym syncs, so the **Cost** column in [Traces](../tabs/traces-tab.md) stays empty for these calls. Token counts are still recorded, and you can add your own price with a pricing override.

## Errors

| Situation | What happens |
|-----------|--------------|
| Invalid API key | The node fails with a message naming the credential |
| Malformed question | The provider's own field-level message is carried into the node error |
| Rate limited or overloaded | The node fails with a message saying the condition is transient — turn on [retry](../reference/features.md) for this node to ride it out |
| Duplicate or empty question id | The node fails before any request is sent |
| Box question without an image | The node fails before any request is sent |
| Image name empty, repeated, not a plain name, or already a state field | The node fails before any request is sent, naming the image |
| Image source resolves to nothing, cannot be fetched, or is not an image | The node fails, naming the image |
| Too many or too large images (413) | The node fails asking for fewer or smaller images |

## Related

- [LLM Node](./llm-node.md) – Generate text instead of a judgment
- [Agent Node](./agent-node.md) – Gather evidence with tools, then judge it here
- [Switch Node](./switch-node.md) – Route on the chosen option
- [Condition Node](./condition-node.md) – Gate on confidence
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials](../reference/credentials.md) – Credential types and fields
- [Traces Tab](../tabs/traces-tab.md) – Inspect decision calls and token usage
