"""Real Tk layout regression and optional synthetic visual preview (no user data)."""
import sys
from pathlib import Path
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import UI_COLORS
from mind_map import BreedingMindMap, MindMapNode


def main():
    root = tk.Tk()
    root.title("V0.2.8 卡片验证（模拟素材）")
    root.geometry("1450x850")
    view = BreedingMindMap(root, colors=UI_COLORS, font_family="Microsoft YaHei",
                           on_step_activate=lambda _: None)
    view.pack(fill="both", expand=True)
    children = [MindMapNode(str(i), name, gender=gender, species_id=species,
                           route_role="maternal" if i == 0 else "iv", completed=True,
                           show_checkbox=True, iv_text="3V", iv_values=("31", "7", "31", "28", "24", "31"),
                           detail=f"示例账号-{i} 7-1,8\n{'雄性' if gender == 'M' else '雌性' if gender == 'F' else '无性别'} · 固执 · 梦特已解锁",
                           item_text="本只携带：特防护腕", item_keys=("power-band",),
                           status_text="库存", exclude_material_id=f"fake-{i}")
                for i, (name, gender, species) in enumerate((("水伊布", "M", 134), ("百变怪", "N", 132), ("浮潜鼬", "F", 419)))]
    target = MindMapNode("root", "母体主线 · 5V 随机性格 头目 · 伊布", gender="F",
                         detail="锁定雌性 · 子代 伊布 · 梦特保留 · 遗传技能：祈愿、哈欠",
                         iv_text="5V", iv_values=("31", "X", "31", "31", "31", "31"),
                         item_text="本只携带：无需道具", status_text="启用后执行", nature_text="爆性格：待确认",
                         species_id=133, show_checkbox=True, route_role="maternal", children=children)
    view.root_node = target
    view.nodes_by_key = {node.key: node for node in [target, *children]}
    for scaling in (1.0, 1.5, 2.0):
        root.tk.call("tk", "scaling", scaling)
        for zoom in (0.6, 1.0, 1.8):
            view.zoom = zoom
            view.render(center=False)
            root.update_idletasks()
            for node in [target, *children]:
                x, y = view.positions[node.key]
                detail_item = next(item for item in view.canvas.find_withtag(f"node:{node.key}")
                                   if "mind-detail" in view.canvas.gettags(item))
                assert view.canvas.itemcget(detail_item, "text") == node.detail
                for item in view.canvas.find_withtag(f"node:{node.key}"):
                    if view.canvas.type(item) != "text":
                        continue
                    box = view.canvas.bbox(item)
                    assert box[0] >= x, (zoom, scaling, node.key, "left", box)
                    assert box[2] <= x + view._scaled(view.BASE_NODE_WIDTH), (zoom, scaling, node.key, "right", box)
                    assert box[3] <= y + view._card_height, (zoom, scaling, node.key, "bottom", box)
                box = view.canvas.bbox(detail_item)
                assert box[3] <= y + view._layouts[node.key]["item_y"], (zoom, scaling, "detail/item overlap")
    print("PASS: card text bounds at 9 DPI/zoom combinations; no truncated detail or item overlap")
    if "--show" in sys.argv:
        root.tk.call("tk", "scaling", 1.333333)
        view.zoom = 1.0
        view.render()
        root.mainloop()
    else:
        root.destroy()


if __name__ == "__main__":
    main()
