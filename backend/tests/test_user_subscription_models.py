import unittest

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import CITEXT, JSONB

from app.models.user import AppUser, SubscriptionPlan, UserAuthIdentity, UserProfile, UserSubscription


class UserSubscriptionModelsTest(unittest.TestCase):
    def test_app_user_email_uses_citext(self) -> None:
        self.assertIsInstance(AppUser.__table__.c.email.type, CITEXT)

    def test_auth_identity_email_uses_citext(self) -> None:
        self.assertIsInstance(UserAuthIdentity.__table__.c.email.type, CITEXT)

    def test_jsonb_columns_match_schema(self) -> None:
        self.assertIsInstance(UserProfile.__table__.c.settings.type, JSONB)
        self.assertIsInstance(SubscriptionPlan.__table__.c.limits.type, JSONB)
        self.assertIsInstance(SubscriptionPlan.__table__.c.features.type, JSONB)

    def test_plan_price_precision_matches_migration(self) -> None:
        column_type = SubscriptionPlan.__table__.c.price_monthly.type
        self.assertIsInstance(column_type, Numeric)
        self.assertEqual(column_type.precision, 12)
        self.assertEqual(column_type.scale, 2)

    def test_subscription_status_constraint_is_present(self) -> None:
        constraint_names = {constraint.name for constraint in UserSubscription.__table__.constraints}
        self.assertIn("ck_user_subscriptions_status", constraint_names)

    def test_auth_identity_constraints_and_indexes_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in UserAuthIdentity.__table__.constraints}
        index_names = {index.name for index in UserAuthIdentity.__table__.indexes}

        self.assertIn("uq_user_auth_identities_provider_subject", constraint_names)
        self.assertIn("ck_user_auth_identities_provider_not_blank", constraint_names)
        self.assertIn("ck_user_auth_identities_provider_subject_not_blank", constraint_names)
        self.assertIn("ix_user_auth_identities_user_id", index_names)
        self.assertIn("ix_user_auth_identities_provider_subject", index_names)


if __name__ == "__main__":
    unittest.main()
