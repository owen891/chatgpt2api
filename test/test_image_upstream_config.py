from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.config import ConfigStore


def image_upstreams(api_key: str = "secret") -> dict[str, object]:
    return {
        "max_attempts": 2,
        "channels": [{
            "id": "primary", "name": "Primary", "enabled": True, "priority": 10,
            "base_url": " https://images.example.test/v1/ ", "api_key": api_key,
            "model_mappings": [{"client_model": "gpt-image-2", "upstream_model": "provider-image"}],
        }],
    }


class ImageUpstreamConfigTests(unittest.TestCase):
    def make_store(self) -> tuple[tempfile.TemporaryDirectory[str], ConfigStore]:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "config.json"
        path.write_text(json.dumps({"auth-key": "test", "image_upstreams": image_upstreams()}), encoding="utf-8")
        return tmp, ConfigStore(path)

    def test_public_config_redacts_key_and_empty_edit_preserves_it(self) -> None:
        tmp, store = self.make_store()
        with tmp:
            public = store.get()["image_upstreams"]
            channel = public["channels"][0]
            self.assertNotIn("api_key", channel)
            self.assertTrue(channel["has_api_key"])
            self.assertNotIn("secret", json.dumps(public))

            saved = store.update({"image_upstreams": public})
            self.assertTrue(saved["image_upstreams"]["channels"][0]["has_api_key"])
            raw = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["image_upstreams"]["channels"][0]["api_key"], "secret")

    def test_explicit_clear_removes_key_and_invalid_enabled_url_is_rejected(self) -> None:
        tmp, store = self.make_store()
        with tmp:
            public = store.get()["image_upstreams"]
            public["channels"][0]["clear_api_key"] = True
            store.update({"image_upstreams": public})
            self.assertEqual(store.get_image_upstreams_settings()["channels"][0]["api_key"], "")

            invalid = image_upstreams()
            invalid["channels"][0]["base_url"] = "not-a-url"
            with self.assertRaises(ValueError):
                store.update({"image_upstreams": invalid})

    def test_rejects_duplicate_or_conflicting_model_alias(self) -> None:
        tmp, store = self.make_store()
        with tmp:
            invalid = image_upstreams()
            invalid["channels"].append({
                "id": "secondary", "name": "Secondary", "enabled": True, "priority": 20,
                "base_url": "https://secondary.example.test/v1", "model_alias": "primary-image",
                "model_mappings": [{"client_model": "gpt-image-2", "upstream_model": "secondary-image"}],
            })
            invalid["channels"][0]["model_alias"] = "primary-image"
            with self.assertRaisesRegex(ValueError, "重复"):
                store.update({"image_upstreams": invalid})

            invalid["channels"] = invalid["channels"][:1]
            invalid["channels"][0]["model_alias"] = "gpt-image-2"
            with self.assertRaisesRegex(ValueError, "冲突"):
                store.update({"image_upstreams": invalid})

    def test_rejects_colliding_multi_mapping_model_aliases(self) -> None:
        tmp, store = self.make_store()
        with tmp:
            invalid = image_upstreams()
            invalid["channels"][0].update({
                "model_alias": "primary",
                "model_mappings": [
                    {"client_model": "one", "upstream_model": "provider-one"},
                    {"client_model": "two", "upstream_model": "provider-two"},
                ],
            })
            invalid["channels"].append({
                "id": "secondary", "name": "Secondary", "enabled": True, "priority": 20,
                "base_url": "https://secondary.example.test/v1", "model_alias": "primary--one",
                "model_mappings": [{"client_model": "three", "upstream_model": "provider-three"}],
            })
            with self.assertRaisesRegex(ValueError, "ID 重复"):
                store.update({"image_upstreams": invalid})


if __name__ == "__main__":
    unittest.main()
