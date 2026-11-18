"""Just-in-time user provisioning.

The first valid request from a new Supabase user creates their ``users`` row,
default categories and seed categorization rules in one database transaction.
Two simultaneous first requests are safe: ``INSERT ... ON CONFLICT DO NOTHING``
lets exactly one of them create the user; the other waits for that commit and
then reads the row.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.core.security import VerifiedClaims
from app.domain.defaults import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES, SEED_RULES
from app.models import CategorizationRule, Category, User


def get_or_provision_user(session: Session, claims: VerifiedClaims) -> User:
    existing = session.scalars(select(User).where(User.auth_subject == claims.subject)).first()
    if existing is not None:
        return existing

    if claims.email is None:
        # Sign-in is by email in this app; a token without one cannot become a user.
        raise ProblemError(
            401, "auth.email_required", "Not authenticated", "The token has no email address."
        )

    try:
        inserted_id = session.execute(
            insert(User)
            .values(auth_subject=claims.subject, email=claims.email)
            .on_conflict_do_nothing(index_elements=[User.auth_subject])
            .returning(User.id)
        ).scalar_one_or_none()
        if inserted_id is not None:
            _seed_new_user(session, inserted_id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # The only other unique key is the email: a different identity already uses it.
        raise ProblemError(
            409,
            "auth.email_in_use",
            "Email already registered",
            "Another account already uses this email address.",
        ) from exc

    user = session.scalars(select(User).where(User.auth_subject == claims.subject)).one()
    return user


def _seed_new_user(session: Session, user_id: object) -> None:
    categories: dict[str, Category] = {}
    for kind, names in (
        ("expense", DEFAULT_EXPENSE_CATEGORIES),
        ("income", DEFAULT_INCOME_CATEGORIES),
    ):
        for name in names:
            category = Category(user_id=user_id, name=name, kind=kind)
            session.add(category)
            categories[name] = category
    session.flush()
    for pattern, category_name in SEED_RULES.items():
        session.add(
            CategorizationRule(
                user_id=user_id,
                pattern=pattern,
                category_id=categories[category_name].id,
                priority=100,
                created_from="seed",
            )
        )
    session.flush()
