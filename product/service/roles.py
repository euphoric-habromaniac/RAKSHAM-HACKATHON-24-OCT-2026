"""Roles and the two-approver threshold change workflow.

Identity here is a stand-in: the API trusts X-User / X-Role headers. In a bank
deployment these come from the bank's SSO/IdP behind a gateway; the checks
below are the authorisation logic, not authentication.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


class Role(str, Enum):
    AGENT = "agent"
    ANALYST = "analyst"
    FRAUD_HEAD = "fraud_head"


@dataclass(frozen=True)
class Principal:
    user: str
    role: Role


class PermissionDenied(Exception):
    pass


class ProposalError(Exception):
    """Unknown proposal, duplicate approval, or already-applied proposal."""


def _same_person(a: str, b: str) -> bool:
    """Approver identity: ignore case and surrounding whitespace so 'Alice' and ' alice' are one person."""
    return a.strip().casefold() == b.strip().casefold()


def authorize(principal: Principal, *allowed: Role) -> Principal:
    if principal.role not in allowed:
        raise PermissionDenied(f"role '{principal.role.value}' may not do this")
    return principal


@dataclass
class Proposal:
    proposal_id: str
    layer: str
    weak: float
    strong: float
    reason: str
    proposed_by: str
    approvers: List[str] = field(default_factory=list)
    status: str = "pending"


class ThresholdChangeManager:
    """A change applies only after two distinct fraud-head users approve it.

    The proposer may be one of the two approvers, but the same user approving
    twice counts once. Only fraud_head may propose or approve; analysts and
    agents may not.
    """

    REQUIRED_APPROVERS = 2

    def __init__(self, apply: Callable[[str, float, float], None],
                 on_event: Optional[Callable[[str, Proposal], None]] = None):
        self._apply = apply
        self._on_event = on_event or (lambda _e, _p: None)
        self._proposals: Dict[str, Proposal] = {}
        self._lock = threading.Lock()

    def propose(self, who: Principal, layer: str, weak: float, strong: float, reason: str) -> Proposal:
        authorize(who, Role.FRAUD_HEAD)
        if not 0.0 < weak < strong < 1.0:
            raise ProposalError("need 0 < weak < strong < 1")
        prop = Proposal(uuid.uuid4().hex[:12], layer, weak, strong, reason, who.user)
        with self._lock:
            self._proposals[prop.proposal_id] = prop
        self._on_event("threshold_proposed", prop)
        return prop

    def approve(self, who: Principal, proposal_id: str) -> Proposal:
        authorize(who, Role.FRAUD_HEAD)
        with self._lock:
            prop = self._proposals.get(proposal_id)
            if prop is None:
                raise ProposalError("unknown proposal")
            if prop.status == "applied":
                raise ProposalError("proposal already applied")
            if any(_same_person(who.user, a) for a in prop.approvers):
                raise ProposalError("this user has already approved")
            prop.approvers.append(who.user)
            applied_now = len(prop.approvers) >= self.REQUIRED_APPROVERS
            if applied_now:
                try:
                    self._apply(prop.layer, prop.weak, prop.strong)
                except Exception:
                    prop.approvers.pop()  # a failed apply must not leave a counted approval behind
                    raise
                prop.status = "applied"
        self._on_event("threshold_applied" if applied_now else "threshold_approved", prop)
        return prop

    def get(self, proposal_id: str) -> Optional[Proposal]:
        return self._proposals.get(proposal_id)

    def all(self) -> List[Proposal]:
        return list(self._proposals.values())
