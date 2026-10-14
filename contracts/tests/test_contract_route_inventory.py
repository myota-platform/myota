from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_contract_phase0 import service_routes  # noqa: E402


class ServiceRouteInventoryTests(unittest.TestCase):
    def test_test_fixtures_are_not_counted_as_live_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "identity.py").write_text(
                'routes = {("GET", "/v1/identity/me"): handler}\n',
                encoding="utf-8",
            )
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_legacy_aliases.py").write_text(
                'routes = {("POST", "/v1/identity/legacy"): handler}\n',
                encoding="utf-8",
            )

            routes = service_routes(root)

        self.assertEqual(
            [(route["method"], route["path"]) for route in routes],
            [("GET", "/v1/identity/me")],
        )


if __name__ == "__main__":
    unittest.main()
