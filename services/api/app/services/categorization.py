"""Rule-based categorization (handoff section 10).

A rule maps a merchant word or phrase (e.g. "SWIGGY") to one of the user's
categories. Rules only fill in a category nobody has chosen yet
(``category_source = 'none'``); they never override the user's own choice.

Which rule wins when several match:
1. user rules beat seed rules,
2. then the lower ``priority`` number,
3. then the longer (more specific) pattern.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.domain.merchant import contains_word, merchant_tokens, normalize_merchant
from app.models import CategorizationRule, Category, Transaction
from app.services.ledger import apply_change

USER_RULE_PRIORITY = 10
SEED_RULE_PRIORITY = 100
_KIND_FOR_TYPE = {"expense": "expense", "refund": "expense", "income": "income"}


@dataclass(frozen=True)
class Rule:
    pattern: str
    category_id: UUID
    category_kind: str
    priority: int
    from_user: bool


def active_rules(session: Session, user_id: UUID) -> list[Rule]:
    """The user's rules whose category is still active, best first."""
    rows = session.execute(
        select(CategorizationRule, Category.kind)
        .join(
            Category,
            (Category.id == CategorizationRule.category_id)
            & (Category.user_id == CategorizationRule.user_id),
        )
        .where(CategorizationRule.user_id == user_id, Category.is_archived.is_(False))
    ).all()
    rules = [
        Rule(
            pattern=rule.pattern,
            category_id=rule.category_id,
            category_kind=kind,
            priority=rule.priority,
            from_user=rule.created_from == "user",
        )
        for rule, kind in rows
    ]
    return sorted(rules, key=lambda r: (not r.from_user, r.priority, -len(r.pattern), r.pattern))


def match_rule(rules: list[Rule], description: str | None, transaction_type: str) -> Rule | None:
    """The best rule for a description, among rules whose category fits the type."""
    kind = _KIND_FOR_TYPE.get(transaction_type)
    if kind is None:
        return None  # transfers never get a category
    merchant = " ".join(merchant_tokens(description))
    if not merchant:
        return None
    for rule in rules:
        if rule.category_kind == kind and contains_word(merchant, rule.pattern):
            return rule
    return None


def categorize_transactions(
    session: Session, user_id: UUID, transactions: list[Transaction]
) -> int:
    """Apply rules to rows nobody has categorized. Returns how many got a category.
    Idempotent: a second run finds nothing left to do. Does not commit."""
    rules = active_rules(session, user_id)
    changed = 0
    for tx in transactions:
        if tx.category_source != "none" or tx.category_id is not None:
            continue
        rule = match_rule(rules, tx.description, tx.transaction_type)
        if rule is None:
            continue
        apply_change(
            session,
            tx,
            {"category_id": rule.category_id, "category_source": "rule"},
            event_type="categorized_by_rule",
            actor="rule",
            reason=f"rule {rule.pattern}",
        )
        changed += 1
    return changed


def categorize_import(session: Session, user_id: UUID, import_id: UUID) -> int:
    rows = list(
        session.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.import_id == import_id,
                Transaction.category_source == "none",
            )
            .order_by(Transaction.id)
            .with_for_update(skip_locked=True)
        )
    )
    return categorize_transactions(session, user_id, rows)


def create_user_rule(
    session: Session, user_id: UUID, description: str | None, category_id: UUID
) -> str:
    """Remember "this merchant -> this category" for future transactions. A user rule
    for the same pattern replaces the earlier one (seed or user). Does not commit."""
    pattern = normalize_merchant(description)
    if not pattern:
        raise ProblemError(
            422,
            "rule.no_merchant",
            "No merchant name",
            "This transaction's description has no merchant name to make a rule from.",
        )
    session.execute(
        insert(CategorizationRule)
        .values(
            user_id=user_id,
            pattern=pattern,
            category_id=category_id,
            priority=USER_RULE_PRIORITY,
            created_from="user",
        )
        .on_conflict_do_update(
            index_elements=[CategorizationRule.user_id, CategorizationRule.pattern],
            set_={
                "category_id": category_id,
                "priority": USER_RULE_PRIORITY,
                "created_from": "user",
            },
        )
    )
    return pattern
