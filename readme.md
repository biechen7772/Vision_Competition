# Vision Demo

面向 VirtualNext Smart 仿真平台的 Python 视觉程序。项目加载已训练的 YOLO 分类模型，完成相机取图、ROI 裁剪、缺陷识别和货位分配，并通过 TCP 将结果交给控制程序。机械臂的运动、抓取和放置由平台配套控制程序执行。

## 已实现的功能

- **TCP 通信**：作为服务器接收控制端的拍照触发，同时作为客户端连接平台相机；支持分段接收图像、触发命令半包处理、超时和错误返回。
- **ROI 裁剪**：将固定尺寸原图中的物料区域裁剪出来，供模型分类使用。
- **模型推理**：当前使用 `best1.pt`，按类别名称映射货位，适应不同模型的类别索引顺序。
- **图片保存**：自动保存无损 ROI 图片，按日期分类，方便检查裁剪范围和识别效果。
- **货位分配**：记录已分配的货位，在同类未使用的位置中随机选位。
- **图形界面**：显示接收的原图、通信参数和操作日志；日志、图片更新通过队列交给主线程，连接和停止服务在后台执行。
- **离线验证**：提供模型推理自测、真实窗口的连续通信自测和单元测试。

## 工作流程与货位映射

```text
控制端通过 TCP 向 Python 发送拍照触发命令 Camera:Trigger=True
→ Python 通过另一条 TCP 连接向平台相机发送取图命令 Camera:Start=True
→ 平台相机通过 TCP 返回 4 字节大端图像长度及原图数据
→ Python 按长度完整接收图像数据
→ 本地处理：解码原图 → ROI 裁剪与保存 → YOLO 分类 → 按类别名称分配货位
→ Python 通过控制端的 TCP 连接返回 Camera:Result=<货位编号>
→ 控制程序接收结果并执行抓取、搬运和放置
```

其中有两条 TCP 连接：控制端连接 Python 视觉服务器（默认端口 `50050`），Python 作为客户端连接平台相机服务（默认端口 `5001`）。TCP 用于传递命令、图片和结果；图片完整接收后的解码、裁剪、保存及分类在本地完成。同机使用 `127.0.0.1` 连接时也属于 TCP 通信。

当前已校准的货架从左到右为：

| 类别 | 模型类别名称 | 返回货位编号 |
| --- | --- | --- |
| 孔洞 | hole | 1、2、3 |
| 污渍 | stain | 4、5、6 |
| 划痕 | scratch | 7、8、9 |
| 破损 | damage | 10、11、12 |

`config.py` 中，`SHAPE_COLOR_MAP` 将类别名称转换成内部编号，`RANGE_MAPPING` 再将内部编号转换成可选货位。发送给控制端的是最终的 **1～12 货位编号**，不是模型的 0～3 类别索引。

通信格式：控制端发送 `Camera:Trigger=True`，Python 向相机发送 `Camera:Start=True`，最后返回 `Camera:Result=<货位编号>`。相机图片按“4 字节大端长度 + 图片数据”接收；处理失败时返回负数错误码。

## 主要文件

| 文件 | 作用 |
| --- | --- |
| `main.py`、`main_window.py` | 程序入口、视觉界面及服务启动／停止 |
| `tcp_communication.py` | 控制端与相机的 TCP 通信 |
| `image_processor.py` | 图像处理、模型调用和货位分配 |
| `config.py` | 模型路径、ROI、图片保存和类别／货位配置 |
| `model_loader.py` | 权重加载及训练环境路径的跨平台兼容 |
| `roi_utils.py`、`roi_storage.py` | ROI 裁剪与图片保存 |
| `logger.py`、`ui_dispatcher.py` | 日志输出及主线程界面更新 |
| `VisionApp.spec`、`packaging_runtime_hook.py` | EXE 打包配置及启动时的离线运行设置 |
| `packaging_self_test.py`、`gui_self_test.py`、`tests/` | 功能自测与回归测试 |

## 源码运行与常用配置

在已安装依赖的 Python 环境中，从项目根目录运行：

```powershell
python main.py
```

先启动仿真平台和相机服务，再启动视觉程序。视觉程序会自动尝试连接相机并监听控制端连接；若连接失败，可在平台就绪后点击“启动服务”。确认视觉服务就绪后，再连接、运行配套控制程序。

| 配置项 | 当前值 |
| --- | --- |
| 模型 | `best1.pt` |
| Python 监听地址 | `0.0.0.0:50050` |
| 平台相机地址 | `127.0.0.1:5001` |
| 通信超时 | 默认 15 秒，可在界面调整 |
| 相机原图 | 4096 × 3000 |
| ROI 左、上、右、下边界 | `(1248, 800, 2712, 2264)` |
| ROI 裁剪尺寸 | 1464 × 1464 |
| ROI 自动保存 | `ROI_SAVE_ENABLED = True` |

同机控制程序应连接 `127.0.0.1:50050`；`0.0.0.0` 是监听地址。这里的超时属于视觉程序的通信设置，不是整轮机械臂动作的时间限制。

