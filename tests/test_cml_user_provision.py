# File Chain (see DEVELOPER.md):
# Purpose: TG-192 — unit tests for per-ticket CML user provisioning.
# Blast Radius: Test-only.

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml_user import (  # noqa: E402
    LAB_PERMISSIONS,
    main,
    provision_cml_user,
    resolve_password,
    revoke_cml_user,
)

LAB_ID = "2be6f617-cf45-4bff-8970-2c9f28ac01d3"
USER_ID = "90f84e38-a71c-4d57-8d90-00fa8a197385"


class _FakeUserManagement:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_user(self, username, pwd, **kwargs):
        self.created.append((username, pwd, kwargs))
        return {"id": USER_ID, "username": username, **kwargs}

    def user_id(self, username):
        return USER_ID

    def delete_user(self, user_id):
        self.deleted.append(user_id)


class TestCmlUserProvision(unittest.TestCase):
    def test_resolve_password_from_env(self):
        with patch.dict("os.environ", {"CUSTOMER_CML_PASSWORD": "from-env-secret"}):
            self.assertEqual(resolve_password(password_env="CUSTOMER_CML_PASSWORD"), "from-env-secret")

    def test_resolve_password_explicit(self):
        self.assertEqual(resolve_password("explicit"), "explicit")

    def test_resolve_password_csprng_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            pwd = resolve_password()
        self.assertGreaterEqual(len(pwd), 16)

    def test_provision_creates_scoped_user(self):
        um = _FakeUserManagement()
        client = MagicMock(user_management=um)
        result = provision_cml_user(
            lab_id=LAB_ID,
            username="tg-TG-192-smoke",
            password="test-pass",
            client=client,
        )
        self.assertEqual(result["username"], "tg-TG-192-smoke")
        self.assertEqual(result["user_id"], USER_ID)
        self.assertFalse(result["admin"])
        self.assertEqual(result["permissions"], list(LAB_PERMISSIONS))
        self.assertEqual(len(um.created), 1)
        username, pwd, kwargs = um.created[0]
        self.assertEqual(username, "tg-TG-192-smoke")
        self.assertEqual(pwd, "test-pass")
        self.assertFalse(kwargs["admin"])
        self.assertEqual(
            kwargs["associations"],
            [{"id": LAB_ID, "permissions": list(LAB_PERMISSIONS)}],
        )

    def test_provision_dry_run(self):
        um = _FakeUserManagement()
        client = MagicMock(user_management=um)
        result = provision_cml_user(
            lab_id=LAB_ID,
            username="tg-TG-192-demo",
            password="dry-pass",
            dry_run=True,
            client=client,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(um.created), 0)

    def test_revoke_deletes_user(self):
        um = _FakeUserManagement()
        client = MagicMock(user_management=um)
        result = revoke_cml_user(username="tg-TG-192-smoke", client=client)
        self.assertTrue(result["revoked"])
        self.assertEqual(result["user_id"], USER_ID)
        self.assertEqual(um.deleted, [USER_ID])

    def test_cli_provision_dry_run_exit_zero(self):
        with patch("topogen.cml_user.provision_cml_user") as mock_prov:
            mock_prov.return_value = {
                "username": "tg-TG-192",
                "lab_id": LAB_ID,
                "admin": False,
                "permissions": list(LAB_PERMISSIONS),
                "password": "secret",
            }
            rc = main(
                [
                    "--lab-id",
                    LAB_ID,
                    "--username",
                    "tg-TG-192",
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 0)
        mock_prov.assert_called_once()

    def test_cli_revoke_exit_zero(self):
        with patch("topogen.cml_user.revoke_cml_user") as mock_rev:
            mock_rev.return_value = {"username": "tg-TG-192", "revoked": True}
            rc = main(["--username", "tg-TG-192", "--revoke", "--dry-run"])
        self.assertEqual(rc, 0)
        mock_rev.assert_called_once()


if __name__ == "__main__":
    unittest.main()
