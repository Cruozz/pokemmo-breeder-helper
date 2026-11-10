# PokeMMO 孵蛋助手

Windows 只读 OCR、素材库存与孵蛋规划工具，同时提供原生 Android APK。两端复用 Python 规划器；不控制游戏、不自动购买、不自动孵蛋。

| 平台 | 当前版本 | 功能 |
| --- | --- | --- |
| Windows | **0.2.42** | OCR、库存、规划与执行、市场行情、离线攻略 |
| Android | **0.9.1** | 实时浮窗 / 截图 / 录屏采集、库存、规划与执行、费用与补购设置 |

下载见 [GitHub Releases](https://github.com/Cruozz/pokemmo-breeder-helper/releases)。APK 文件名包含 Android 版本；Windows 标签和 APK 版本分别维护。Android 需要 Android 8.0+，支持 arm64-v8a / x86_64。覆盖安装保留数据，请勿为升级卸载应用。

手机采集操作见 [手机库存采集与 JSON 互通](docs/mobile-capture.md)：浮窗选择账号与仓位，展开确认入库或最小化自动入库；库存可导出电脑通用 JSON。

## 本次更新

- Android 浮窗可最小化为 48dp 的可拖动按钮，最小化后自动识别入库；展开后手动预览，点“下一只”确认当前结果再继续。
- 结果显示名字、性别、性格和六项个体值：公蓝、母粉、31 绿；自动结果提示持续 5 秒，点击游戏立即消失并穿透点击。
- 保留上一只完整结果，兼容先切游戏／先点软件两种顺序；资料完全相同时继续等待，不把旧页面重复写入库存。
- 浮窗默认 9–10sp，在主界面“浮窗外观”调整不透明度、字号、自适应宽高或手动宽高；变化实时生效。
- Windows 同步发行，孵蛋规则仍为 0.2.39，库存 JSON 格式保持一致，已有路线可继续使用。

## 开发

需要 Python 3.12（Windows OCR 支持 3.10–3.12）。Android 另外需要 JDK 21、Android SDK 36 和 ADB。

```powershell
$python312 = 'C:\Path\to\Python312\python.exe'
./setup.ps1 -Python $python312
$env:PYTHONPATH = "$PWD/vendor"
& $python312 -m pip install --target vendor pytest
& $python312 scripts/test-python.py
```

测试入口会执行全部测试，桌面 Tk 界面用例分别使用新进程，避免重复创建解释器及临时环境设置互相干扰；失败不会自动重试或忽略。逐组结果在 .runtime/test-results/。

Windows 启动与打包：

```powershell
./scripts/build-parallel-guide-host.ps1
& $python312 app.py
./release.ps1 -Python 'C:\Path\to\Python312\python.exe'
```

Android 构建和可选设备测试见 [Android 开发说明](android-app/README.md)。

```powershell
./scripts/build-android.ps1 -Python 'C:\Path\to\Python312\python.exe'
```

## 目录

| 路径 | 用途 |
| --- | --- |
| 根目录 Python 模块 | Windows UI 与两端共享的孵蛋规则 |
| android-app/ | Kotlin / Compose 界面与 Python JSON 桥接 |
| android-app/planner-modules.txt | APK 共享模块清单 |
| tests/ | 共享规则、桌面与移动桥接回归 |
| data/、assets/ | 离线参考数据与界面资源 |
| scripts/ | 数据维护和构建入口 |
| docs/ | 使用、维护及发布记录 |

## 协作与发布

GitHub Actions 在 main 推送及 PR 时执行 Python 回归、Android 单元测试、lint 和 APK 构建。保持 main 可构建；一次提交聚焦一组关联改动，提交前运行 Python 回归、Android 单元测试、lint 和 git diff --check；设备测试使用隔离测试包，按当前任务约定选择模拟器或真机。Windows 与 Android 分别使用版本号，孵蛋规则版本随共享规则同步。更换规则后旧路线暂停核销，库存和已完成结果继续保留，可按原目标重算。

发布步骤及持续约定见 [AGENTS.md](AGENTS.md)。每批修改同时验证 Windows 实际 EXE 和 APK；GitHub 发布使用新标签，不覆盖旧资产。源码中不提交库存、账号、签名密钥或构建目录。

### 实时采集与提前性格

- 安卓“实时浮窗 / 截图 / 录屏采集库存”支持屏幕共享授权后边浏览游戏边采集。浮窗可拖动、收起、暂停、定位识别范围，位置设置支持用户名、仓库号、格位、每仓格数和自动模式。
- 自动模式在完整六项 IV 的画面稳定后保存待核对素材；格位依序增加，满仓进入下一仓。跳格请更新位置；相同名字与 IV 无法仅靠画面可靠区分，手动“下一只”可明确追加另一只。完成后结束采集并核对入库。
- 做 5V / 4V / 3V 时，从 4V / 3V / 2V 的未锁性格步骤提供可选“提前爆出目标性格”，公母均可。实际孵完再登记，父母核销与子代保存后按原目标生成新建议，确认后启用。

提前爆性格后，4V 母固执配 5V 公锁性格；4V 公固执则先把现有母体升到 5V，再由这只公素材携带不变之石收尾。3V、4V 目标使用相同规则。
