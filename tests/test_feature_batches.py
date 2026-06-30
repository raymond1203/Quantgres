import hashlib
from decimal import Decimal

from quantgres.experiments.feature_batches import (
    build_batch_config,
    build_batch_id,
    build_code_fingerprint,
    build_dependency_fingerprint,
    build_runtime_fingerprint,
    canonical_json_hash,
    runtime_hash_material,
    summarize_plan,
)
from quantgres.experiments.feature_store import FeatureSourceRow
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


def source_row(close_price: str) -> FeatureSourceRow:
    return FeatureSourceRow(
        symbol="BTCUSDT",
        event_ts="2026-01-01T00:00:00Z",
        feature_ts="2026-01-01T00:01:00Z",
        close_price=Decimal(close_price),
        previous_close_price=None,
        return_bps=None,
        rolling_5_return_bps=None,
        volume=Decimal("1"),
        quote_volume=Decimal("2"),
        swap_count=0,
        refreshed_at="2026-01-01T00:02:00Z",
        candle_source="binance_spot_klines",
    )


def test_build_batch_id_changes_when_source_rows_change():
    left = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(source_row("10"),),
    )
    right = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(source_row("11"),),
    )

    assert left != right


def test_canonical_json_hash_is_stable_for_key_order():
    left = canonical_json_hash({"b": 2, "a": 1})
    right = canonical_json_hash({"a": 1, "b": 2})

    assert left == right


def test_build_batch_id_changes_when_config_or_code_hash_changes():
    row = source_row("10")

    left = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        config_hash="config-a",
        code_hash="code-a",
    )
    right = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        config_hash="config-b",
        code_hash="code-a",
    )
    other = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        config_hash="config-a",
        code_hash="code-b",
    )

    assert left != right
    assert left != other


def test_build_batch_id_changes_when_dependency_or_runtime_hash_changes():
    row = source_row("10")

    left = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        dependency_hash="dependency-a",
        runtime_hash="runtime-a",
    )
    dependency_changed = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        dependency_hash="dependency-b",
        runtime_hash="runtime-a",
    )
    runtime_changed = build_batch_id(
        feature_set="market_return_v1",
        run_key="default",
        rows=(row,),
        dependency_hash="dependency-a",
        runtime_hash="runtime-b",
    )

    assert left != dependency_changed
    assert left != runtime_changed


def test_build_batch_config_normalizes_symbol():
    config = build_batch_config(
        symbol="btcusdt",
        feature_set="market_return_v1",
        run_key="default",
        binance_limit=500,
        source_limit=50,
    )

    assert config["symbol"] == "BTCUSDT"


def test_build_code_fingerprint_hashes_file_content(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.sql"
    first.write_text("print('a')\n", encoding="utf-8")
    second.write_text("SELECT 1;\n", encoding="utf-8")

    fingerprint = build_code_fingerprint((first, second))

    assert len(str(fingerprint["code_hash"])) == 64
    assert fingerprint["code_paths"] == [
        {
            "path": first.as_posix(),
            "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
        },
        {
            "path": second.as_posix(),
            "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
        },
    ]


def test_build_dependency_fingerprint_hashes_lock_inputs(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    pyproject.write_text("[project]\nname='q'\n", encoding="utf-8")
    lockfile.write_text("version = 1\n", encoding="utf-8")

    fingerprint = build_dependency_fingerprint((pyproject, lockfile))

    assert len(str(fingerprint["dependency_hash"])) == 64
    assert fingerprint["dependency_paths"] == [
        {
            "path": pyproject.as_posix(),
            "sha256": hashlib.sha256(pyproject.read_bytes()).hexdigest(),
        },
        {
            "path": lockfile.as_posix(),
            "sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest(),
        },
    ]


def test_build_runtime_fingerprint_sorts_extensions_and_hash_excludes_user_database():
    left = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(
            ExtensionStatus(name="vector", version="0.8.3"),
            ExtensionStatus(name="pg_trgm", version="1.6"),
        ),
    )
    right = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4",
        server_version_num=180004,
        database_name="other",
        user_name="other",
        extensions=(
            ExtensionStatus(name="pg_trgm", version="1.6"),
            ExtensionStatus(name="vector", version="0.8.3"),
        ),
    )

    assert runtime_hash_material(left) == runtime_hash_material(right)
    assert (
        build_runtime_fingerprint(left)["runtime_hash"]
        == build_runtime_fingerprint(right)["runtime_hash"]
    )


def test_summarize_plan_extracts_batch_asof_index():
    plan = [
        {
            "Plan": {
                "Node Type": "Limit",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "quant_feature_batch_items_symbol_asof_idx",
                    }
                ],
            },
            "Planning Time": 0.1,
            "Execution Time": 0.2,
        }
    ]

    summary = summarize_plan(plan)

    assert summary.root_node_type == "Limit"
    assert summary.index_names == ("quant_feature_batch_items_symbol_asof_idx",)
