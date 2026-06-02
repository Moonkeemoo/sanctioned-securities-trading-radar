"""Column-name constants for interim tables. One source of truth so stages agree."""

# stage1 outputs
SANCTIONED_SECURITIES = ["isin", "ticker", "figi", "security_name", "issuer_entity_id", "source"]
SANCTIONED_ENTITIES = ["entity_id", "name", "lei", "country", "topics"]
ISIN_TO_LEI = ["isin", "lei"]
LEI_RELATIONS = ["parent_lei", "child_lei", "relation_type"]

# stage2 output
CANDIDATE_ISINS = ["isin", "issuer_lei", "root_sanctioned_lei", "path_depth", "tag"]

# stage3 output
CLASSIFIED = ["isin", "is_us", "cusip", "security_type", "trace_eligible_guess", "gap_reason"]

# stage4 output
ACTIVITY = ["isin", "signal_kind", "signal_value", "observed_period", "source_url", "fetched_at"]

TAG_DIRECT = "direct"
TAG_INDIRECT = "indirect"
