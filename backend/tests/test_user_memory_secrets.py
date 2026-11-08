"""The memory secret guard refuses credential shapes and passes ordinary text."""

import unittest

from app.services.user_memory_secrets import find_secret_like

SECRET_SAMPLES: dict[str, str] = {
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "openai key": "my key is " + "sk-" + "proj-" + "Ab1" * 10,
    "anthropic key": "sk-" + "ant-" + "Xy9" * 10,
    "github token": "gh" + "p_" + "Ab1" * 12,
    "github pat": "github" + "_pat_" + "Ab1" * 12,
    "gitlab token": "gl" + "pat-" + "Ab1" * 8,
    "slack token": "xo" + "xb-" + "1234-5678-abcdEFGH",
    "aws key": "AKIA" + "IOSFODNN7EXAMPLE",
    "google key": "AI" + "za" + "Sy" + "A1b2C3d4" * 4 + "x",
    "jwt": "eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + "." + "SflKxwRJSMeK",
    "bearer header": "Authorization: Bearer " + "abc123DEF456ghi789",
    "url with password": "postgres://heym:" + "s3cretpass" + "@db.internal:5432/heym",
    "api_key assignment": "api_key=" + "abcdef123456",
    "env token assignment": "MY_SERVICE_TOKEN: " + "q9w8e7r6",
    "password assignment": "password = " + "hunter22",
    "hex token": "a1b2c3d4" * 8,
    "random token": "Zx8Qp2Lm4Rt7Vb9Nc3Hd6Jk1Ws5Ye0Ua",
}

SAFE_SAMPLES: dict[str, str] = {
    "preference": "Always answer in English and keep replies short.",
    "decision": "The sales team uses HubSpot as its CRM; weekly report goes out Monday 09:00.",
    "uuid": "Main workflow id: 3f2b6c1e-9a4d-4e8f-b7c2-1d5e6f7a8b9c",
    "plain url": "Docs live at https://heym.run/docs/getting-started/quick-start",
    "token mentioned": "The Slack token is stored in Credentials as Slack Bot.",
    "camel case name": "Run SendWeeklyReportToSalesTeamV2Flow on Fridays.",
    "git sha": "Released from de57bf059c91aba9cf75f095ba1285791f3ef790.",
    "expression reference": "Workflows read api_key: $vars.openai from variables.",
    "short password word": "password: required",
}


class FindSecretLikeTests(unittest.TestCase):
    def test_every_secret_shape_is_found(self) -> None:
        for label, text in SECRET_SAMPLES.items():
            with self.subTest(label):
                self.assertIsNotNone(find_secret_like(text), text)

    def test_ordinary_text_passes(self) -> None:
        for label, text in SAFE_SAMPLES.items():
            with self.subTest(label):
                self.assertIsNone(find_secret_like(text), text)

    def test_the_reason_names_the_shape(self) -> None:
        self.assertEqual(find_secret_like(SECRET_SAMPLES["github token"]), "a GitHub token")
        self.assertEqual(find_secret_like(SECRET_SAMPLES["random token"]), "a random-looking token")


if __name__ == "__main__":
    unittest.main()
