"""Classify branches identically in candidate previews and saved execution maps."""
from dataclasses import dataclass, field


ROUTE_LABELS = {
    "maternal": "母体主线",
    "nature": "性格手",
    "egg_move": "遗传技能",
    "iv": "IV 素材",
}

# Fill, border/edge, text. Progress remains visible in the separate status chip.
ROUTE_PALETTES = {
    "maternal": ("#EFF6FF", "#2563EB", "#1E3A8A"),
    "nature": ("#F5F3FF", "#7C3AED", "#4C1D95"),
    "egg_move": ("#FFF7ED", "#C2410C", "#7C2D12"),
    "iv": ("#F8FAFC", "#64748B", "#334155"),
}


@dataclass
class RouteSource:
    key: object
    gender: str = ""
    ditto: bool = False
    moves: frozenset[str] = frozenset()
    parents: list[tuple["RouteSource", str]] = field(default_factory=list)


def classify_routes(root: RouteSource, *, nature_phase: str = "", target_moves=()) -> dict:
    """Classify the structural role; inherited skills are an independent layer."""
    roles = {}

    def visit(source, role):
        roles[source.key] = role
        if not source.parents:
            return
        ordinary = [parent for parent, _item in source.parents if not parent.ditto]
        mother = next((parent for parent in ordinary if parent.gender == "F"),
                      ordinary[0] if ordinary else None)
        for parent, item in source.parents:
            child_role = role if role == "nature" else "iv"
            if parent is mother and role == "maternal":
                child_role = "maternal"
            elif parent is not mother:
                if item == "不变之石":
                    child_role = "nature"
            visit(parent, child_role)

    visit(root, "nature" if nature_phase in {"gamble_upper", "gamble_lower"} else "maternal")
    return roles


def candidate_route_roles(candidate) -> dict[int, str]:
    def source(state):
        from chain_planner import is_ditto
        result = RouteSource(id(state), state.gender, is_ditto(state.species), state.inherited_moves)
        if state.action:
            result.parents = [(source(state.action.parent_a), state.action.item_a),
                              (source(state.action.parent_b), state.action.item_b)]
        return result

    return classify_routes(source(candidate.root), nature_phase=candidate.nature_phase,
                           target_moves=candidate.target_moves)
