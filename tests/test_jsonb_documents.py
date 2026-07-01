from quantgres.experiments.jsonb_documents import (
    BNB_CONTAINMENT_FILTER,
    BNB_CONTAINMENT_QUERY,
    INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL,
)


def test_bnb_swap_corpus_document_sql_uses_enriched_event_time_source():
    assert "'bnb_swap_corpus'" in INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL
    assert "block_timestamp IS NOT NULL" in INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL
    assert "'pair_address', pair_address" in INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL
    assert "'transaction_hash', transaction_hash" in INSERT_BNB_SWAP_CORPUS_DOCUMENTS_SQL
    assert "source = 'bnb_swap_corpus'" in BNB_CONTAINMENT_QUERY
    assert tuple(BNB_CONTAINMENT_FILTER) == ("pair_address",)
