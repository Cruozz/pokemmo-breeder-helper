import unittest
from app import UI_COLORS
from execution import ExecutionStep
from execution_view import step_display_gender, execution_map
from mind_map import BreedingMindMap, MindMapNode
from models import Monster
from test_route_colors import color_fixture, walk
from species_data import get_species_database


class CardGenderTests(unittest.TestCase):
    def test_background_uses_sex_not_route_or_status(self):
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.colors = UI_COLORS
        for role in ("maternal", "nature", "iv", "egg_move", ""):
            for status in ("pending", "inventory", "completed", "purchase"):
                for gender, color in (("M", "#DBEAFE"), ("F", "#FCE7F3"), ("N", "#F8FAFC"), ("", "#F8FAFC")):
                    node = MindMapNode("test", "精灵", gender=gender, route_role=role, kind=status)
                    self.assertEqual(view._node_palette(node)[0], color)

    def test_planned_actual_random_and_override_sex(self):
        step = ExecutionStep(1, "a", "b", "a", "b", Monster(id="child", gender="M"), planned_gender="F")
        self.assertEqual(step_display_gender(step), "F")
        step.gender_override = "M"
        self.assertEqual(step_display_gender(step), "M")
        step.gender_override = "random"
        self.assertEqual(step_display_gender(step), "")
        step.completed = True
        self.assertEqual(step_display_gender(step), "M")

    def test_execution_inventory_names_and_sex_are_preserved(self):
        _, plan, inventory = color_fixture()
        root = execution_map(plan, inventory, set(), get_species_database())
        for monster in inventory:
            leaf = next(node for node in walk(root) if node.key.endswith("-" + monster.id))
            self.assertEqual(leaf.title, monster.species)
            self.assertEqual(leaf.gender, monster.gender)
