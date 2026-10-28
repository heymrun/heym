"""What the Heym Agent says about itself, written once for MCP and A2A.

`heym_chat`'s tool description and the A2A Agent Card's description and skills are built
from here, so a new capability is described in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

AGENT_NAME = "Heym Agent"

AGENT_CAPABILITIES = (
    "list, inspect and run workflows; build a new workflow or change one it built earlier in "
    "the conversation, test-run it with sample inputs (at most 5 test runs per message) and "
    "fix it until a run passes; create, edit and run prompt and agent eval suites, including "
    "an agent's baseline; report analytics, where workflows fail and why they are slow (by "
    "workflow and by node type), recent executions, the run history of one "
    "workflow (how many times it ran, statuses, when, and the details of a single run), and "
    "which executions are running right now (with elapsed time, current node, and a link to "
    "each live run); read and resolve human-in-the-loop reviews; list and act on agentic "
    "kanban boards, cards and comments; list dashboards (Heym Work's pages) with the widgets "
    "on each and which dashboard a workflow is on, add a new widget to a dashboard and build "
    "its workflow, or put an existing workflow on a dashboard as a widget, rename or delete a "
    "widget and tidy a dashboard's layout; read schedules, teams and global variables; search "
    "the Heym documentation; and create or update the user's credentials on a secure Heym "
    "page the user opens in their browser, so keys and tokens never pass through the client."
)

_INTRO = (
    "Talk to the Heym Agent in natural language and let it act on the user's Heym account. "
    "It is the same engine that powers the Heym Chat tab, so it can do everything that tab "
    "can: "
)

MCP_TOOL_DESCRIPTION = (
    _INTRO
    + AGENT_CAPABILITIES
    + " Never put a secret in `message`. New Heym capabilities become available here "
    "automatically. Send one natural-language instruction or question as `message` and read "
    "the reply. Every call is recorded in the user's Chat tab history. To continue an "
    "earlier exchange instead of starting a new thread, pass the `conversation_id` returned "
    "by a previous call."
)

A2A_DESCRIPTION = (
    _INTRO
    + AGENT_CAPABILITIES
    + " Never put a secret in a message. Every task is recorded in the user's Chat tab "
    "history. Send follow-ups with the contextId of an earlier task to continue its "
    "conversation."
)


@dataclass(frozen=True)
class AgentSkillInfo:
    """One capability family, as an A2A skill."""

    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    examples: tuple[str, ...]


AGENT_SKILLS: tuple[AgentSkillInfo, ...] = (
    AgentSkillInfo(
        "workflows",
        "Workflows",
        "List, inspect and run the user's workflows.",
        ("workflows", "automation"),
        ("Run the invoice parser on this PDF link.", "Which workflows post to Slack?"),
    ),
    AgentSkillInfo(
        "build-workflows",
        "Build workflows",
        "Build or change a workflow, test-run it and fix it until a run passes.",
        ("build", "workflows", "testing"),
        ("Build a workflow that posts new Google Sheets rows to Slack.",),
    ),
    AgentSkillInfo(
        "evals",
        "Eval suites",
        "Create, edit and run prompt and agent eval suites, including an agent's baseline.",
        ("evals", "testing"),
        ("Create an eval suite for the support triage prompt.",),
    ),
    AgentSkillInfo(
        "observability",
        "Runs and analytics",
        "Report analytics, where workflows fail and why they are slow (by workflow and node "
        "type), recent executions, a workflow's run history and the runs in progress.",
        ("analytics", "executions", "observability"),
        (
            "How many times did the lead scorer fail this week?",
            "Why are my workflows slow today?",
        ),
    ),
    AgentSkillInfo(
        "human-review",
        "Human review",
        "Read and resolve human-in-the-loop reviews.",
        ("hitl", "approvals"),
        ("Show the reviews waiting for me.",),
    ),
    AgentSkillInfo(
        "boards",
        "Kanban boards",
        "List and act on agentic kanban boards, cards and comments.",
        ("kanban", "boards"),
        ("Move the onboarding card to Done.",),
    ),
    AgentSkillInfo(
        "dashboards",
        "Dashboards",
        "List dashboards and their widgets, add, rename or delete widgets and tidy a layout.",
        ("dashboards", "widgets"),
        ("Add a widget for weekly signups to the sales dashboard.",),
    ),
    AgentSkillInfo(
        "docs",
        "Heym documentation",
        "Search the Heym documentation.",
        ("docs", "help"),
        ("How do I schedule a workflow?",),
    ),
    AgentSkillInfo(
        "credentials",
        "Credentials",
        "Create or update credentials on a secure Heym page the user opens in a browser.",
        ("credentials", "security"),
        ("Set up my OpenAI credential.",),
    ),
)
