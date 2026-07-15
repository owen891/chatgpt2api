from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.image_archive_recovery_service import ImageArchiveRecoveryService


OWNER = {"id": "owner-1", "name": "Owner", "role": "user"}
OTHER = {"id": "owner-2", "name": "Other", "role": "user"}


class ImageArchiveRecoveryServiceTests(unittest.TestCase):
    def test_recovery_persists_and_protects_source_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "recoveries.json"
            service = ImageArchiveRecoveryService(path)
            created = service.create(
                OWNER,
                operation="generation",
                model="gpt-image-2",
                pending=[{"url": "https://cdn.example.test/signed.png", "channel_name": "primary"}],
                error="download timeout",
            )

            public = service.get(OWNER, str(created["id"]))
            self.assertNotIn("pending_archive", public)
            self.assertEqual(public["status"], "error")

            reloaded = ImageArchiveRecoveryService(path)
            with self.assertRaises(ValueError):
                reloaded.get(OTHER, str(created["id"]))
            protected = reloaded.get(OWNER, str(created["id"]), include_urls=True)
            self.assertEqual(protected["pending_archive"][0]["url"], "https://cdn.example.test/signed.png")

    def test_retry_does_not_call_generation_and_persists_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = ImageArchiveRecoveryService(Path(tmp_dir) / "recoveries.json")
            created = service.create(
                OWNER,
                operation="generation",
                model="gpt-image-2",
                pending=[{"url": "https://cdn.example.test/signed.png"}],
                error="download timeout",
            )
            with mock.patch(
                "services.image_archive_recovery_service.image_upstream_service.archive_pending",
                return_value={"data": [{"url": "http://app.test/images/recovered.png"}]},
            ) as archive:
                service.retry(OWNER, str(created["id"]))
                for _ in range(20):
                    current = service.get(OWNER, str(created["id"]))
                    if current["status"] != "running":
                        break
                    import time

                    time.sleep(0.01)

            archive.assert_called_once()
            self.assertEqual(current["status"], "success")
            self.assertEqual(current["data"][0]["url"], "http://app.test/images/recovered.png")


if __name__ == "__main__":
    unittest.main()
