import unittest

from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import CITEXT, JSONB

from app.models.user import AppUser, SubscriptionPlan, UserProfile, UserSubscription


class UserSubscriptionModelsTest(unittest.TestCase):
    def test_app_user_email_uses_citext(self) -> None:
        self.assertIsInstance(AppUser.__table__.c.email.type, CITEXT)

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


if __name__ == "__main__":
    unittest.main()
