"""Service-layer errors. Phase 7 maps them to HTTP: RequestRejected -> 422, Conflict -> 409, NotFound -> 404."""


class ServiceError(Exception):
    """Base class: an expected, explainable refusal. Never a crash."""


class RequestRejected(ServiceError):
    """The request is well-formed but cannot be scored or applied as asked."""


class Conflict(ServiceError):
    """The request contradicts recorded state (idempotency mismatch, stale expected action)."""


class NotFound(ServiceError):
    """No decision exists for this order."""


class UnknownAccount(NotFound):
    """The account does not exist; accounts cannot be created live (#31, architect decision 1.3 -> 404)."""
