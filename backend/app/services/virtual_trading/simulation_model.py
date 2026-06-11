from __future__ import annotations

from app.schemas.trade import VirtualSimulationCapability, VirtualSimulationModelInfo

MVP_CAPABILITY_CODES = [
    "orderbook_depth_simulation",
    "spread_check",
    "slippage_calculation",
    "partial_fill",
    "max_executable_size",
    "liquidity_score",
    "execution_realism_check",
]

ADVANCED_ACTIVE_CAPABILITY_CODES = [
    "impact_decay",
]

ADVANCED_PLANNED_CAPABILITY_CODES = [
    "queue_position_limit_orders",
    "dynamic_liquidity_replenishment",
    "maker_taker_fee_logic",
    "funding",
    "cross_exchange_liquidity_comparison",
    "fake_liquidity_detection",
    "spoofing_detection",
]

PRO_PLANNED_CAPABILITY_CODES = [
    "agent_based_market_simulator",
    "microstructure_model",
    "probabilistic_fill_model",
    "monte_carlo_execution_simulation",
    "historical_replay_synthetic_impact",
]


_CAPABILITIES = {
    "orderbook_depth_simulation": VirtualSimulationCapability(
        code="orderbook_depth_simulation",
        name="Orderbook depth simulation",
        tier="mvp",
        status="active",
        description="Walks available book levels or depth metrics to estimate executable notional.",
    ),
    "spread_check": VirtualSimulationCapability(
        code="spread_check",
        name="Spread check",
        tier="mvp",
        status="active",
        description="Scores poor virtual market-order execution when spread is too wide.",
    ),
    "slippage_calculation": VirtualSimulationCapability(
        code="slippage_calculation",
        name="Slippage calculation",
        tier="mvp",
        status="active",
        description="Calculates entry and exit slippage from book walk, spread, and impact pressure.",
    ),
    "partial_fill": VirtualSimulationCapability(
        code="partial_fill",
        name="Partial fill",
        tier="mvp",
        status="active",
        description="Keeps filled and unfilled notional when available liquidity is insufficient.",
    ),
    "max_executable_size": VirtualSimulationCapability(
        code="max_executable_size",
        name="Max executable size",
        tier="mvp",
        status="active",
        description="Suggests realistic max virtual size when simulated execution quality is poor.",
    ),
    "liquidity_score": VirtualSimulationCapability(
        code="liquidity_score",
        name="Liquidity score",
        tier="mvp",
        status="active",
        description="Scores spread, depth, volume, and average trade size against requested position size.",
    ),
    "execution_realism_check": VirtualSimulationCapability(
        code="execution_realism_check",
        name="Execution realism check",
        tier="mvp",
        status="active",
        description="Flags unrealistic virtual execution without deciding whether entry is allowed.",
    ),
    "impact_decay": VirtualSimulationCapability(
        code="impact_decay",
        name="Impact decay",
        tier="advanced",
        status="active",
        description="Builds a private simulated price path with exponential decay for the position.",
    ),
    "queue_position_limit_orders": VirtualSimulationCapability(
        code="queue_position_limit_orders",
        name="Queue position for limit orders",
        tier="advanced",
        status="planned",
        description="Models whether a limit order was actually ahead in the book queue.",
    ),
    "dynamic_liquidity_replenishment": VirtualSimulationCapability(
        code="dynamic_liquidity_replenishment",
        name="Dynamic liquidity replenishment",
        tier="advanced",
        status="planned",
        description="Models liquidity returning after our order consumes book levels.",
    ),
    "maker_taker_fee_logic": VirtualSimulationCapability(
        code="maker_taker_fee_logic",
        name="Maker/taker fee logic",
        tier="advanced",
        status="planned",
        description="Applies fee schedules by order type, venue, and execution role.",
    ),
    "funding": VirtualSimulationCapability(
        code="funding",
        name="Funding",
        tier="advanced",
        status="planned",
        description="Applies perpetual funding payments to virtual positions.",
    ),
    "cross_exchange_liquidity_comparison": VirtualSimulationCapability(
        code="cross_exchange_liquidity_comparison",
        name="Cross-exchange liquidity comparison",
        tier="advanced",
        status="planned",
        description="Compares execution quality across exchanges before confirming a trade.",
    ),
    "fake_liquidity_detection": VirtualSimulationCapability(
        code="fake_liquidity_detection",
        name="Fake liquidity detection",
        tier="advanced",
        status="planned",
        description="Flags book liquidity that repeatedly disappears before execution.",
    ),
    "spoofing_detection": VirtualSimulationCapability(
        code="spoofing_detection",
        name="Spoofing detection",
        tier="advanced",
        status="planned",
        description="Detects manipulative book behavior around signal/entry time.",
    ),
    "agent_based_market_simulator": VirtualSimulationCapability(
        code="agent_based_market_simulator",
        name="Agent-based market simulator",
        tier="pro",
        status="planned",
        description="Simulates independent market participants reacting to impact.",
    ),
    "microstructure_model": VirtualSimulationCapability(
        code="microstructure_model",
        name="Microstructure model",
        tier="pro",
        status="planned",
        description="Models order flow, book events, and short-horizon price formation.",
    ),
    "probabilistic_fill_model": VirtualSimulationCapability(
        code="probabilistic_fill_model",
        name="Probabilistic fill model",
        tier="pro",
        status="planned",
        description="Estimates a distribution of fill outcomes instead of a single deterministic fill.",
    ),
    "monte_carlo_execution_simulation": VirtualSimulationCapability(
        code="monte_carlo_execution_simulation",
        name="Monte Carlo execution simulation",
        tier="pro",
        status="planned",
        description="Runs repeated execution scenarios to estimate risk bands.",
    ),
    "historical_replay_synthetic_impact": VirtualSimulationCapability(
        code="historical_replay_synthetic_impact",
        name="Historical replay with synthetic impact",
        tier="pro",
        status="planned",
        description="Replays historical market data while injecting private order impact.",
    ),
}


def capability_codes_for_report(*, impact_aware: bool, has_simulated_path: bool) -> list[str]:
    codes = list(MVP_CAPABILITY_CODES)
    if impact_aware and has_simulated_path:
        codes.extend(ADVANCED_ACTIVE_CAPABILITY_CODES)
    return codes


def planned_capability_codes_for_report() -> list[str]:
    return [*ADVANCED_PLANNED_CAPABILITY_CODES, *PRO_PLANNED_CAPABILITY_CODES]


def simulation_tier_for_report(*, has_simulated_path: bool) -> str:
    return "advanced" if has_simulated_path else "mvp"


def get_virtual_simulation_model_info() -> VirtualSimulationModelInfo:
    active_codes = [*MVP_CAPABILITY_CODES, *ADVANCED_ACTIVE_CAPABILITY_CODES]
    planned_codes = planned_capability_codes_for_report()
    return VirtualSimulationModelInfo(
        current_tier="advanced",
        active_capabilities=[_CAPABILITIES[code] for code in active_codes],
        planned_capabilities=[_CAPABILITIES[code] for code in planned_codes],
        data_boundary=(
            "Global market candles/orderbook data stay immutable; private simulated impact "
            "is stored only inside the virtual execution snapshot for a specific position."
        ),
        notes=[
            "MVP simulation quality is active for virtual depth, spread, slippage, partial fills, max size, liquidity score, and realism warnings.",
            "Advanced impact decay is active for private virtual position paths.",
            "Advanced limit-order queueing, replenishment, fees, funding, cross-exchange checks, fake liquidity, spoofing, and Pro simulators are planned.",
        ],
    )
