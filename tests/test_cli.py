from decimal import Decimal

from quantgres.cli import main
from quantgres.experiments.embedding_comparison import (
    FASTEMBED_MODEL_DIMENSIONS,
    MODEL_VECTOR_INDEX_NAME,
    EmbeddingComparisonSmokeResult,
)
from quantgres.experiments.rdb_trading_ledger import (
    CashBalanceRow,
    ConstraintCheck,
    PositionRow,
    TradingLedgerSmokeResult,
)
from quantgres.experiments.time_series_candles import (
    CandlePlanSummary,
    CandleRangeSummary,
    CandleSmokeResult,
)
from quantgres.experiments.vector_memory import (
    MemorySearchResult,
    VectorMemorySmokeResult,
    VectorPlanSummary,
)
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


def test_doctor_prints_configuration(capsys):
    exit_code = main(["doctor"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Quantgres" in output
    assert "Environment: local" in output
    assert "Database URL: postgresql://quantgres:***@localhost:55432/quantgres" in output


def test_db_info_prints_runtime_metadata(monkeypatch, capsys):
    info = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(
            ExtensionStatus(name="pg_trgm", version="1.6"),
            ExtensionStatus(name="vector", version="0.8.3"),
        ),
    )
    monkeypatch.setattr("quantgres.cli.load_runtime_info", lambda: info)

    exit_code = main(["db-info"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PostgreSQL 18.4" in output
    assert "server_version_num: 180004" in output
    assert "- pg_trgm: 1.6" in output
    assert "- vector: 0.8.3" in output


def test_db_info_fails_when_required_extension_is_missing(monkeypatch, capsys):
    info = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(ExtensionStatus(name="vector", version="0.8.3"),),
    )
    monkeypatch.setattr("quantgres.cli.load_runtime_info", lambda: info)

    exit_code = main(["db-info"])

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Missing required extensions: pg_trgm" in output


def test_rdb_ledger_smoke_prints_summary(monkeypatch, capsys):
    result = TradingLedgerSmokeResult(
        positions=(
            PositionRow(
                account_code="A1",
                strategy_code="mean_reversion_v1",
                symbol="BTCUSDT",
                quantity=Decimal("0.4"),
                average_entry_price=Decimal("59970"),
                market_price=Decimal("62100"),
                unrealized_pnl=Decimal("852"),
            ),
        ),
        cash_balances=(
            CashBalanceRow(
                account_code="A1",
                currency="USDT",
                cash_balance=Decimal("76183.8100000000"),
            ),
        ),
        constraint_checks=(
            ConstraintCheck(
                name="negative order quantity",
                passed=True,
                error_type="CheckViolation",
            ),
        ),
    )
    monkeypatch.setattr("quantgres.cli.run_smoke", lambda: result)

    exit_code = main(["rdb-ledger-smoke"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "RDB Trading Ledger Smoke" in output
    assert "A1 mean_reversion_v1 BTCUSDT quantity=0.4" in output
    assert "A1 USDT cash_balance=76183.8100000000" in output
    assert "negative order quantity: passed CheckViolation" in output


def test_benchmark_rdb_ledger_prints_report_paths(monkeypatch, capsys, tmp_path):
    class Report:
        json_path = tmp_path / "report.json"
        markdown_path = tmp_path / "report.md"

    monkeypatch.setattr(
        "quantgres.cli.run_rdb_ledger_cash_balance_benchmark",
        lambda: Report(),
    )

    exit_code = main(["benchmark-rdb-ledger"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "JSON report:" in output
    assert "Markdown report:" in output


def test_time_series_candles_smoke_prints_summary(monkeypatch, capsys):
    result = CandleSmokeResult(
        summary=CandleRangeSummary(
            symbol="BTCUSDT",
            candle_count=60,
            first_ts="2026-01-01 00:00:00+00:00",
            last_ts="2026-01-01 00:59:00+00:00",
            min_low=Decimal("59995.0000000000"),
            max_high=Decimal("60010.9000000000"),
            vwap=Decimal("60003.1234567890"),
        ),
        plan=CandlePlanSummary(
            root_node_type="Aggregate",
            planning_time_ms=0.1,
            execution_time_ms=0.2,
        ),
    )
    monkeypatch.setattr("quantgres.cli.run_candle_smoke", lambda: result)

    exit_code = main(["time-series-candles-smoke"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Time-Series Candles Smoke" in output
    assert "symbol=BTCUSDT candle_count=60" in output
    assert "root_node=Aggregate" in output


def test_embedding_comparison_smoke_prints_model_summary(monkeypatch, capsys):
    plan = VectorPlanSummary(
        root_node_type="Limit",
        index_names=(MODEL_VECTOR_INDEX_NAME,),
        planning_time_ms=0.1,
        execution_time_ms=0.2,
    )
    deterministic_result = MemorySearchResult(
        source="bnb_rpc_log",
        external_id="tx-1",
        title="BNB Chain PancakeSwap swap log",
        preview="bnb chain pancakeswap swap rpc log",
        cosine_similarity=0.9,
    )
    model_result = MemorySearchResult(
        source="bnb_rpc_log",
        external_id="tx-1",
        title="BNB Chain PancakeSwap swap log",
        preview="bnb chain pancakeswap swap rpc log",
        cosine_similarity=0.8,
    )
    result = EmbeddingComparisonSmokeResult(
        vector_projection=VectorMemorySmokeResult(
            projected_chunks=1,
            total_chunks=1,
            query_text="pancakeswap swap bnb chain",
            results=(deterministic_result,),
            plan=plan,
        ),
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dimensions=FASTEMBED_MODEL_DIMENSIONS,
        projected_model_chunks=1,
        total_model_chunks=1,
        query_text="pancakeswap swap bnb chain",
        deterministic_results=(deterministic_result,),
        model_results=(model_result,),
        top_overlap_count=1,
        plan=plan,
    )
    monkeypatch.setattr("quantgres.cli.run_embedding_comparison_smoke", lambda **_: result)

    exit_code = main(["embedding-comparison-smoke", "--source-limit", "1", "--limit", "1"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Embedding Comparison Smoke" in output
    assert "Model: BAAI/bge-small-en-v1.5" in output
    assert "Top overlap: 1/1 deterministic results" in output
    assert MODEL_VECTOR_INDEX_NAME in output
