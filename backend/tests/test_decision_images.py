"""Preparing images for a decision model: orientation, size limits and encoding."""

import io
import unittest

from PIL import Image

from app.services.decision_images import MAX_SIDE, MIN_SIDE, prepare_image
from app.services.decision_models import DecisionRequestError

_EXIF_ORIENTATION = 0x0112


def _encode(image: Image.Image, fmt: str = "PNG", **save_kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def _decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


class PrepareImageTests(unittest.TestCase):
    def test_a_large_photo_is_downscaled_to_the_maximum_side(self) -> None:
        prepared = prepare_image("photo", _encode(Image.new("RGB", (4000, 3000), "red"), "JPEG"))
        self.assertEqual((prepared.width, prepared.height), (MAX_SIDE, 1176))
        self.assertEqual(_decode(prepared.data).size, (MAX_SIDE, 1176))

    def test_an_image_within_the_limits_keeps_its_size(self) -> None:
        prepared = prepare_image("photo", _encode(Image.new("RGB", (800, 600), "red")))
        self.assertEqual((prepared.width, prepared.height), (800, 600))

    def test_a_small_image_is_scaled_up_to_the_minimum_side(self) -> None:
        prepared = prepare_image("icon", _encode(Image.new("RGB", (100, 100), "red")))
        self.assertEqual((prepared.width, prepared.height), (MIN_SIDE, MIN_SIDE))

    def test_a_small_image_keeps_its_aspect_ratio_when_scaled_up(self) -> None:
        prepared = prepare_image("icon", _encode(Image.new("RGB", (200, 100), "red")))
        self.assertEqual((prepared.width, prepared.height), (560, MIN_SIDE))

    def test_a_long_strip_is_padded_rather_than_stretched(self) -> None:
        prepared = prepare_image("strip", _encode(Image.new("RGB", (2000, 100), "red")))
        self.assertEqual((prepared.width, prepared.height), (MAX_SIDE, MIN_SIDE))
        decoded = _decode(prepared.data).convert("RGB")
        # The strip sits in the middle; the padding above it is white.
        self.assertEqual(decoded.getpixel((MAX_SIDE // 2, 2)), (255, 255, 255))
        red, green, blue = decoded.getpixel((MAX_SIDE // 2, MIN_SIDE // 2))
        self.assertGreater(red, 200)
        self.assertLess(green, 60)
        self.assertLess(blue, 60)

    def test_exif_orientation_is_applied_to_the_pixels(self) -> None:
        image = Image.new("RGB", (600, 300), "red")
        exif = image.getexif()
        exif[_EXIF_ORIENTATION] = 6  # rotate 90 degrees clockwise to display upright
        prepared = prepare_image("photo", _encode(image, "JPEG", exif=exif.tobytes()))
        self.assertEqual((prepared.width, prepared.height), (300, 600))

    def test_an_opaque_image_becomes_a_jpeg(self) -> None:
        prepared = prepare_image("photo", _encode(Image.new("RGB", (400, 400), "red")))
        self.assertEqual(prepared.format, "jpg")
        self.assertEqual(_decode(prepared.data).format, "JPEG")

    def test_an_image_with_alpha_stays_a_png(self) -> None:
        prepared = prepare_image("logo", _encode(Image.new("RGBA", (400, 400), (255, 0, 0, 128))))
        self.assertEqual(prepared.format, "png")
        self.assertEqual(_decode(prepared.data).mode, "RGBA")

    def test_a_webp_is_converted(self) -> None:
        prepared = prepare_image("photo", _encode(Image.new("RGB", (400, 400), "red"), "WEBP"))
        self.assertEqual(prepared.format, "jpg")

    def test_an_animation_yields_its_first_frame(self) -> None:
        frames = [Image.new("RGB", (400, 400), color) for color in ("red", "blue")]
        buffer = io.BytesIO()
        frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
        prepared = prepare_image("clip", buffer.getvalue())
        decoded = _decode(prepared.data)
        self.assertEqual(getattr(decoded, "n_frames", 1), 1)
        red, _green, blue = decoded.convert("RGB").getpixel((200, 200))
        self.assertGreater(red, blue)

    def test_bytes_that_are_not_an_image_name_the_row(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            prepare_image("photo", b"definitely not an image")
        self.assertIn("'photo'", str(ctx.exception))

    def test_the_name_is_carried_through(self) -> None:
        prepared = prepare_image("poster", _encode(Image.new("RGB", (400, 400), "red")))
        self.assertEqual(prepared.name, "poster")


if __name__ == "__main__":
    unittest.main()
