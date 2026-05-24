# System Flow

MarketData → Features → StrategySignal → ScoredSignal → Execution

---

# Rules

## run_strategies
- pure function
- no DB
- no external APIs

## calculate_features
- must use only market data
- no external calls

## execution
- must use config
- no hardcoded values