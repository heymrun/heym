import unittest

from app.models.schemas import LLMModel


class CredentialsModelsContextWindowTests(unittest.TestCase):
    def test_known_models_get_context_window_via_substring_match(self) -> None:
        from app.services.context_compressor import KNOWN_LIMITS

        models = [
            LLMModel(id="gpt-4o-mini", name="GPT-4o mini"),
            LLMModel(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet"),
            LLMModel(id="unknown-model-xyz", name="Unknown"),
        ]
        for m in models:
            model_lower = m.id.lower()
            for key, limit in KNOWN_LIMITS.items():
                if key in model_lower:
                    m.context_window = limit
                    break

        self.assertEqual(models[0].context_window, 128_000)
        self.assertEqual(models[1].context_window, 200_000)
        self.assertIsNone(models[2].context_window)
