# PokeMMO 孵蛋助手（只读 OCR MVP）

这是一个 Windows 桌面 MVP，目标是把“你手动点击精灵”和“程序识别、保存、规划”分开：

- 你手动在 PokeMMO 中点击仓库格子和切换仓库页；
- 程序只截取当前可见窗口或读取截图；
- OCR 读取当前精灵的种类、性别、性格、IV、特性和道具；
- 结果保存到本地素材库存；
- 根据已确认库存生成严格保证模式的直接孵蛋配对建议。

程序不会发送键盘/鼠标输入，不会读取 PokeMMO 内存，不会抓取网络，也不会修改游戏客户端。

## 运行

开发运行：

```powershell
$py = 'C:\Users\Chenruo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py app.py
```

首次运行建议按下面的顺序使用：

1. 启动 PokeMMO，打开仓库；在工具中点击“刷新窗口”，选择 PokeMMO 窗口。
2. 点击“截取选中窗口”，再点击“默认左侧信息区”，或在预览图上手动框选信息面板。
3. 你在游戏里手动点击一只精灵后，重新截取当前窗口，点击“识别当前截图”。
4. 检查 OCR 结果，手动补上仓库页、格子和蛋组，再点击“保存到库存”。重复步骤 3–4 扫描需要作为素材的精灵。
5. 在“孵蛋规划”中填写目标种类、性格、目标 IV 和蛋组，生成直接配对方案。

程序不会自动点击格子或翻页；这是为了把输入控制留在你手中，降低触发游戏规则风险。OCR 结果必须人工确认后再保存或用于消耗素材的决定。

## 生成 EXE

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./build.ps1
```

生成的目录位于 `dist/PokeMMO-Breeder-Helper/`，入口是同名 EXE。第一版使用 onedir 模式，方便检查 OCR 模型和依赖；稳定后再考虑 onefile。

如果需要排查启动错误，可以临时使用 `./build.ps1 -Console` 生成带控制台的调试版本；交付版本直接运行 `./build.ps1`。

库存默认保存到：

```text
%LOCALAPPDATA%\PokeMMO-Breeder-Helper\inventory.json
```

## 当前限制

- 目前是直接配对规划器，不是完整多代链式搜索；
- 素材的蛋组需要手动填写，后续可以接入版本化的 PokeMMO 静态数据；
- 蛋招式、Alpha、隐藏特性、闪光、OT、精灵球和服装暂未加入严格规划；
- OCR 结果必须人工确认，不能把低置信度结果直接用于消耗素材的决定。

## 相关开源参考

- [mylis/pokemmo_ocr](https://github.com/mylis/pokemmo_ocr)：截图/视频 OCR 识别精灵信息；
- [PokeMMO-Tools/pokemmo-hub](https://github.com/PokeMMO-Tools/pokemmo-hub)：孵蛋模拟器和蛋招式工具；
- [PokeMMO-Tools/pokemmo-data](https://github.com/PokeMMO-Tools/pokemmo-data)：版本化静态数据，可作为后续蛋组/招式数据库来源。
