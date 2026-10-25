"""Deploy connector INTERFACE ONLY (Coolify / Quickemu are deferred).

User decision (2026-10-25, defaults approved): the Coolify/Quickemu
connector is DEFERRED — this module defines the interface, the
settings keys, and the permission model, and NOTHING ELSE. No core
functionality imports or depends on it, no live Coolify/Quickemu
call is made anywhere, and no implementation is shipped here.

A future implementation must:
  * implement :class:`DeployConnector` (all methods, no partial class);
  * pass the permission check in :func:`check_deploy_permission`
    before any deploy / environment / VM action;
  * require explicit per-deploy approval when
    ``deploy_require_approval`` is on (the default);
  * be registered explicitly (never auto-discovered from the network).

Until then, :func:`list_deploy_connectors` reports every connector
as ``status: "deferred"`` and any deploy attempt raises
:class:`DeployDeferredError`. That is the honest state, not a mock
that pretends to deploy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeployDeferredError(NotImplementedError):
    """Raised by any deploy action while the connector is deferred."""


class DeployPermission(str, Enum):
    VIEW = "deploy.view"          # list connectors + deployment status
    DEPLOY = "deploy.deploy"      # one-click deploy of a generated app
    MANAGE_ENV = "deploy.manage_env"  # environment / SSL / proxy settings
    LAUNCH_VM = "deploy.launch_vm"    # VM/sandbox launch (Quickemu)
    VIEW_LOGS = "deploy.view_logs"


# Single-user Sangam: the owner holds every permission; a paired LAN
# device (see lan_pairing) holds NONE of these by default and must be
# granted them explicitly per device. This table is the permission
# model — a future multi-device grant store must consult it.
DEFAULT_GRANTS: dict[str, set[DeployPermission]] = {
    "owner": set(DeployPermission),
    "lan_device": set(),
}

DEPLOY_SETTINGS = [
    # (name, label, description, default, section)
    ("deploy_coolify_enabled", "Coolify connector",
     "Enable the (deferred) Coolify deploy connector. Off until the "
     "connector is implemented; enabling it alone deploys nothing.",
     False, "Deploy"),
    ("deploy_coolify_url", "Coolify instance URL",
     "Base URL of the Coolify instance to deploy to, when implemented. "
     "Empty means unconfigured.", "", "Deploy"),
    ("deploy_quickemu_enabled", "Quickemu VM / sandbox launch",
     "Enable the (deferred) Quickemu VM/sandbox launcher (developer "
     "mode only when implemented). Off by default.", False, "Deploy"),
    ("deploy_require_approval", "Require approval per deploy",
     "Every deploy or VM launch must be explicitly approved before it "
     "runs, even for the owner.", True, "Deploy"),
    ("deploy_sandbox_mode", "Sandbox mode for generated apps",
     "How generated apps run before deploy: 'preview' (sandboxed "
     "preview only) or 'isolated' (isolated VM/sandbox when available).",
     "preview", "Deploy"),
]


@dataclass
class DeployTarget:
    name: str
    kind: str  # "coolify" | "quickemu"
    url: str = ""
    status: str = "deferred"


@dataclass
class AppPackage:
    """A generated app ready to deploy: files + entrypoint, no secrets."""
    name: str
    files: dict[str, str] = field(default_factory=dict)
    entrypoint: str = "index.html"
    port: int = 8000


@dataclass
class DeployResult:
    target: str
    url: str = ""
    status: str = "deferred"
    detail: str = ""


class DeployConnector:
    """Interface a real deploy connector must implement. Not usable
    directly: instantiating the base class and calling any action
    raises DeployDeferredError."""

    kind: str = "base"

    def list_targets(self) -> list[DeployTarget]:
        raise DeployDeferredError(
            "deploy connector is deferred: no Coolify/Quickemu "
            "implementation is shipped")

    def deploy(self, package: AppPackage, target: str) -> DeployResult:
        raise DeployDeferredError(
            "deploy connector is deferred: no Coolify/Quickemu "
            "implementation is shipped")

    def launch_vm(self, image: str, **kwargs) -> DeployResult:
        raise DeployDeferredError(
            "deploy connector is deferred: no Coolify/Quickemu "
            "implementation is shipped")


def check_deploy_permission(role: str, permission: DeployPermission) -> bool:
    return permission in DEFAULT_GRANTS.get(role, set())


def list_deploy_connectors() -> list[dict]:
    return [
        {"kind": "coolify", "label": "Coolify (one-click app deploy)",
         "status": "deferred",
         "detail": "Interface only; no live Coolify dependency."},
        {"kind": "quickemu", "label": "Quickemu (VM / sandbox launch)",
         "status": "deferred",
         "detail": "Interface only; no live Quickemu dependency."},
    ]
