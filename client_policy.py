"""Client-mode policy constants.

This file is protected by INTEGRITY.lock in exported signal-client artifacts.
"""

CLIENT_MODE = True
AUTHOR_PRIVATE_DATA_ALLOWED = False
ALLOWED_OUTPUTS = ("local_audit_markdown", "anonymized_run_report")
FORBIDDEN_ACTIONS = (
    "modify_core_logic",
    "change_rules_without_integrity_violation",
    "read_author_private_db",
    "create_trades",
    "send_without_share_consent",
)
