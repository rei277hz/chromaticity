"""Validate the generated ICC profiles using Pillow's independent LittleCMS."""
import base64
import io
import json
import sys
import numpy as np
from PIL import Image, ImageCms
from picker_reference import P3, REC709

profiles = json.load(sys.stdin)
out = {}
sample = np.array([180, 120, 90])
encoded = sample / 255
linear = np.where(encoded <= .04045, encoded / 12.92, ((encoded + .055) / 1.055)**2.4)
destination = ImageCms.createProfile("sRGB")
for name, matrix in [("srgb", REC709), ("p3", P3)]:
    source = ImageCms.ImageCmsProfile(io.BytesIO(base64.b64decode(profiles[name])))
    image = Image.new("RGB", (1, 1), tuple(sample))
    actual = ImageCms.profileToProfile(image, source, destination, renderingIntent=1).getpixel((0, 0))
    rgb = np.clip(np.linalg.solve(REC709, matrix @ linear), 0, 1)
    expected = np.rint(np.where(rgb <= .0031308, 12.92 * rgb, 1.055 * rgb**(1/2.4) - .055) * 255)
    out[name] = {"name": ImageCms.getProfileDescription(source), "actual": actual, "expected": expected.tolist()}
json.dump(out, sys.stdout)
