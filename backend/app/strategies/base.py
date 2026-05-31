from typing import Any, Mapping, Protocol

from app.schemas.market import Features
from app.schemas.signal import StrategySignal


class Strategy(Protocol):
    name: str
    version: str
    required_data: list[str]

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        ...
