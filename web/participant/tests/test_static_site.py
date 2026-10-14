import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class _AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        asset = attributes.get("src") if tag == "script" else None
        if tag == "link" and attributes.get("rel") == "stylesheet":
            asset = attributes.get("href")
        if asset:
            self.assets.append(asset)
        if attributes.get("id"):
            self.ids.append(attributes["id"])


class StaticSiteTests(unittest.TestCase):
    def test_entrypoint_and_local_assets_exist(self):
        entrypoint = WEB / "index.html"
        self.assertTrue(entrypoint.is_file())
        parser = _AssetParser()
        parser.feed(entrypoint.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(parser.assets), 2)
        for asset in parser.assets:
            self.assertFalse(asset.startswith(("http://", "https://", "data:")))
            self.assertTrue((WEB / asset.lstrip("/")).is_file(), asset)

    def test_entrypoint_ids_are_unique(self):
        parser = _AssetParser()
        parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))

    def test_expected_site_assets_exist(self):
        self.assertTrue((WEB / "app.js").is_file())
        self.assertTrue((WEB / "profile-utils.js").is_file())
        self.assertTrue((WEB / "styles.css").is_file())

    def test_profile_editor_has_accessible_crop_and_private_fields(self):
        entrypoint = WEB / "index.html"
        parser = _AssetParser()
        parser.feed(entrypoint.read_text(encoding="utf-8"))
        self.assertTrue(
            {
                "profile-form",
                "profile-website",
                "profile-biography",
                "profile-biography-preview",
                "profile-image-file",
                "profile-crop-canvas",
                "profile-crop-zoom",
                "profile-image-upload",
            }.issubset(set(parser.ids))
        )
        self.assertEqual(
            parser.assets[-2:], ["/profile-utils.js", "/app.js"]
        )
        markup = entrypoint.read_text(encoding="utf-8")
        self.assertIn('id="profile-form" class="profile-form" hidden', markup)
        self.assertIn('id="profile-image-editor" class="profile-image-editor" hidden', markup)
        self.assertIn('aria-label="Square profile picture crop preview"', markup)


if __name__ == "__main__":
    unittest.main()
