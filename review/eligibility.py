from dispatch.evidence import IntervalEvidence
from review.storage import load_current_reviews, replace_effective_reviews


def apply_review_eligibility(connection, starting_ledger, target_ledger, evidence: IntervalEvidence):
    """Apply validated interval evidence inside the receipt transaction."""
    existing = load_current_reviews(connection, starting_ledger.day, starting_ledger.issue)
    continued = {key.row_id: existing[key.row_id] for key in evidence.continuous
                 if key.row_id in existing}
    replace_effective_reviews(connection, target_ledger.day, target_ledger.issue, continued)
