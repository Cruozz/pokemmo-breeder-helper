import unittest

from app import UI_COLORS
from chain_planner import ChainCandidate, ChainState, SpeciesProfile, _forced_child
from execution import ExecutionPlan, build_execution_plan
from execution_view import execution_map
from mind_map import BreedingMindMap, MindMapNode
from models import Monster
from route_roles import ROUTE_PALETTES, candidate_route_roles
from species_data import get_species_database
from unittest.mock import Mock


def color_fixture(maternal_skill=False):
    def leaf(key, species, gender, mask, nature="", moves=()):
        monster = Monster(id=key, species=species, gender=gender, nature=nature,
                          ivs=[31 if mask & (1 << i) else None for i in range(6)],
                          moves=list(moves), egg_groups=["陆上"])
        return ChainState(species=species, gender=gender, egg_groups=("陆上",), mask=mask,
                          has_nature=bool(nature), nature=nature, is_alpha=False, used_ids=frozenset({key}),
                          generation=0, breeds=0, braces=0, everstones=0, leaf=monster,
                          inherited_moves=frozenset(moves))

    eevee = SpeciesProfile("伊布", "伊布", ("陆上",), False, ("F", "M"))
    meowth = SpeciesProfile("喵喵", "喵喵", ("陆上",), False, ("F", "M"))
    mother = leaf("mother", "伊布", "F", 3, moves=("祈愿",) if maternal_skill else ())
    skill = _forced_child(leaf("skill-f", "伊布", "F", 2), leaf("skill-m", "伊布", "M", 4, moves=() if maternal_skill else ("祈愿",)),
                          eevee, "M", 1, 2)
    body = _forced_child(mother, skill, eevee, "F", 0, 2)
    nature = _forced_child(leaf("nature-f", "喵喵", "F", 1, "固执"), leaf("nature-m", "阿柏蛇", "M", 3),
                           meowth, "M", brace_b=1, everstone_a=True)
    root = _forced_child(body, nature, eevee, "F", brace_a=2, everstone_b=True)
    candidate = ChainCandidate(root, [31, 31, 31, None, None, None], "固执", "F",
                               target_species="伊布", offspring_species="伊布", nature_strategy="strict",
                               nature_phase="strict", target_moves=("祈愿",))
    plan = build_execution_plan(candidate)
    inventory = [Monster.from_dict(value) for value in plan.materials.values()]
    return candidate, plan, inventory


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


