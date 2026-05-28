import unittest

from app.models.ai import SignalAIExplanation


class SignalAIExplanationModelsTest(unittest.TestCase):
    def test_signal_foreign_key_cascades_on_signal_delete(self) -> None:
        foreign_key = next(iter(SignalAIExplanation.__table__.c.signal_id.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_required_text_constraints_are_present(self) -> None:
        constraint_names = {constraint.name for constraint in SignalAIExplanation.__table__.constraints}
        self.assertIn("ck_signal_ai_explanations_model_provider_not_blank", constraint_names)
        self.assertIn("ck_signal_ai_explanations_model_name_not_blank", constraint_names)
        self.assertIn("ck_signal_ai_explanations_prompt_hash_not_blank", constraint_names)
        self.assertIn("ck_signal_ai_explanations_explanation_md_not_blank", constraint_names)

    def test_signal_and_created_at_indexes_are_present(self) -> None:
        index_names = {index.name for index in SignalAIExplanation.__table__.indexes}
        self.assertIn("ix_signal_ai_explanations_signal_id", index_names)
        self.assertIn("ix_signal_ai_explanations_created_at", index_names)


if __name__ == "__main__":
    unittest.main()
