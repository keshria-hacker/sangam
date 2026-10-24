"""Risk-tier permission policy for agent tool calls (deep-read Wave 1).

Layer order, evaluated on tool + args — never on the tool name alone:

    blacklist  >  whitelist  >  tool default  (and the approval policy)

A blacklisted call is DENIED even when the caller asked for the
``automatic`` approval policy. That closes the ``automatic -> []``
escape hatch in ``api_routes/agents_routes.py``: ``automatic`` may skip
*asking*, it may never skip a *denial*. A denial always cites the rule
that fired, and destructive-bash denials carry a recovery hint, so the
model (and the user) can choose a safer command instead of retrying
the same one blindly.

The pattern tables here are the single source of truth for the ECC
guard layer: :mod:`hooks` builds its before-tool-call hooks from them,
so a rule change in one place reaches both the policy check in
``code_agent.run_agent`` and the hook check in ``ToolExecutor``.

Config-edit denylist (ECC's config-protection, ported):
linter/formatter configs are denied because agents modify configs to
make checks pass instead of fixing source. Deliberate exception, kept
from ECC: ``pyproject.toml`` is NOT protected — it also carries project
metadata, so protecting it would block legitimate project edits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Destructive-bash patterns (tool == "run_bash", arg == "command").
# Each entry: (rule_id, compiled regex, recovery hint).
# Patterns are deliberately narrow: they match destructive *targets*
# (filesystem roots, devices, the home directory), not merely the
# presence of a scary word, so `rm -rf ./build` stays allowed.
# ---------------------------------------------------------------------------

DESTRUCTIVE_BASH_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "destructive-bash/rm-root",
        re.compile(r"\brm\b[^;&|]*-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\b[^;&|]*"
                   r"(^|[\s'\"])(/|/\*|~|~/|\$HOME|\$HOME/)(\s|;|$|'|\")"),
        "Use a scoped path instead (e.g. `rm -rf ./build`) and confirm "
        "the directory listing first.",
    ),
    (
        "destructive-bash/mkfs",
        re.compile(r"\bmkfs\b"),
        "Formatting a filesystem is irreversible from the agent. "
        "Run it by hand outside Sangam if you really mean it.",
    ),
    (
        "destructive-bash/dd-device",
        re.compile(r"\bdd\b[^;&|]*\bof\s*=\s*/dev/"),
        "Writing raw bytes to a device is irreversible. Use a file "
        "target inside the workspace instead.",
    ),
    (
        "destructive-bash/device-write",
        re.compile(r">\s*/dev/[a-z]+"),
        "Redirecting output to a device is irreversible. Redirect to a "
        "workspace file instead.",
    ),
    (
        "destructive-bash/fork-bomb",
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"),
        "Fork bombs exhaust the host. Do not run process-spawning "
        "loops without a bound.",
    ),
    (
        "destructive-bash/chmod-root",
        re.compile(r"\bchmod\b[^;&|]*-R[^;&|]*\b/\b"),
        "Recursive permission changes on / break the host. Scope the "
        "change to a workspace path.",
    ),
    (
        "destructive-bash/force-push-default",
        re.compile(r"\bgit\s+push\b[^;&|]*--force\b[^;&|]*\b(main|master)\b"),
        "Force-pushing the default branch rewrites shared history. "
        "Push to a feature branch, or force-push by hand after review.",
    ),
]

# Config files the agent may not edit (matched against the basename of
# the `path` argument of write_file / edit_file). See module docstring
# for the pyproject.toml exception.
CONFIG_DENYLIST_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("config-deny/eslint", re.compile(r"^(\.eslintrc(\..*)?|eslint\.config\..*)$")),
    ("config-deny/prettier", re.compile(r"^(\.prettierrc(\..*)?|prettier\.config\..*)$")),
    ("config-deny/biome", re.compile(r"^(biome\.json.*|\.biome\.json.*)$")),
    ("config-deny/ruff", re.compile(r"^(\.?ruff\.toml)$")),
    ("config-deny/flake8", re.compile(r"^\.flake8$")),
    ("config-deny/mypy", re.compile(r"^mypy\.ini$")),
    ("config-deny/pre-commit", re.compile(r"^\.pre-commit-config\.yaml$")),
]

# Tools that ask for approval under the default policy.
DEFAULT_APPROVAL_TOOLS = frozenset(
    {"write_file", "edit_file", "run_bash", "execute_code"}
)


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of evaluating one tool call against the risk tiers."""

    decision: str  # "allow" | "ask" | "deny"
    rule_id: str | None = None
    reason: str = ""
    recovery_hint: str | None = None

    def __bool__(self) -> bool:
        return self.decision == "allow"


