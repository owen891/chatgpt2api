from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from api.image_inputs import _download_image_url


class ImageUrlSafetyTests(unittest.TestCase):
    def test_rejects_private_address_before_request(self) -> None:
        with mock.patch("api.image_inputs.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]), \
             mock.patch("api.image_inputs.requests.get") as get:
            with self.assertRaises(HTTPException) as raised:
                _download_image_url("http://internal.example.test/image.png")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("private network", str(raised.exception.detail))
        get.assert_not_called()

    def test_revalidates_every_redirect_target(self) -> None:
        redirect = mock.Mock(status_code=302, headers={"location": "http://private.example.test/image.png"})
        with mock.patch("api.image_inputs.socket.getaddrinfo", side_effect=[[(2, 1, 6, "", ("8.8.8.8", 0))], [(2, 1, 6, "", ("10.0.0.1", 0))]]), \
             mock.patch("api.image_inputs.requests.get", return_value=redirect) as get:
            with self.assertRaises(HTTPException) as raised:
                _download_image_url("https://public.example.test/image.png")

        self.assertIn("private network", str(raised.exception.detail))
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
