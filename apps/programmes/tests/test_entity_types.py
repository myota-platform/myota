import unittest

from programmes import ProgrammeHandler


class EntityTypeManagementTests(unittest.TestCase):
    def setUp(self):
        self.previous_items = ProgrammeHandler.store.items
        self.previous_events = ProgrammeHandler.store.events
        self.previous_data = ProgrammeHandler.store.data
        ProgrammeHandler.store.items = {
            "demo": {
                "id": "programme-1",
                "entityTypes": [
                    {
                        "code": "MUNICIPAL_PARK",
                        "label": "Municipal park",
                        "geometry": "MULTIPOLYGON",
                    }
                ],
                "policyVersion": 1,
            }
        }
        ProgrammeHandler.store.events = []
        ProgrammeHandler.store.data = {}

    def tearDown(self):
        ProgrammeHandler.store.items = self.previous_items
        ProgrammeHandler.store.events = self.previous_events
        ProgrammeHandler.store.data = self.previous_data

    def test_creates_and_updates_programme_category(self):
        result = ProgrammeHandler.save_entity_type(
            None,
            {
                "slug": "demo",
                "_body": {
                    "code": "TRAIL",
                    "label": "Trail",
                    "geometry": "LINESTRING",
                    "description": "A walkable route",
                },
            },
        )
        self.assertEqual(result["entityType"]["code"], "TRAIL")
        self.assertTrue(result["entityType"]["active"])

        result = ProgrammeHandler.save_entity_type(
            None,
            {
                "slug": "demo",
                "_body": {
                    "code": "TRAIL",
                    "originalCode": "TRAIL",
                    "label": "Hiking trail",
                    "geometry": "LINESTRING",
                    "active": False,
                },
            },
        )
        self.assertEqual(result["entityType"]["label"], "Hiking trail")
        self.assertFalse(result["entityType"]["active"])

    def test_category_codes_cannot_be_renamed(self):
        with self.assertRaisesRegex(ValueError, "cannot be renamed"):
            ProgrammeHandler.save_entity_type(
                None,
                {
                    "slug": "demo",
                    "_body": {
                        "code": "CITY_PARK",
                        "originalCode": "MUNICIPAL_PARK",
                        "label": "City park",
                        "geometry": "POLYGON",
                    },
                },
            )

    def test_category_can_be_assigned_to_multiple_programmes(self):
        ProgrammeHandler.store.items["second"] = {
            "id": "programme-2",
            "entityTypes": [],
            "policyVersion": 1,
        }
        ProgrammeHandler.save_entity_type_catalog(
            None,
            {
                "_body": {
                    "code": "TRAIL",
                    "label": "Trail",
                    "geometry": "LINESTRING",
                }
            },
        )
        ProgrammeHandler.assign_entity_type(
            None, {"slug": "demo", "_body": {"code": "TRAIL"}}
        )
        ProgrammeHandler.assign_entity_type(
            None, {"slug": "second", "_body": {"code": "TRAIL"}}
        )

        self.assertEqual(
            [
                item["code"]
                for item in ProgrammeHandler.list_entity_types(
                    None, {"slug": "demo"}
                )["items"]
            ],
            ["MUNICIPAL_PARK", "TRAIL"],
        )
        self.assertEqual(
            [
                item["code"]
                for item in ProgrammeHandler.list_entity_types(
                    None, {"slug": "second"}
                )["items"]
            ],
            ["TRAIL"],
        )

        ProgrammeHandler.unassign_entity_type(
            None, {"slug": "demo", "_body": {"code": "TRAIL"}}
        )
        self.assertEqual(
            [
                item["code"]
                for item in ProgrammeHandler.list_entity_types(
                    None, {"slug": "second"}
                )["items"]
            ],
            ["TRAIL"],
        )

    def test_category_accepts_multiple_geometry_types(self):
        result = ProgrammeHandler.save_entity_type_catalog(
            None,
            {
                "_body": {
                    "code": "OUTDOOR_SITE",
                    "label": "Outdoor site",
                    "geometryTypes": [
                        "Point",
                        "LineString",
                        "MultiLineString",
                        "Polygon",
                        "MultiPolygon",
                    ],
                }
            },
        )
        self.assertEqual(
            result["entityType"]["geometryTypes"],
            [
                "POINT",
                "LINESTRING",
                "MULTILINESTRING",
                "POLYGON",
                "MULTIPOLYGON",
            ],
        )

    def test_resource_aliases_preserve_assignment_and_content_lifecycle(self):
        ProgrammeHandler.save_entity_type_catalog(
            None,
            {
                "_body": {
                    "code": "TRAIL",
                    "label": "Trail",
                    "geometry": "LINESTRING",
                }
            },
        )
        assigned = ProgrammeHandler.assign_entity_type_resource(
            None,
            {
                "slug": "demo",
                "categoryCode": "TRAIL",
                "Idempotency-Key": "assign-trail",
            },
        )
        event_count = len(ProgrammeHandler.store.events)
        repeated = ProgrammeHandler.assign_entity_type_resource(
            None,
            {
                "slug": "demo",
                "categoryCode": "TRAIL",
                "Idempotency-Key": "assign-trail",
            },
        )
        self.assertIn("TRAIL", [item["code"] for item in assigned["items"]])
        self.assertEqual(repeated, assigned)
        self.assertEqual(len(ProgrammeHandler.store.events), event_count)
        removed = ProgrammeHandler.unassign_entity_type_resource(
            None,
            {
                "slug": "demo",
                "categoryCode": "TRAIL",
                "Idempotency-Key": "unassign-trail",
            },
        )
        self.assertNotIn("TRAIL", [item["code"] for item in removed["items"]])

        content = ProgrammeHandler.save_content(
            None,
            {
                "slug": "demo",
                "_body": {
                    "key": "programme.title",
                    "locale": "en",
                    "value": "Draft title",
                },
            },
        )
        content = ProgrammeHandler.patch_content(
            None,
            {
                "slug": "demo",
                "contentId": content["id"],
                "_body": {"value": "Updated title"},
            },
        )
        self.assertEqual(content["value"], "Updated title")
        content = ProgrammeHandler.patch_content(
            None,
            {
                "slug": "demo",
                "contentId": content["id"],
                "_body": {"status": "UNDER_REVIEW"},
            },
        )
        self.assertEqual(content["status"], "UNDER_REVIEW")


if __name__ == "__main__":
    unittest.main()
