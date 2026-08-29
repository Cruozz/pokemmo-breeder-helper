from __future__ import annotations

import unittest

from ocr_engine import OCRItem, OCRProcessor


def box(left: float, top: float, right: float, bottom: float) -> list[list[float]]:
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


class FakeImage:
    def __init__(self, width: int, height: int, color: tuple[int, int, int] = (0, 0, 0)) -> None:
        self.width = width
        self.height = height
        self.size = (width, height)
        self.pixels = [color] * (width * height)

    def convert(self, _mode: str):
        return self

    def getdata(self):
        return self.pixels

    def crop(self, bounds: tuple[int, int, int, int]):
        left, top, right, bottom = bounds
        result = FakeImage(max(0, right - left), max(0, bottom - top))
        result.pixels = [
            self.pixels[y * self.width + x]
            for y in range(top, bottom)
            for x in range(left, right)
        ]
        return result

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        self.pixels[y * self.width + x] = color


class OCRParserTests(unittest.TestCase):
    def test_uses_labeled_individual_values_instead_of_stats_or_evs(self) -> None:
        # Mirrors the three numeric rows visible in the user's PokeMMO panel.
        items = [
            OCRItem("Lv.1 蘑蘑菇 早", 0.80, box(100, 90, 250, 112)),
            OCRItem("能力值：", 0.90, box(20, 130, 80, 152)),
            OCRItem("12/5/6/5/6/5", 0.98, box(100, 130, 220, 152)),
            OCRItem("个体值：", 0.85, box(20, 170, 80, 192)),
            OCRItem("26/2/19/0/16/6", 0.99, box(100, 170, 240, 192)),
            OCRItem("努力值：", 0.92, box(20, 210, 80, 232)),
            OCRItem("0/0/0/0/0/0", 0.97, box(100, 210, 220, 232)),
            OCRItem("性格：", 0.92, box(20, 250, 80, 272)),
            OCRItem("坦率Docile", 0.96, box(100, 250, 200, 272)),
            OCRItem("特性：", 0.94, box(20, 275, 80, 287)),
            OCRItem("孢子", 0.97, box(100, 275, 150, 287)),
            OCRItem("标记：", 0.90, box(20, 290, 80, 312)),
            OCRItem("一般", 0.98, box(20, 330, 78, 352)),
            OCRItem("撞击", 0.94, box(100, 330, 150, 352)),
            OCRItem("草", 0.87, box(20, 370, 78, 392)),
            OCRItem("吸取", 0.93, box(100, 370, 150, 392)),
            OCRItem("茸", 0.63, box(20, 410, 78, 432)),
            OCRItem("麻痹粉", 0.91, box(100, 410, 165, 432)),
            OCRItem("草", 0.95, box(20, 450, 78, 472)),
            OCRItem("寄生种子", 0.99, box(100, 450, 180, 472)),
            OCRItem("高级搜索", 0.99, box(900, 450, 980, 472)),
        ]

        parsed = OCRProcessor.parse(items)

        self.assertEqual(parsed["species"], "蘑蘑菇")
        self.assertEqual(parsed["gender"], "F")
        self.assertEqual(parsed["ivs"], [26, 2, 19, 0, 16, 6])
        self.assertEqual(parsed["nature"], "坦率")
        self.assertEqual(parsed["ability"], "孢子")
        self.assertEqual(parsed["moves"], ["撞击", "吸取", "麻痹粉", "寄生种子"])
        self.assertNotIn("12/5/6/5/6/5", parsed["recognized_text"])
        self.assertIn("性别：母", parsed["recognized_text"])

    def test_multiple_unlabeled_rows_are_rejected_instead_of_guessing(self) -> None:
        items = [
            OCRItem("12/5/6/5/6/5", 0.98, box(100, 130, 220, 152)),
            OCRItem("26/2/19/0/16/6", 0.99, box(100, 170, 240, 192)),
        ]
        self.assertEqual(OCRProcessor.parse(items)["ivs"], [None] * 6)

    def test_gender_color_classifier_separates_pink_and_blue(self) -> None:
        female, male = OCRProcessor._gender_color_counts([(230, 80, 200)] * 10 + [(220, 220, 220)] * 20)
        self.assertEqual((female, male), (10, 0))
        female, male = OCRProcessor._gender_color_counts([(55, 170, 235)] * 10 + [(220, 220, 220)] * 20)
        self.assertEqual((female, male), (0, 10))

    def test_recovers_six_green_perfect_ivs_when_ocr_merges_the_row(self) -> None:
        image = FakeImage(300, 180)
        for value_index in range(6):
            left = 100 + value_index * 20
            for y in range(54, 65):
                for x in range(left, left + 9):
                    image.set_pixel(x, y, (100, 180, 120))
        items = [
            OCRItem("个体值：", 0.98, box(20, 50, 80, 72)),
            OCRItem("731/31/31/31/31", 0.90, box(110, 50, 230, 72)),
        ]

        self.assertEqual(OCRProcessor.parse(items, image)["ivs"], [31] * 6)

    def test_detects_red_alpha_icon_above_and_left_of_level_text(self) -> None:
        image = FakeImage(240, 260)
        for y in range(55, 85):
            for x in range(50, 80):
                if (x + y) % 2 == 0:
                    image.set_pixel(x, y, (150, 45, 55))
        items = [OCRItem("Lv.50 拉鲁拉丝", 0.95, box(100, 200, 210, 225))]

        parsed = OCRProcessor.parse(items, image)

        self.assertTrue(parsed["is_alpha"])
        self.assertGreaterEqual(parsed["alpha_confidence"], 0.65)
        self.assertFalse(OCRProcessor.parse(items, FakeImage(240, 260))["is_alpha"])

    def test_detects_cyan_hidden_ability_diamond_without_requiring_gold_text(self) -> None:
        image = FakeImage(260, 180)
        for y in range(93, 103):
            for x in range(139, 149):
                if abs(x - 144) + abs(y - 98) <= 6:
                    image.set_pixel(x, y, (45, 190, 235))
        items = [
            OCRItem("特性：", 0.96, box(20, 88, 80, 108)),
            OCRItem("食草", 0.94, box(92, 88, 128, 108)),
        ]

        parsed = OCRProcessor.parse(items, image)

        self.assertTrue(parsed["has_hidden_ability"])
        self.assertGreaterEqual(parsed["hidden_ability_confidence"], 0.70)
        self.assertFalse(OCRProcessor.parse(items, FakeImage(260, 180))["has_hidden_ability"])

    def test_gold_ability_text_without_cyan_diamond_is_not_hidden_ability(self) -> None:
        image = FakeImage(260, 180)
        for y in range(92, 105):
            for x in range(92, 128):
                if (x + y) % 3:
                    image.set_pixel(x, y, (205, 170, 85))
        items = [
            OCRItem("特性：", 0.96, box(20, 88, 80, 108)),
            OCRItem("食草", 0.94, box(92, 88, 128, 108)),
        ]

        parsed = OCRProcessor.parse(items, image)

        self.assertFalse(parsed["has_hidden_ability"])
        self.assertEqual(parsed["hidden_ability_confidence"], 0.0)

    def test_thin_cyan_ui_accent_is_not_mistaken_for_diamond(self) -> None:
        image = FakeImage(260, 180)
        for x in range(139, 151):
            image.set_pixel(x, 98, (45, 190, 235))
        items = [
            OCRItem("特性：", 0.96, box(20, 88, 80, 108)),
            OCRItem("食草", 0.94, box(92, 88, 128, 108)),
        ]

        self.assertFalse(OCRProcessor.parse(items, image)["has_hidden_ability"])


if __name__ == "__main__":
    unittest.main()
