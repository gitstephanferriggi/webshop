"""Validate browser signature images before storing or rendering them."""
import base64
import binascii
from io import BytesIO

from PIL import Image, ImageChops

ACKNOWLEDGEMENT = "I confirm receipt of the items and quantities listed above."


def clean_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 140 or any(ord(c) < 32 for c in value):
        raise ValueError("Enter the collector or recipient's name.")
    return value.strip()


def clean_signature(value):
    prefix = "data:image/png;base64,"
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 350_000:
        raise ValueError("Please sign in the signature box.")
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
        with Image.open(BytesIO(raw)) as source:
            if source.format != "PNG" or not (40 <= source.width <= 2000 and 20 <= source.height <= 1000):
                raise ValueError
            source.load()
            rgba = source.convert("RGBA")
            image = Image.new("RGB", source.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        ink = ImageChops.difference(image, Image.new("RGB", image.size, "white")).convert("L")
        if sum(count for shade, count in enumerate(ink.histogram()) if shade > 35) < 40:
            raise ValueError
        output = BytesIO()
        image.save(output, format="PNG")
        return prefix + base64.b64encode(output.getvalue()).decode()
    except (ValueError, OSError, binascii.Error, Image.DecompressionBombError):
        raise ValueError("Please provide a clear signature in the signature box.") from None
