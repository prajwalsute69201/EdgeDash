from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from edgedash.config import Config


@dataclass
class AgentResult:
    agent: str
    status: str
    records_touched: int
    notes: str


@runtime_checkable
class Agent(Protocol):
    name: str

    def run(
        self,
        config: Config,
        goal: str | None = None,
        stop_conditions: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        ...