@dataclass
class RiskRule:
    """One blacklist or whitelist rule, matched on tool + args.

    ``arg_patterns`` maps an argument name to a regex searched in the
    string form of that argument's value. A rule matches when the tool
    matches and every arg pattern matches. ``tool="*"`` matches any tool.
    """

    rule_id: str
    tool: str = "*"
    arg_patterns: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    recovery_hint: str | None = None

    def matches(self, tool_name: str, args: dict[str, Any]) -> bool:
        if self.tool != "*" and self.tool != tool_name:
            return False
        for arg_name, pattern in self.arg_patterns.items():
            value = args.get(arg_name)
            if value is None or not re.search(pattern, str(value)):
                return False
        return True


def _default_blacklist() -> list[RiskRule]:
    rules: list[RiskRule] = []
    for rule_id, pattern, hint in DESTRUCTIVE_BASH_PATTERNS:
        rules.append(RiskRule(
            rule_id=rule_id, tool="run_bash",
            arg_patterns={"command": pattern.pattern},
            reason=f"Destructive command blocked by rule {rule_id}.",
            recovery_hint=hint,
        ))
    # Config denylist applies to the file-writing tools only (never to
    # read-only tools), matched on the path argument's basename part.
    for rule_id, pattern in CONFIG_DENYLIST_PATTERNS:
        # Strip the basename anchor: the composed pattern matches the
        # basename at the start of the string or after a "/".
        basename_pattern = pattern.pattern[1:] if pattern.pattern.startswith("^") else pattern.pattern
        for tool in ("write_file", "edit_file"):
            rules.append(RiskRule(
                rule_id=rule_id, tool=tool,
                arg_patterns={"path": r"(^|/)" + basename_pattern},
                reason=f"Editing protected config files is blocked by rule "
                       f"{rule_id}. Fix the source instead of changing the "
                       "check configuration.",
                recovery_hint="Edit the source file that fails the check, "
                              "not the linter/formatter configuration.",
            ))
    return rules


@dataclass
class RiskPolicy:
    """Blacklist > whitelist > tool default, plus the approval policy.

    ``approval_policy`` is one of "default" | "automatic" | "always_ask".
    ``require_approval`` mirrors the engine's legacy argument: None means
    the engine defaults (sensitive tools ask); a list means exactly those
    tools ask. Neither form can override a blacklist denial.
    """

    blacklist: list[RiskRule] = field(default_factory=_default_blacklist)
    whitelist: list[RiskRule] = field(default_factory=list)

    def evaluate(self, tool_name: str, args: dict[str, Any] | None,
                 approval_policy: str = "default",
                 require_approval: list[str] | None = None) -> PolicyDecision:
        args = args or {}
        for rule in self.blacklist:
            if rule.matches(tool_name, args):
                return PolicyDecision(
                    decision="deny", rule_id=rule.rule_id,
                    reason=rule.reason, recovery_hint=rule.recovery_hint,
                )
        for rule in self.whitelist:
            if rule.matches(tool_name, args):
                return PolicyDecision(
                    decision="allow", rule_id=rule.rule_id,
                    reason=f"Explicitly whitelisted by rule {rule.rule_id}.",
                )
        policy = (approval_policy or "default").strip().lower()
        if policy in ("automatic", "auto", "never"):
            # May skip asking — never skips a blacklist denial (checked
            # above). Non-blacklisted calls are allowed outright.
            return PolicyDecision(decision="allow", reason="Automatic policy.")
        if policy in ("always_ask", "ask_all", "always"):
            return PolicyDecision(decision="ask",
                                  reason="Always-ask policy: every call asks.")
        # Default policy: the legacy require_approval semantics.
        if require_approval is None:
            needs_ask = tool_name in DEFAULT_APPROVAL_TOOLS
        else:
            needs_ask = tool_name in require_approval
        if needs_ask:
            return PolicyDecision(
                decision="ask",
                reason=f"Tool {tool_name!r} requires approval by default.")
        return PolicyDecision(decision="allow",
                              reason=f"Tool {tool_name!r} is read-only by default.")


# Shared default policy used by the agent loop and the executor hooks.
DEFAULT_POLICY = RiskPolicy()
