from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common import (
    _HTTP_METRIC_LOCK,
    _HTTP_METRIC_VALUES,
    _record_http_metric,
    _render_http_metrics,
)

from identity import IdentityHandler


class IdentityMetricsTests(unittest.TestCase):
    def test_http_metrics_use_bounded_route_template_labels(self):
        with _HTTP_METRIC_LOCK:
            _HTTP_METRIC_VALUES.clear()

        _record_http_metric("GET", "/v1/accounts/{accountId}", 200, 12)
        output = _render_http_metrics()

        self.assertIn(
            'myota_http_server_requests_total{http_request_method="GET",'
            'http_route="/v1/accounts/{accountId}",http_response_status_code="200"} 1',
            output,
        )
        self.assertIn(
            "myota_http_server_duration_milliseconds_bucket{"
            'http_request_method="GET",http_route="/v1/accounts/{accountId}",'
            'http_response_status_code="200",le="25"} 1',
            output,
        )
        self.assertNotIn("private-account-id", output)

    def test_metrics_are_aggregated_and_bounded(self):
        fake_store = SimpleNamespace(
            items={
                "private-account-id": {
                    "email": "private@example.invalid",
                    "participationType": "OPERATOR",
                    "callsigns": [{"callsign": "PRIVATE"}],
                },
                "another-private-id": {
                    "email": "another@example.invalid",
                    "participationType": "SWL",
                    "callsigns": [],
                },
            },
            data={
                "credentials": {
                    "private-account-id": {
                        "lockedUntil": "2999-01-01T00:00:00Z"
                    },
                    "another-private-id": {"lockedUntil": None},
                },
                "roles": {
                    "role-1": {"validTo": None},
                    "role-2": {"validTo": "2026-01-01T00:00:00Z"},
                },
                "securityEvents": {"event-1": {}, "event-2": {}},
            },
        )

        with patch.object(IdentityHandler, "store", fake_store):
            output = IdentityHandler.metrics_text()

        self.assertIn(
            'myota_identity_users{participation_type="OPERATOR"} 1', output
        )
        self.assertIn(
            'myota_identity_users{participation_type="SWL"} 1', output
        )
        self.assertIn("myota_identity_callsigns 1", output)
        self.assertIn("myota_identity_roles 1", output)
        self.assertIn("myota_identity_security_events 2", output)
        self.assertIn("myota_identity_locked_accounts 1", output)
        self.assertNotIn("private@example.invalid", output)
        self.assertNotIn("PRIVATE", output)
        self.assertNotIn("private-account-id", output)


if __name__ == "__main__":
    unittest.main()