class RouteColorTests(unittest.TestCase):
    def test_maternal_skill_continues_to_final_product_after_reload_and_collapse(self):
        candidate, plan, inventory = color_fixture(maternal_skill=True)
        plan = ExecutionPlan.from_dict(plan.to_dict())
        body_step = next(step for step in plan.steps if step.child.gender == "F" and step.number != plan.steps[-1].number)
        for completed in (False, True):
            body_step.completed = completed
            node = execution_map(plan, inventory, set(), get_species_database())
            self.assertEqual(node.route_moves, ("祈愿",))
            body = next(item for item in walk(node) if item.step_number == body_step.number)
            self.assertEqual(body.route_role, "maternal")
            self.assertEqual(body.route_moves, ("祈愿",))
            if not completed:
                mother = next(item for item in walk(node) if item.key.endswith("-mother"))
                self.assertEqual(mother.route_moves, ("祈愿",))
                self.assertTrue(all(not item.route_moves for item in walk(node) if item.route_role != "maternal"))
            else:
                self.assertFalse(body.children)

    def test_overlay_edges_only_follow_shared_selected_skills(self):
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.colors, view.zoom, view.canvas = UI_COLORS, 1, Mock()
        view._card_height = 152
        root = MindMapNode("root", "母体", route_role="maternal", route_moves=("祈愿",), children=[
            MindMapNode("source", "母体素材", route_role="maternal", route_moves=("祈愿",)),
            MindMapNode("other", "无关技能素材", route_role="iv", route_moves=("哈欠",)),
        ])
        view.positions = {"root": (200, 0), "source": (0, 230), "other": (400, 230)}
        view._draw_edges(root)
        skill_edges = [call for call in view.canvas.create_line.call_args_list if call.kwargs["tags"][0].startswith("skill-edge:")]
        self.assertEqual(len(skill_edges), 1)
        self.assertEqual(skill_edges[0].kwargs["tags"], ("skill-edge:source",))
        self.assertEqual(skill_edges[0].kwargs["fill"], ROUTE_PALETTES["egg_move"][1])

    def test_multi_role_frame_retains_both_colors_when_selected_and_zoomed(self):
        for zoom in (0.6, 1.0, 1.8):
            view = BreedingMindMap.__new__(BreedingMindMap)
            view.colors, view.zoom, view.canvas = UI_COLORS, zoom, Mock()
            view.font_family = "Arial"
            view.positions = {"skill": (30, 30)}
            view.selected_key = "skill"
            view._draw_iv_row = Mock()
            view._draw_node_media = Mock()
            view._draw_chip = Mock(return_value=30)
            node = MindMapNode("skill", "性格手＋技能", route_role="nature", route_moves=("祈愿",), status_text="已完成")
            view.nodes_by_key = {node.key: node}
            view.canvas.bbox.return_value = (0, 0, 150, 20)
            view._layouts = {node.key: view._text_layout(node)}
            view._card_height = view._layouts[node.key]["height"]
            view._draw_node(node)
            cards = view.canvas.create_rectangle.call_args_list
            self.assertEqual(cards[0].kwargs["outline"], ROUTE_PALETTES["egg_move"][1])
            self.assertEqual(cards[1].kwargs["outline"], ROUTE_PALETTES["nature"][1])
            self.assertLess(cards[0].args[0], cards[1].args[0])
            view._refresh_selection()
            self.assertEqual(view.canvas.itemconfigure.call_args.kwargs["outline"], ROUTE_PALETTES["nature"][1])

    def test_preview_and_execution_classify_entire_branches_identically_after_reload(self):
        candidate, plan, inventory = color_fixture()
        roles = candidate_route_roles(candidate)
        self.assertEqual(roles[id(candidate.root)], "maternal")
        self.assertEqual(roles[id(candidate.root.action.parent_a)], "maternal")
        self.assertEqual(roles[id(candidate.root.action.parent_b)], "nature")
        for candidate in (candidate, ChainCandidate.from_dict(candidate.to_dict())):
            plan = ExecutionPlan.from_dict(build_execution_plan(candidate).to_dict())
            node = execution_map(plan, inventory, set(), get_species_database())
            by_key = {item.key: item for item in walk(node)}
            self.assertEqual(node.route_role, "maternal")
            self.assertEqual(node.route_moves, ("祈愿",))
            for material_id, expected in (("mother", "maternal"), ("skill-f", "iv"),
                                          ("skill-m", "iv"), ("nature-f", "nature"), ("nature-m", "nature")):
                material = next(item for key, item in by_key.items() if key.endswith("-" + material_id))
                self.assertEqual(material.route_role, expected)
                self.assertEqual(material.route_moves, ("祈愿",) if material_id == "skill-m" else ())
            self.assertEqual({item.route_role for item in walk(node)}, {"maternal", "nature", "iv"})

    def test_completed_and_expanded_sources_keep_route_colors(self):
        _candidate, plan, inventory = color_fixture()
        before = execution_map(plan, inventory, set(), get_species_database())
        plan.steps[0].completed = True
        expanded = {(plan.id, 1)}
        after = execution_map(plan, inventory, expanded, get_species_database())
        self.assertEqual({node.key: node.route_role for node in walk(before)},
                         {node.key: node.route_role for node in walk(after)})
        collapsed = execution_map(plan, inventory, set(), get_species_database())
        done = next(node for node in walk(collapsed) if node.step_number == 1)
        self.assertEqual(done.children, [])
        self.assertEqual(done.route_role, "iv")

    def test_random_nature_hand_colors_all_pre_everstone_ancestors(self):
        candidate, _plan, _inventory = color_fixture()
        candidate.root = candidate.root.action.parent_b
        candidate.nature_phase = "gamble_lower"
        self.assertEqual(set(candidate_route_roles(candidate).values()), {"nature"})

    def test_node_edges_and_selection_keep_role_color_independent_of_progress(self):
        view = BreedingMindMap.__new__(BreedingMindMap)
        view.colors = UI_COLORS
        view.zoom = 1
        view._card_height = 152
        view.canvas = Mock()
        root = MindMapNode("root", "成品", route_role="maternal", children=[
            MindMapNode("nature", "性格手", route_role="nature", kind="completed"),
            MindMapNode("skill", "技能", route_role="egg_move", kind="purchase"),
        ])
        view.positions = {"root": (200, 0), "nature": (0, 230), "skill": (400, 230)}
        view.nodes_by_key = {node.key: node for node in walk(root)}
        view.selected_key = "skill"
        view._draw_edges(root)
        self.assertEqual([call.kwargs["fill"] for call in view.canvas.create_line.call_args_list
                          if call.kwargs["tags"][0].startswith("edge:")],
                         [ROUTE_PALETTES["nature"][1], ROUTE_PALETTES["egg_move"][1]])
        view._refresh_selection()
        self.assertEqual(view.canvas.itemconfigure.call_args.kwargs["outline"], ROUTE_PALETTES["egg_move"][1])
        self.assertEqual(view._node_palette(root.children[0])[1], ROUTE_PALETTES["nature"][1])


if __name__ == "__main__":
    unittest.main()
