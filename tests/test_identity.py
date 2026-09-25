import os
import unittest
from unittest.mock import patch

from sds import identity


class VerifyIdentityTests(unittest.TestCase):
    def test_returns_false_when_not_configured(self):
        self.assertFalse(identity.verify_identity("", "runner"))
        self.assertFalse(identity.verify_identity("fingerprint", ""))

    def test_accepts_case_insensitive_user_match(self):
        with patch.dict(os.environ, {"USER": "Runner"}, clear=False):
            self.assertTrue(identity.verify_identity("fingerprint", " runner "))

    def test_rejects_different_user(self):
        with patch.dict(os.environ, {"USER": "alice"}, clear=False):
            self.assertFalse(identity.verify_identity("fingerprint", "bob"))


if __name__ == "__main__":
    unittest.main()
