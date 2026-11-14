"""Conservative, local matching of the selected summary-panel particle icon."""
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


def detect_particle(image, items) -> tuple[bool, list[str]]:
    if image is None:
        return False, []
    try:
        from ocr_engine import OCRProcessor as OCR
        name = next(iter(OCR._level_items(items)), None)
        if name is None:
            return False, []
        h = max(8, round(OCR._height(name.box)))
        left = max(0, int(OCR._right(name.box) - h))
        top = max(0, int(OCR._top(name.box) - h * 4.5))
        right = min(image.width, int(OCR._right(name.box) + h * 5))
        bottom = min(image.height, int(OCR._bottom(name.box) + h * .5))
        if left >= right or top >= bottom:
            return False, []
        import cv2
        import numpy as np
        rgb = np.asarray(image.convert("RGB").crop((left, top, right, bottom)))
        if rgb.ndim != 3 or rgb.dtype != np.uint8 or not rgb.size:
            return False, []
        if np.ptp(rgb, axis=(0, 1)).max() < 12:
            return False, []
        source = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        # Locate at half resolution, then verify only the best few identities
        # in a small full-resolution patch. This avoids 42 full-size sweeps.
        small = cv2.resize(source, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
        sizes = sorted({12, *range(max(6, h // 2), min(56, h * 2) + 1, 2)})
        located = []
        for name, rgba in _templates():
            best = (math.inf, name, 12, (0, 0), rgba)
            for size in sizes:
                if size > min(small.shape[:2]):
                    continue
                template = cv2.resize(rgba, (size, size), interpolation=cv2.INTER_LINEAR)
                mask = (template[:, :, 3] > 245).astype(np.uint8) * 255
                if np.count_nonzero(mask) < 3:
                    continue
                result = cv2.matchTemplate(small, template[:, :, :3], cv2.TM_SQDIFF, mask=mask)
                value, _, position, _ = cv2.minMaxLoc(result)
                error = math.sqrt(max(0, value) / max(1, int(np.count_nonzero(mask)) * 3))
                if error < best[0]:
                    best = (error, name, size, position, rgba)
            located.append(best)
        scores = []
        for _, name, coarse_size, (x, y), rgba in sorted(located, key=lambda row: row[0])[:6]:
            best = math.inf
            for size in range(max(8, coarse_size * 2 - 5), coarse_size * 2 + 6):
                x0, y0 = max(0, x * 2 - 6), max(0, y * 2 - 6)
                patch = source[y0:min(source.shape[0], y * 2 + size + 7), x0:min(source.shape[1], x * 2 + size + 7)]
                if size > min(patch.shape[:2]):
                    continue
                for interpolation in (cv2.INTER_NEAREST, cv2.INTER_LINEAR):
                    template = cv2.resize(rgba, (size, size), interpolation=interpolation)
                    mask = (template[:, :, 3] > 245).astype(np.uint8) * 255
                    result = cv2.matchTemplate(patch, template[:, :, :3], cv2.TM_SQDIFF, mask=mask)
                    value, _, position, _ = cv2.minMaxLoc(result)
                    px, py = position
                    actual = patch[py:py + size, px:px + size]
                    if np.ptp(actual, axis=(0, 1)).max() < 20:
                        continue
                    negative = template[:, :, 3] == 0
                    edge = max(2, size // 12)
                    negative[:edge] = negative[-edge:] = False
                    negative[:, :edge] = negative[:, -edge:] = False
                    background = actual[negative].astype(np.float32)
                    spread = float(np.mean((background - np.median(background, axis=0)) ** 2)) if len(background) > 5 else 0
                    error = max(0, value) / max(1, int(np.count_nonzero(mask)) * 3)
                    best = min(best, math.sqrt(error + 3 * spread))
            scores.append((best, name))
        scores.sort()
        if scores[0][0] <= 34 and scores[1][0] - scores[0][0] >= 4:
            return True, [scores[0][1]]
        # Recognized as a particle-sized graphic but not a reliable identity.
        return scores[0][0] < 43, []
    except (ImportError, AttributeError, TypeError, ValueError):
        return False, []
