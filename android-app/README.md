# Android 开发与验证

原生 Kotlin / Jetpack Compose + Chaquopy Python 3.12。应用 0.9.0（versionCode 16），共享规则 0.2.39；applicationId 保持 com.example.pokemmobreederhelper。

## 环境

- JDK 21，设置 JAVA_HOME。
- Android SDK：platforms;android-36、build-tools、platform-tools；设置 ANDROID_HOME。
- Python 3.12。传入实际解释器路径，不使用 Python 3.13+。
- Gradle Wrapper 已固定版本与 SHA-256，不需要另装 Gradle。

## Windows 构建

从仓库根目录运行：

```powershell
./scripts/build-android.ps1 -Python 'C:\Path\to\Python312\python.exe' -JavaHome 'C:\Path\to\jdk-21'
```

脚本运行 JVM 单元测试、lint 和 APK 构建。APK 在 app/build/outputs/apk/debug/app-debug.apk。

其他系统可在本目录使用 ./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug -PplannerBuildPython=/path/to/python3.12。

## 可选设备测试

本次开发按用户要求不进行真机测试。以下命令是维护者未来自行选择执行的可选步骤。

连接一台开启 USB 或无线调试的设备，先在手机授权 ADB，然后运行：

```powershell
./scripts/build-android.ps1 -Python 'C:\Path\to\Python312\python.exe' -DeviceTests
```

测试构建使用 .devtest 应用 ID，测试库存与正式安装的数据分开。测试使用合成数据；部分测试会重建测试包的库存。请勿对用户包直接运行 connectedDebugAndroidTest，必须传 -PisolatedDeviceTests=true。

测试后重新运行不带 -DeviceTests 的构建，得到可覆盖安装的用户 APK。使用 android run --apks=<apk> --device=<serial> 安装并运行，或 adb install -r <apk>。不要通过卸载解决签名冲突；先导出用户库存，并找回原签名。

## 共享规则与保存格式

planner-modules.txt 是共享模块清单；Gradle 同步清单与根目录 data/。新增依赖必须更新清单，tests/test_android_bundle.py 会在隔离目录导入并执行规划，避免被仓库中的模块掩盖漏包。

Python 的执行字段如果需要保存或回传，必须同时进入 data/Models.kt。特别保留 preparations、maternal_nature_min_ivs、candidate_snapshot 和 planning_options。更新规则版本后，旧规则路线可查看但不能直接核销。

公开行情只作采购可用性和价格参考，缺数据时不推荐未经核验的采购。规划请求中的库存与账号留在本机。成本缺价标为待报价；不同性别比例的费用不能用普通费用覆盖。

## 媒体采集

使用系统 Photo Picker 选择截图或录屏，内置 ML Kit Chinese 16.0.1 模型。InventoryMediaScanner 限制图片解码尺寸并串行处理录屏帧；mobile_capture.py 复用 ocr_engine.py 的几何解析，不加载桌面 RapidOCR、numpy 或图像模型。CaptureStore 将预览与待核对记录保存到私有目录，使用 AtomicFile 更新索引；只有库存保存成功后才移除对应草稿。

操作流程和识别边界见 [手机采集说明](../docs/mobile-capture.md)。JVM 回归检查录屏采样上限、跨批次去重边界和草稿序列化；Python 回归检查 IV 行选择、缺失字段和隔离打包。CaptureImportTest 在隔离包中验证本机 OCR、合成录屏解码和确认入库。

合成 MP4 位于 app/src/androidTest/assets/，不含真实库存。可用 Pillow 和 FFmpeg 重新生成：

```powershell
python ../scripts/generate-capture-fixture.py --font 'C:\Windows\Fonts\msyh.ttc'
```

## 实时屏幕采集

Android 0.9.0 使用 MediaProjection 前台服务与可最小化浮窗，每次开始请求新的系统授权。展开时冻结稳定识别预览，点“下一只”原子保存并推进仓位，再等待新精灵；“保存并结束”保存最后一只。最小化时自动入库，结果提示 5 秒或窗外触摸关闭。

LiveCaptureGate 比较名字、性别、性格、六项 IV 等资料，连续稳定后才接收；下一只、空白过渡、暂停和旋转都不清除上一只记录。已知字段只在缺失／出现之间变化不算新精灵；完全一致的精灵无法仅凭画面区分，会继续等待。

CaptureResultView 共用公蓝／母粉／31 绿渲染，未知字段明确显示待确认。CaptureOverlay 的按钮监听 ACTION_OUTSIDE；提示窗使用 FLAG_NOT_TOUCHABLE，alpha 不超过系统 maximumObscuringOpacityForTouch。浮窗／提示以及短暂保留的旧矩形均从整屏 OCR 画面遮罩。OverlayAppearance 在主界面持久化透明度、字号、自适应或手动尺寸，服务运行时即时更新。

InventoryRepository 保留共享状态与原子写锁，直接入库记录 verified=false，仓位冲突保留草稿并暂停。静态帧精确复用 OCR，250ms 采样、500ms 稳定窗口。手动确认时保存冻结结果，防止游戏先切页后误存下一只。LiveCaptureJourneyTest 通过隔离合成页面验证真实屏幕授权、两种下一只顺序、性别／性格变化、去重、仓位翻页、提示超时及触摸、停止；OverlayAppearanceTest 验证设置与颜色。合成页面仅在 -PisolatedDeviceTests=true 时编入，正式 APK 不包含测试入口。
