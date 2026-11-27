"""Request-local authenticated actor context for audit and row-scope enforcement."""
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Literal
from uuid import UUID


@dataclass(frozen=True)
class ActorContext:
    actor_type: Literal["ADMIN", "GOOGLE"]
    user_id: UUID | None = None
    admin_username: str | None = None
    company_id: UUID | None = None
    membership_id: UUID | None = None
    data_scope: Literal["ALL", "OWN"] | None = None
    permission_code: str | None = None


current_actor: ContextVar[ActorContext | None] = ContextVar(
    "gold_erp_current_actor",
    default=None,
)


@contextmanager
def bind_actor(actor: ActorContext) -> Iterator[None]:
    token: Token = current_actor.set(actor)
    try:
        yield
    finally:
        current_actor.reset(token)
