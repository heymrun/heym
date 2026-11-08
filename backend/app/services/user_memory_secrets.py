"""Text that looks like a credential, so memory writes can refuse it.

User Rules reach every later prompt, so a key saved there would be sent to every model the user
talks to. The checks are shapes, not proof: known token prefixes, credential-bearing headers and
URLs, secret-named assignments, long hex runs and long random-looking runs. A UUID, an ordinary
URL and ordinary prose pass.
"""

import math
import re
from collections import Counter

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "an OpenAI or Anthropic API key",
        re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    ),
    (
        "a GitHub token",
        re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    ),
    ("a GitLab token", re.compile(r"(?<![A-Za-z0-9])glpat-[A-Za-z0-9_\-]{20,}")),
    ("a Slack token", re.compile(r"(?<![A-Za-z0-9])xox[abposr]-[A-Za-z0-9-]{10,}")),
    ("an AWS access key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])")),
    ("a Google API key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}")),
    (
        "a JSON Web Token",
        re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ),
    (
        "an Authorization header",
        re.compile(r"(?i)(?<![A-Za-z])(?:bearer|basic)\s+[A-Za-z0-9._~+/\-]{16,}=*"),
    ),
    (
        "a URL with a password",
        re.compile(r"(?i)(?<![A-Za-z0-9])[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"),
    ),
    ("a hex token", re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{48,}(?![0-9A-Fa-f])")),
)

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z])(?:api[_\-\s]?key|apikey|client[_\-\s]?secret|secret[_\-\s]?key|secret"
    r"|access[_\-\s]?token|auth[_\-\s]?token|token|password|passwd|pwd|private[_\-\s]?key)"
    r"\s*[:=]\s*[\"']?(?P<value>[^\s\"']+)"
)
_MIN_ASSIGNED_SECRET_LENGTH = 8

_RANDOM_RUN = re.compile(r"[A-Za-z0-9_\-+=]{32,}")
_MIN_EACH_CHARACTER_CLASS = 3
_MIN_ENTROPY_BITS = 4.2


def _assignment_value_is_secret(value: str) -> bool:
    """A secret-named key's value counts unless it is a reference or a plain lowercase word."""
    if len(value) < _MIN_ASSIGNED_SECRET_LENGTH:
        return False
    if value[0] in "$<{":
        return False
    return not value.isalpha() or not value.islower()


def _entropy(value: str) -> float:
    counts = Counter(value)
    size = len(value)
    return -sum(n / size * math.log2(n / size) for n in counts.values())


def _looks_random(run: str) -> bool:
    upper = sum(c.isupper() for c in run)
    lower = sum(c.islower() for c in run)
    digits = sum(c.isdigit() for c in run)
    return (
        min(upper, lower, digits) >= _MIN_EACH_CHARACTER_CLASS and _entropy(run) > _MIN_ENTROPY_BITS
    )


def find_secret_like(text: str) -> str | None:
    """What the text seems to contain (for example "a GitHub token"), or None if it looks safe."""
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    for match in _SECRET_ASSIGNMENT.finditer(text):
        if _assignment_value_is_secret(match.group("value")):
            return "a secret value"
    for match in _RANDOM_RUN.finditer(text):
        if _looks_random(match.group(0)):
            return "a random-looking token"
    return None
