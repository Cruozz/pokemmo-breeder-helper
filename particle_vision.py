"""Match the particle badge in the bottom-right slot of a summary portrait."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import math

from cosmetics import particle_catalog


@lru_cache(maxsize=1)
def _templates():
    import cv2
    import numpy as np
    root = Path(__file__).resolve().parent / "data"
    return [(entry["id"], cv2.imdecode(np.frombuffer((root / entry["icon"]).read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED))
            for entry in particle_catalog()]


def _icon_region(image, items):
    """Use the name row, panel edge and text scale; never search the sprite."""
    import numpy as np
    from ocr_engine import OCRProcessor as OCR

    name = next(iter(OCR._level_items(items)), None)
    if name is None or name.box is None:
        return None
    h = max(8, round(OCR._height(name.box)))
    name_right = math.ceil(OCR._right(name.box))
    top = max(0, math.floor(OCR._top(name.box) - h * .6))
    bottom = min(image.height, math.ceil(OCR._bottom(name.box) + h * .15))
    # A separated gender glyph may be absent from the OCR name box.
    left = max(0, math.ceil(name_right + h))
    right = min(image.width, math.ceil(name_right + h * 12))
    if right <= left or bottom <= top:
        return None

    # A full-screen capture can contain another UI column immediately to the
    # right. Stop at the portrait's persistent vertical frame, not image.width.
    y0 = max(0, math.floor(OCR._top(name.box) - h * 2))
    y1 = min(image.height, math.ceil(OCR._bottom(name.box) + h * .3))
    strip = np.asarray(image.convert("RGB").crop((left - 1, y0, right, y1)), dtype=np.int16)
    edges = (np.max(np.abs(np.diff(strip, axis=1)), axis=2) >= 10).mean(axis=0)
    candidates = np.flatnonzero(edges >= .85)
    if len(candidates):
        right = left + int(candidates[0])
    elif right < image.width:
        # The panel boundary was not visible in a larger frame. Do not search
        # adjacent panels using an arbitrary distance from the name.
        return None
    left = max(left, math.floor(right - h * 2.8))
    if right - left < h * .8:
        return None
    return (left, top, right, bottom), h


def detect_particle(image, items) -> tuple[bool, list[str]]:
    if image is None:
        return False, []
    try:
        import cv2
        import numpy as np

        region = _icon_region(image, items)
        if region is None:
            return False, []
        box, h = region
        source = cv2.cvtColor(np.asarray(image.convert("RGB").crop(box)), cv2.COLOR_RGB2BGR)
        if not source.size or np.ptp(source, axis=(0, 1)).max() < 20:
            return False, []
        # The badge shares the name row's UI scale. Tiny sprite fragments and
        # oversized animation graphics cannot be particle candidates.
        sizes = range(max(8, math.floor(h * .8)), min(round(h * 1.6), *source.shape[:2]) + 1)
        scores = []
        for name, rgba in _templates():
            best = math.inf
            for size in sizes:
                for interpolation in (cv2.INTER_NEAREST, cv2.INTER_LINEAR):
                    template = cv2.resize(rgba, (size, size), interpolation=interpolation)
                    mask = (template[:, :, 3] > 245).astype(np.uint8) * 255
                    count = int(np.count_nonzero(mask))
                    if count < 6:
                        continue
                    result = cv2.matchTemplate(source, template[:, :, :3], cv2.TM_SQDIFF, mask=mask)
                    value, _, (x, y), _ = cv2.minMaxLoc(result)
                    if not math.isfinite(value):
                        continue
                    actual = source[y:y + size, x:x + size]
                    if np.ptp(actual, axis=(0, 1)).max() < 20:
                        continue
                    negative = template[:, :, 3] == 0
                    edge = max(1, size // 12)
                    negative[:edge] = negative[-edge:] = False
                    negative[:, :edge] = negative[:, -edge:] = False
                    background = actual[negative].astype(np.float32)
                    if len(background) < 6:
                        continue
                    background_color = np.median(background, axis=0)
                    alpha = template[:, :, 3:4].astype(np.float32) / 255
                    composite = template[:, :, :3] * alpha + background_color * (1 - alpha)
                    # Confirm the whole silhouette, including its empty pixels.
                    # Dark, sparse templates otherwise fit almost any dark UI.
                    correlation = cv2.matchTemplate(actual.astype(np.float32), composite, cv2.TM_CCOEFF_NORMED)[0, 0]
                    if correlation < .85:
                        continue
                    spread = float(np.mean((background - background_color) ** 2))
                    error = math.sqrt(max(0, value) / (count * 3) + 3 * spread)
                    best = min(best, error)
            scores.append((best, name))
        scores.sort()
        if len(scores) >= 2 and scores[0][0] <= 38 and scores[1][0] - scores[0][0] >= 5:
            return True, [scores[0][1]]
        # A weak resemblance is not evidence that a particle exists.
        return False, []
    except (ImportError, AttributeError, TypeError, ValueError):
        return False, []
