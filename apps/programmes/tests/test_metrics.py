from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common import (
    _HTTP_METRIC_LOCK,
    _HTTP_METRIC_VALUES,
    _record_http_metric,
    _render_http_metrics,
)

from programmes import ProgrammeHandler


class ProgrammeMetricsTests(unittest.TestCase):
    def test_http_metrics_use_bounded_route_template_labels(self):
        with _HTTP_METRIC_LOCK:
            _HTTP_METRIC_VALUES.clear()

        _record_http_metric("GET", "/v1/programmes/{slug}", 200, 12)
        output = _render_http_metrics()

        self.assertIn(
            'myota_http_server_requests_total{http_request_method="GET",'
            'http_route="/v1/programmes/{slug}",http_response_status_code="200"} 1',
            output,
        )
        self.assertIn(
            "myota_http_server_duration_milliseconds_bucket{"
            'http_request_method="GET",http_route="/v1/programmes/{slug}",'
            'http_response_status_code="200",le="25"} 1',
            output,
        )
        self.assertNotIn("private-programme-slug", output)

    def test_metrics_are_aggregate_and_have_no_domain_labels(self):
        fake_store = SimpleNamespace(
            items={
                "private-programme-slug": {
                    "entityTypeCodes": ["POTA", "SOTA"],
                },
                "another-private-slug": {
                    "entityTypeCodes": ["POTA"],
                },
            },
            data={"entityTypeCatalog": {"POTA": {}, "SOTA": {}}},
        )

        with patch.object(ProgrammeHandler, "store", fake_store):
            output = ProgrammeHandler.metrics_text()

        self.assertIn("myota_programmes 2", output)
        self.assertIn("myota_programme_entity_type_catalog_items 2", output)
        self.assertIn("myota_programme_category_assignments 3", output)
        self.assertNotIn("private-programme-slug", output)
        self.assertNotIn("POTA", output)


if __name__ == "__main__":
    unittest.main()
