import unittest

from programmes import ProgrammeHandler, _utc_timestamp


class UtcEffectiveDateTests(unittest.TestCase):
    def test_normalizes_offsets_and_legacy_unqualified_times(self):
        for value in (
            "2026-10-09T14:45:30+02:00",
            "2026-10-09T12:45:30",
            "2026-10-09T12:45:30Z",
        ):
            self.assertEqual(_utc_timestamp(value), "2026-10-09T12:45:30Z")
        with self.assertRaises(ValueError):
            _utc_timestamp("not a timestamp")

    def test_publication_and_events_use_canonical_utc(self):
        store = ProgrammeHandler.store
        previous = store.items, store.data, store.events
        store.items, store.data, store.events = (
            {"fixture": {"rules": {}, "entityTypes": []}},
            {},
            [],
        )
        try:
            content = ProgrammeHandler.save_content(
                None,
                {
                    "slug": "fixture",
                    "_body": {"key": "title", "locale": "en", "value": "Test"},
                },
            )
            ProgrammeHandler._content_bucket()[content["id"]]["status"] = (
                "APPROVED"
            )
            published = ProgrammeHandler.publish_content(
                None,
                {
                    "slug": "fixture",
                    "contentId": content["id"],
                    "_body": {
                        "effectiveFrom": "2026-10-09T14:45:30+02:00",
                        "publisherId": "fixture",
                    },
                },
            )
            self.assertEqual(
                published["effectiveFrom"], "2026-10-09T12:45:30Z"
            )
            self.assertEqual(
                store.events[-1]["payload"]["effectiveFrom"],
                "2026-10-09T12:45:30Z",
            )
            draft = ProgrammeHandler.save_policy_draft(
                None,
                {
                    "slug": "fixture",
                    "_body": {
                        "name": "UTC policy",
                        "type": "RULES",
                        "schema": {
                            "rules": {"minimumQsos": {"activation": 0}}
                        },
                        "effectiveFrom": "2026-10-09T14:45:30+02:00",
                    },
                },
            )
            self.assertEqual(draft["effectiveFrom"], "2026-10-09T12:45:30Z")
            ProgrammeHandler._policy_bucket()[draft["id"]]["status"] = (
                "APPROVED"
            )
            policy = ProgrammeHandler.publish_policy_draft(
                None,
                {
                    "slug": "fixture",
                    "draftId": draft["id"],
                    "_body": {
                        "effectiveFrom": "2026-10-09T14:45:30+02:00",
                        "publisherId": "fixture",
                    },
                },
            )
            self.assertEqual(
                policy["draft"]["effectiveFrom"], "2026-10-09T12:45:30Z"
            )
        finally:
            store.items, store.data, store.events = previous