ROI 图片保存在源码目录或 EXE 所在目录的 `roi_images/日期/` 下，文件夹自动创建。保存的是模型预处理前的裁剪图，当前模型随后按 1024 × 1024 输入进行预处理。更多说明见 [ROI 图片保存说明](./ROI图片保存说明.md)。

## 打包方法与作用

打包将 Python 程序、模型和所需运行库合成为 `VisionApp.exe`，方便通过 U 盘部署到平台电脑；目标电脑无需另装 Python，也无需单独复制权重。

### 1. 准备打包环境

使用 Windows 64 位 Python 环境，安装 `torch`、`torchvision`、`ultralytics`、`Pillow` 和 `PyInstaller`。本项目已验证的版本为 Python 3.9.23、CPU 版 PyTorch 2.8.0、torchvision 0.23.0、Ultralytics 8.3.213、Pillow 11.3.0、PyInstaller 6.16.0。

CPU 便携版应使用 **CPU 版 PyTorch 环境**打包。PyInstaller 不会自动将 CUDA 环境转换为 CPU 环境；不同依赖环境会影响 EXE 体积和运行要求。

确认当前环境及 `config.py` 的 `MODEL_PATH`，并确保对应权重文件位于项目目录。下面的命令均在项目根目录、所选 Python 环境中执行。

### 2. 生成 EXE

```powershell
python -m PyInstaller --noconfirm --distpath "dist\VisionApp_release" VisionApp.spec
```

输出为 `dist/VisionApp_release/VisionApp.exe`，中间构建文件位于 `build/`。可更换输出目录名来区分不同版本。

- `VisionApp.spec` 自动读取 `config.py` 指定的模型，收集运行依赖，并生成单文件、无控制台窗口的 EXE。
- `packaging_runtime_hook.py` 设置第三方库的配置目录，并关闭 Ultralytics 自动安装依赖。
- 修改模型、ROI 或货位映射后，需要重新打包；已经生成的 EXE 不会随源码修改而更新。

### 3. 验证与整理便携包
**（这部分看不看无所谓，主要是检验用，目前已经可以跑通了就不用看了）**

用 PowerShell 等待两项自测完成，并查看对应 JSON 报告中的 `ok`：

```powershell
Start-Process -FilePath ".\dist\VisionApp_release\VisionApp.exe" -ArgumentList '--self-test ".\dist\VisionApp_release\运行检查.json"' -Wait
Start-Process -FilePath ".\dist\VisionApp_release\VisionApp.exe" -ArgumentList '--gui-self-test ".\dist\VisionApp_release\界面通信检查.json"' -Wait
```

第一项使用真实权重和合成图片，检查模型加载、ROI、图片保存及单次 TCP 结果返回。第二项使用真实窗口和本机模拟相机／控制端，检查 12 次通信循环及停止服务；循环阶段使用固定分类结果，不验证识别准确率。两项都不需要连接真实仿真平台。

项目回归测试可单独执行：

```powershell
python -m unittest discover -s tests -v
```

现成便携包中的配套文件作用如下：

| 文件 | 作用 |
| --- | --- |
| `检查运行环境.bat` | 调用真实模型自测，生成 `运行检查.json` |
| `检查界面与通信.bat` | 调用窗口／通信自测，生成 `界面通信检查.json` |
| `使用说明.txt`、`ROI图片保存说明.md` | 平台连接、运行和图片保存说明 |
| `模型信息.json`、`SHA256.txt` | 记录模型／货位信息及 EXE 校验值 |
| `本机验证结果.json`、`本机界面通信验证.json` | 该版本构建时的验证记录 |

这些配套文件和 ZIP 由便携包整理步骤生成，单独执行 PyInstaller 只会生成 EXE。重新制作便携包时，可复用通用检查脚本和说明；模型信息、校验值及验证报告应按新版本重新生成。

需要压缩传输时执行：

```powershell
Compress-Archive -Path ".\dist\VisionApp_release" -DestinationPath ".\dist\VisionApp_release.zip" -Force
```

当前最新已有便携包为 `dist/VisionApp_best1_ThreadFix_20261015.zip`，包含货位校准及界面线程／TCP 半包修复。

## 平台使用与当前边界

- 将便携包通过 U 盘复制到平台电脑的本地磁盘并解压，再在平台中导入其中的 `VisionApp.exe`。单文件 EXE 每次启动都需要解压运行库，请等待界面出现。
- 每轮重新开始时，同步重置仿真场景并关闭、重启视觉程序；单独“停止服务”不会清空货位记录。货位记录表示已分配位置，不代表机械臂已放置成功。
- 当前某类三个货位耗尽、其他类别仍有空位时，选位逻辑会从其他剩余货位中选择，这个跨类别兜底分支仍需完善。
- 本地自测验证视觉侧功能与通信。平台实际抓放和中途停机仍需结合控制程序的动作状态、反馈信号及日志联调，不能仅凭视觉端“发送成功”认定动作已经完成。
