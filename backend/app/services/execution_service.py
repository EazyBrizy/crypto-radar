from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealExecutionResult


class RealExecutionService:
    """Заглушка для будущего исполнения сделок на бирже.

    Реальные ордера будут проходить через Exchange Adapter Layer и Risk Guard.
    В MVP этот сервис явно сообщает, что торговое исполнение еще не подключено.
    """

    async def place_order(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RealExecutionResult:
        return RealExecutionResult(
            exchange=signal.exchange,
            symbol=signal.symbol,
            message=(
                "Реальное исполнение сделок пока не реализовано. "
                "Для MVP доступен режим virtual."
            ),
        )


real_execution_service = RealExecutionService()
