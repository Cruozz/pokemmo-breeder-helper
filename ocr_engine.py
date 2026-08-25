from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from nature_data import NATURES


IV_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})/(\d{1,2})(?!\d)"
)
IV_LABELS = ("个体值", "個體值", "个休值", "個休值", "个体直", "個體直", "ivs", "iv")
MARK_LABELS = ("标记", "標記", "mark")


@dataclass
class OCRItem:
    text: str
    score: float
    box: Any = None


class OCRProcessor:
    """Read the inventory fields that can affect breeding decisions.

    RapidOCR still sees every glyph inside the user-selected rectangle, but
    parsing is restricted to species, gender, IVs, nature and the four move
    rows. In particular, an unlabeled six-number row is never preferred over
    the row geometrically paired with the ``个体值`` label.
    """

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("缺少 rapidocr_onnxruntime，请重新运行构建脚本。") from exc
        self.engine = RapidOCR()

    def recognize(self, image) -> list[OCRItem]:
        # Keep NumPy lazy so parser-only tests do not need the OCR runtime.
        import numpy as np

        array = np.asarray(image.convert("RGB"))
        result, _elapsed = self.engine(array)
        items: list[OCRItem] = []
        for item in result or []:
            if len(item) < 3:
                continue
            try:
                items.append(OCRItem(str(item[1]), float(item[2]), item[0]))
            except (TypeError, ValueError):
                continue
        return items

    @staticmethod
    def _line_text(items: list[OCRItem]) -> str:
        if not items:
            return ""
        sorted_items = sorted(items, key=lambda x: (OCRProcessor._top(x.box), OCRProcessor._left(x.box)))
        rows: list[list[OCRItem]] = []
        for item in sorted_items:
            center = OCRProcessor._center_y(item.box)
            height = OCRProcessor._height(item.box)
            tolerance = max(5.0, height * 0.45)
            row = next(
                (
                    row
                    for row in rows
                    if abs(OCRProcessor._center_y(row[0].box) - center)
                    <= max(tolerance, OCRProcessor._height(row[0].box) * 0.45)
                ),
                None,
            )
            if row is None:
                rows.append([item])
            else:
                row.append(item)
        lines: list[str] = []
        for row in sorted(rows, key=lambda r: OCRProcessor._center_y(r[0].box)):
            lines.append(" ".join(x.text.strip() for x in sorted(row, key=lambda x: OCRProcessor._left(x.box))))
        return "\n".join(lines)

    @staticmethod
    def _left(box: Any) -> float:
        try:
            return min(float(point[0]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _right(box: Any) -> float:
        try:
            return max(float(point[0]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _top(box: Any) -> float:
        try:
            return min(float(point[1]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _bottom(box: Any) -> float:
        try:
            return max(float(point[1]) for point in box)
        except Exception:
            return 0.0

    @staticmethod
    def _height(box: Any) -> float:
        try:
            ys = [float(point[1]) for point in box]
            return max(ys) - min(ys)
        except Exception:
            return 12.0

    @staticmethod
    def _center_y(box: Any) -> float:
        return (OCRProcessor._top(box) + OCRProcessor._bottom(box)) / 2.0

    @staticmethod
    def _compact(value: str) -> str:
        return (
            (value or "")
            .replace("／", "/")
            .replace("|", "/")
            .replace(" ", "")
            .lower()
        )

    @staticmethod
    def _iv_values(value: str) -> list[int] | None:
        match = IV_PATTERN.search(OCRProcessor._compact(value))
        if not match:
            return None
        values = [int(part) for part in match.groups()]
        return values if all(0 <= number <= 31 for number in values) else None

    @staticmethod
    def _is_iv_label(value: str) -> bool:
        compact = re.sub(r"[^0-9a-z\u3400-\u9fff]", "", OCRProcessor._compact(value))
        return any(label in compact for label in IV_LABELS)

    @classmethod
    def _all_perfect_ivs_from_color(cls, image: Any, label: OCRItem, candidate: OCRItem) -> bool:
        """Conservatively recover a green 6×31 row that OCR merged.

        PokeMMO colors perfect IV values green.  On translucent themes the
        recognizer can drop the first value and read ``31/31`` as ``731``.
        We only recover six perfect values when the labeled row contains six
        evenly spaced green text clusters; otherwise the strict parser keeps
        the values unknown instead of guessing.
        """
        if image is None:
            return False
        height = max(8.0, cls._height(label.box), cls._height(candidate.box))
        left = max(0, int(cls._right(label.box) + height * 0.2))
        top = max(0, int(min(cls._top(label.box), cls._top(candidate.box)) - height * 0.15))
        right = int(cls._right(candidate.box) + height * 0.6)
        bottom = int(max(cls._bottom(label.box), cls._bottom(candidate.box)) + height * 0.15)
        try:
            rgb = image.convert("RGB")
            right = min(rgb.width, right)
            bottom = min(rgb.height, bottom)
            region = rgb.crop((left, top, right, bottom))
            width, region_height = region.size
            pixels = list(region.getdata())
        except Exception:
            return False
        if width < height * 4 or region_height < 4:
            return False

        minimum_column_pixels = max(2, int(height * 0.10))
        column_counts = [0] * width
        for y in range(region_height):
            offset = y * width
            for x in range(width):
                red, green, blue = pixels[offset + x][:3]
                green_excess = int(green) - (int(red) + int(blue)) / 2.0
                if green >= 80 and green_excess > 24:
                    column_counts[x] += 1
        active = [index for index, count in enumerate(column_counts) if count >= minimum_column_pixels]
        if not active:
            return False

        max_inner_gap = max(3, int(height * 0.16))
        clusters: list[tuple[int, int]] = []
        start = previous = active[0]
        for x in active[1:]:
            if x - previous > max_inner_gap:
                clusters.append((start, previous))
                start = x
            previous = x
        clusters.append((start, previous))
        minimum_width = max(3, int(height * 0.15))
        clusters = [(start, end) for start, end in clusters if end - start + 1 >= minimum_width]
        if len(clusters) != 6:
            return False
        centers = [(start + end) / 2.0 for start, end in clusters]
        gaps = [right_center - left_center for left_center, right_center in zip(centers, centers[1:])]
        average_gap = sum(gaps) / len(gaps)
        return average_gap >= height * 0.55 and max(abs(gap - average_gap) for gap in gaps) <= average_gap * 0.25

    @classmethod
    def _find_individual_values(
        cls,
        items: list[OCRItem],
        lines_text: str,
        image: Any = None,
    ) -> tuple[list[int] | None, list[OCRItem]]:
        labels = [item for item in items if cls._is_iv_label(item.text)]
        candidates = [(item, cls._iv_values(item.text)) for item in items]
        candidates = [(item, values) for item, values in candidates if values is not None]

        # Best case: OCR returned label and six values as one block.
        for item, values in candidates:
            if cls._is_iv_label(item.text):
                return values, [item]

        # Common case: label and value are separate blocks on the same row.
        ranked: list[tuple[float, OCRItem, OCRItem, list[int]]] = []
        for label in labels:
            label_center = cls._center_y(label.box)
            for candidate, values in candidates:
                difference = abs(label_center - cls._center_y(candidate.box))
                tolerance = max(10.0, cls._height(label.box) * 0.8, cls._height(candidate.box) * 0.8)
                if difference > tolerance:
                    continue
                side_penalty = 0.0 if cls._left(candidate.box) >= cls._left(label.box) else 50.0
                gap = max(0.0, cls._left(candidate.box) - cls._right(label.box))
                ranked.append((difference + side_penalty + gap * 0.01, label, candidate, values))
        if ranked:
            _rank, label, candidate, values = min(ranked, key=lambda entry: entry[0])
            return values, [label, candidate]

        # A transparent background can make a green 6V row look like
        # ``731/31/31/31/31``.  Use the six green value clusters only when the
        # malformed numeric block is geometrically paired with the IV label.
        for label in labels:
            for candidate in items:
                compact = cls._compact(candidate.text)
                if candidate is label or compact.count("/") < 3 or len(re.findall(r"\d", compact)) < 6:
                    continue
                difference = abs(cls._center_y(label.box) - cls._center_y(candidate.box))
                tolerance = max(10.0, cls._height(label.box) * 0.8, cls._height(candidate.box) * 0.8)
                if difference > tolerance or cls._left(candidate.box) < cls._right(label.box) - 4:
                    continue
                if cls._all_perfect_ivs_from_color(image, label, candidate):
                    return [31] * 6, [label, candidate]

        # A label and value can occasionally be merged only by row grouping.
        for line in lines_text.splitlines():
            if cls._is_iv_label(line):
                values = cls._iv_values(line)
                if values is not None:
                    return values, labels

        # If exactly one six-value row is visible (for example a tightly
        # selected IV-only rectangle), accepting it is safe. With multiple
        # unlabeled rows, return unknown instead of silently storing 能力值.
        if len(candidates) == 1:
            return candidates[0][1], [candidates[0][0]]
        return None, labels

    @staticmethod
    def _nature_in_text(value: str):
        compact = OCRProcessor._compact(value)
        for nature in NATURES:
            if nature.chinese in compact or nature.english.lower() in compact:
                return nature
        return None

    @classmethod
    def _find_nature(cls, items: list[OCRItem], lines_text: str) -> tuple[str, list[OCRItem]]:
        labels = [item for item in items if "性格" in cls._compact(item.text) or "nature" in cls._compact(item.text)]
        for label in labels:
            direct = cls._nature_in_text(label.text)
            if direct:
                return direct.chinese, [label]
            ranked: list[tuple[float, OCRItem, Any]] = []
            for candidate in items:
                if candidate is label:
                    continue
                difference = abs(cls._center_y(label.box) - cls._center_y(candidate.box))
                tolerance = max(10.0, cls._height(label.box) * 0.8, cls._height(candidate.box) * 0.8)
                if difference > tolerance or cls._left(candidate.box) < cls._right(label.box) - 4:
                    continue
                nature = cls._nature_in_text(candidate.text)
                if nature:
                    gap = max(0.0, cls._left(candidate.box) - cls._right(label.box))
                    ranked.append((difference + gap * 0.01, candidate, nature))
            if ranked:
                _rank, candidate, nature = min(ranked, key=lambda entry: entry[0])
                return nature.chinese, [label, candidate]
        for line in lines_text.splitlines():
            if "性格" not in line and "nature" not in line.lower():
                continue
            nature = cls._nature_in_text(line)
            if nature:
                return nature.chinese, labels
        return "", labels

    @classmethod
    def _find_moves(cls, items: list[OCRItem]) -> tuple[list[str], list[OCRItem]]:
        markers = [item for item in items if any(label in cls._compact(item.text) for label in MARK_LABELS)]
        if not markers:
            return [], []
        marker = markers[0]
        height = max(8.0, cls._height(marker.box))
        top_limit = cls._bottom(marker.box) + height * 0.15
        bottom_limit = cls._bottom(marker.box) + height * 8.2
        # Each move row has a type badge to the left (for example “一般” or
        # “草”) and the move name immediately to the right.  Anchor the
        # horizontal band to the marker label's right edge so the badge cannot
        # consume one of the four move slots.  The right bound also keeps text
        # from the storage grid/search controls out of a partially filled move
        # list.
        left_limit = cls._right(marker.box) - height * 0.25
        right_limit = cls._right(marker.box) + height * 7.5
        ignored = (
            "能力值", "个体值", "努力值", "性格", "特性", "持有道具", "标记",
            "電腦", "电脑", "箱子", "高级搜索", "高級搜索", "概况", "戰鬥", "战斗",
        )
        candidates: list[OCRItem] = []
        for item in sorted(items, key=lambda value: (cls._center_y(value.box), cls._left(value.box))):
            center = cls._center_y(item.box)
            raw = item.text.strip(" ：:|/")
            compact = cls._compact(raw)
            if not (top_limit <= center <= bottom_limit):
                continue
            if not (left_limit <= cls._left(item.box) <= right_limit) or item.score < 0.40:
                continue
            if not raw or any(word in compact for word in ignored):
                continue
            if re.search(r"\d{1,2}/\d{1,2}", compact) or re.search(r"\blv\.?\s*\d+", raw, re.IGNORECASE):
                continue
            if not re.search(r"[a-z\u3400-\u9fff]", compact):
                continue
            candidates.append(item)

        moves: list[str] = []
        used: list[OCRItem] = []
        for item in candidates:
            move = item.text.strip(" ：:|/")
            if move and move not in moves:
                moves.append(move)
                used.append(item)
            if len(moves) >= 4:
                break
        return moves, [marker, *used]

    @staticmethod
    def _level_items(items: list[OCRItem]) -> list[OCRItem]:
        return [item for item in items if re.search(r"\bLv\.?\s*\d+", item.text, flags=re.IGNORECASE)]

    @classmethod
    def _species_from_level_item(cls, items: list[OCRItem]) -> tuple[str, OCRItem | None]:
        for item in cls._level_items(items):
            species = re.sub(r"^.*?\bLv\.?\s*\d+", "", item.text, flags=re.IGNORECASE).strip(" ：:")
            species = species.replace("♀", "").replace("♂", "").strip()
            # RapidOCR commonly reads the small pink female glyph as 早.
            species = re.sub(r"[\s'\"`·]*(?:早)$", "", species).strip()
            return species, item
        return "", None

    @staticmethod
    def _gender_color_counts(pixels: Iterable[tuple[int, ...]]) -> tuple[int, int]:
        female = 0
        male = 0
        for pixel in pixels:
            if len(pixel) < 3:
                continue
            red, green, blue = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            # PokeMMO draws ♀ in saturated pink/magenta and ♂ in blue/cyan.
            # White text and the dark panel satisfy neither rule.
            if red >= 120 and blue >= 80 and red - green >= 35 and blue - green >= 20:
                female += 1
            elif blue >= 120 and blue - red >= 25 and green - red >= 10:
                male += 1
        return female, male

    @classmethod
    def _gender_from_image(cls, image: Any, level_items: list[OCRItem]) -> str:
        if image is None or not level_items:
            return ""
        item = level_items[0]
        height = max(8.0, cls._height(item.box))
        left = max(0, int(cls._left(item.box) - height * 0.2))
        top = max(0, int(cls._top(item.box) - height * 0.35))
        right = int(cls._right(item.box) + height * 1.7)
        bottom = int(cls._bottom(item.box) + height * 0.35)
        try:
            rgb = image.convert("RGB")
            right = min(rgb.width, right)
            bottom = min(rgb.height, bottom)
            region = rgb.crop((left, top, right, bottom))
            pixels = region.getdata()
            female, male = cls._gender_color_counts(pixels)
            minimum = max(3, int(region.width * region.height * 0.001))
        except Exception:
            return ""
        if female >= minimum and female > male * 1.5:
            return "F"
        if male >= minimum and male > female * 1.5:
            return "M"
        return ""

    @classmethod
    def _alpha_from_image(cls, image: Any, level_items: list[OCRItem]) -> tuple[bool, float]:
        """Detect the red Alpha icon in the upper-left summary area."""
        if image is None or not level_items:
            return False, 0.0
        item = level_items[0]
        text_height = max(8.0, cls._height(item.box))
        right = max(1, int(cls._left(item.box) - text_height * 0.15))
        bottom = max(1, int(cls._top(item.box) - text_height * 1.8))
        try:
            rgb = image.convert("RGB")
            right = min(rgb.width, right)
            bottom = min(rgb.height, bottom)
            region = rgb.crop((0, 0, right, bottom))
            width, height = region.size
            pixels = list(region.getdata())
        except Exception:
            return False, 0.0
        if width < 2 or height < 2:
            return False, 0.0

        mask = [False] * (width * height)
        for index, pixel in enumerate(pixels):
            red, green, blue = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            mask[index] = red >= 70 and red - green >= 25 and red - blue >= 8

        visited = bytearray(width * height)
        minimum_area = max(20, int(text_height * text_height * 0.18))
        best_confidence = 0.0
        for seed, enabled in enumerate(mask):
            if not enabled or visited[seed]:
                continue
            stack = [seed]
            visited[seed] = 1
            area = 0
            min_x = max_x = seed % width
            min_y = max_y = seed // width
            while stack:
                current = stack.pop()
                x, y = current % width, current // width
                area += 1
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                for dy in (-1, 0, 1):
                    ny = y + dy
                    if ny < 0 or ny >= height:
                        continue
                    for dx in (-1, 0, 1):
                        nx = x + dx
                        if dx == 0 and dy == 0 or nx < 0 or nx >= width:
                            continue
                        neighbor = ny * width + nx
                        if mask[neighbor] and not visited[neighbor]:
                            visited[neighbor] = 1
                            stack.append(neighbor)
            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            density = area / (component_width * component_height)
            scale_ok = (
                text_height * 0.65 <= component_width <= text_height * 1.8
                and text_height * 0.65 <= component_height <= text_height * 1.8
            )
            shape_ok = 0.70 <= component_width / component_height <= 1.45 and 0.28 <= density <= 0.82
            if area >= minimum_area and min_x > 1 and scale_ok and shape_ok:
                area_score = min(1.0, area / max(1.0, text_height * text_height * 0.70))
                best_confidence = max(best_confidence, 0.65 + area_score * 0.35)
        return best_confidence >= 0.65, best_confidence

    @classmethod
    def parse(cls, items: list[OCRItem], image: Any = None) -> dict[str, Any]:
        lines_text = cls._line_text(items)
        species, species_item = cls._species_from_level_item(items)
        ivs, iv_items = cls._find_individual_values(items, lines_text, image)
        nature, nature_items = cls._find_nature(items, lines_text)
        moves, move_items = cls._find_moves(items)

        level_items = cls._level_items(items)
        gender = cls._gender_from_image(image, level_items)
        is_alpha, alpha_confidence = cls._alpha_from_image(image, level_items)
        level_text = " ".join(item.text for item in level_items)
        if not gender:
            if "♀" in level_text or "雌性" in level_text or re.search(r"早\s*$", level_text):
                gender = "F"
            elif "♂" in level_text or "雄性" in level_text:
                gender = "M"

        relevant: list[OCRItem] = []
        for item in ([species_item] if species_item else []) + iv_items:
            if item is not None and item not in relevant:
                relevant.append(item)
        confidence = sum(item.score for item in relevant) / len(relevant) if relevant else 0.0
        minimum_confidence = min((item.score for item in relevant), default=0.0)
        gender_text = {"F": "母", "M": "公", "N": "无性别"}.get(gender, "未识别")
        compact_result = "\n".join(
            (
                f"名字：{species or '未识别'}",
                f"性别：{gender_text}",
                f"个体值：{'/'.join(str(value) for value in ivs) if ivs else '未识别'}",
                f"性格：{nature or '未识别'}",
                f"技能：{'、'.join(moves) if moves else '未识别'}",
                f"类别：{'头目' if is_alpha else '普通'}",
            )
        )
        return {
            "species": species,
            "gender": gender,
            "ivs": ivs or [None] * 6,
            "nature": nature,
            "ability": "",
            "held_item": "",
            "moves": moves,
            "is_alpha": is_alpha,
            "raw_text": lines_text,
            "recognized_text": compact_result,
            "items": items,
            "confidence": confidence,
            "minimum_confidence": minimum_confidence,
            "nature_confidence": min((item.score for item in nature_items), default=0.0),
            "move_confidence": min((item.score for item in move_items[1:]), default=0.0),
            "alpha_confidence": alpha_confidence,
        }
