# Next Steps for Crypto Quant Bot

## Immediate Priority (P2 Completion)

1. Exchange Data Adapter (CCXT integration)
2. Database + Repository Layer
3. Pipeline / Scheduler
4. Paper Trading Engine
5. Portfolio-Level Risk
6. Dashboard (Streamlit)
7. Reconciliation & Kill Switch

## File Creation Needs

### Core Components
- `app/market/exchange_adapter.py` - CCXT integration
- `app/data/database.py` - SQLite/PostgreSQL repository
- `app/data/models.py` - Data models
- `app/pipeline/scheduler.py` - APScheduler integration
- `app/paper/engine.py` - Paper trading engine
- `app/portfolio/risk.py` - Portfolio-level risk management
- `app/dashboard/app.py` - Streamlit dashboard
- `app/execution/reconciliation.py` - Order reconciliation
- `app/execution/kill_switch.py` - Emergency stop mechanism

### Configuration
- `config/exchange_config.py` - Exchange API keys and settings
- `config/database_config.py` - Database connection settings
- `config/scheduler_config.py` - Scan intervals and schedule
- `config/paper_trading_config.py` - Paper trading settings

### Additional Indicators
- `app/indicators/volume.py` - Volume-based indicators
- `app/indicators/volatility.py` - Volatility indicators
- `app/indicators/momentum.py` - Momentum indicators

## Implementation Order

### Phase 1: Data Infrastructure
1. Exchange adapter (Binance only for start)
2. Database models and repository
3. Basic scheduler

### Phase 2: Core Engine
1. Paper trading engine
2. Portfolio risk management
3. Signal generation pipeline

### Phase 3: Monitoring & Control
1. Dashboard
2. Reconciliation system
3. Kill switch

### Phase 4: Enhancement
1. Additional exchanges
2. More sophisticated indicators
3. Advanced risk features

## Testing Requirements

Each component needs:
- Unit tests
- Integration tests (where applicable)
- Mock data for testing