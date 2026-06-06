"""
Custom DRF permission classes for the SMT API.

Phase 7, Task 3B introduces :class:`CanControlSimulator` — the minimal
permission gate for simulator control actions. It is intentionally tiny:
business logic stays in :mod:`apps.simulator.services.control` and the
permission class stays HTTP-aware so the service layer can keep being
called from management commands and tests without any request object.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


SIMULATOR_CONTROL_PERMISSION = "simulator.can_control_simulator"


class CanControlSimulator(BasePermission):
    """
    Allow only authenticated users who either:

    * are superusers (``is_superuser=True``), or
    * carry the ``simulator.can_control_simulator`` permission, either
      directly or via a Django ``Group``.

    The permission is declared as ``Meta.permissions`` on
    :class:`apps.simulator.models.SimulatorScenario`; assignment uses the
    standard Django admin / shell flow described in
    ``docs/simulator_usage.md``.

    The class deliberately does NOT enforce object-level checks
    (``has_object_permission``) — simulator control endpoints currently
    operate on a single resolved scenario per request, and per-scenario
    ACLs are out of scope for this task.
    """

    message = "Lietotājam nav tiesību vadīt simulatoru."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.has_perm(SIMULATOR_CONTROL_PERMISSION)


def user_can_control_simulator(user) -> bool:
    """
    Pure-Python helper mirroring :class:`CanControlSimulator` for
    callers that have a ``User`` object but no DRF request — for
    example, ``simulator_status_view`` adds a ``can_control`` flag to
    its response so the dashboard can disable buttons preemptively.

    Anonymous / ``None`` users return ``False``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.has_perm(SIMULATOR_CONTROL_PERMISSION)
