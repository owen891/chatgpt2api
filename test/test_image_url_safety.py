from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from api.image_inputs import _download_image_url


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image"


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

    def test_retries_with_resource_proxy_after_direct_fetch_failure(self) -> None:
        response = mock.Mock(status_code=200, headers={"content-type": "image/png"}, content=PNG_BYTES)
        with (
            mock.patch("api.image_inputs.socket.getaddrinfo", return_value=[[(2, 1, 6, "", ("8.8.8.8", 0))]][0]),
            mock.patch("api.image_inputs.proxy_settings.build_session_kwargs", return_value={"proxy": "http://resource.test:8080"}),
            mock.patch("api.image_inputs.requests.get", side_effect=[TimeoutError("direct timeout"), response]) as get,
            mock.patch("api.image_inputs.time.sleep"),
        ):
            result = _download_image_url("https://public.example.test/image.png")

        self.assertEqual(result[0], PNG_BYTES)
        self.assertEqual(get.call_count, 2)
        self.assertNotIn("proxy", get.call_args_list[0].kwargs)
        self.assertEqual(get.call_args_list[1].kwargs["proxy"], "http://resource.test:8080")


if __name__ == "__main__":
    unittest.main()
