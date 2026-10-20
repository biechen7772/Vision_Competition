# 错误代码常量定义
ERROR_INCOMPLETE_IMAGE = -1
ERROR_CONNECTION_TIMEOUT = -2
ERROR_COMMUNICATION_ERROR = -3
ERROR_CONNECTION_REFUSED = -4

# 超时时间常量(秒)
SOCKET_TIMEOUT = 15

# 通信协议常量定义
PLC_CMD_CAMERA_TRIGGER = "Camera:Trigger=True"  # 固定格式
VIRTUAL_CMD_CAMERA_START = "Camera:Start=True"  # 发送给Virtual的命令

# 发送给PLC的响应格式
PLC_RESPONSE_RESULT = "Camera:Result={}"  # 使用格式化字符串

# 图像显示设置
MAX_IMAGE_WIDTH = 400
MAX_IMAGE_HEIGHT = 300

# 日志设置
MAX_LOG_LENGTH = 150
LOG_TIMEOUT = 0.1  # 日志缓冲区清空超时时间(秒)

# 缺陷分类模型配置
MODEL_PATH = "best1.pt"

# 与 build_dataset.py 保持一致：(左, 上, 右, 下)，右/下边界不包含在裁剪结果中
ROI_BBOX = (1248, 800, 2712, 2264)
ROI_SOURCE_SIZE = (4096, 3000)

# 保存模型预处理前的 ROI 图，方便检查裁剪范围。
# 相对路径以源码目录（开发运行）或 EXE 所在目录（打包运行）为起点。
ROI_SAVE_ENABLED = True
ROI_SAVE_DIR = "roi_images"

# 缺陷种类映射 (YOLO类别名 -> 1-4主类别编号)
# 这个映射对应 image_processor.py 中的逻辑
SHAPE_COLOR_MAP = {
    'hole': 1,     # 孔洞 -> 结果 1-3
    'stain': 2,    # 污渍 -> 结果 4-6
    'scratch': 3,  # 划痕 -> 结果 7-9
    'damage': 4,   # 破损 -> 结果 10-12
    'Annulus': 1,   # 空心缺陷类 -> 对应结果 1-3
    'Spot': 2,      # 黑点 -> 对应结果 4-6
    'Curve': 3,     # 曲线类 -> 对应结果 7-9
    'Gap': 4        # 缺口 -> 对应结果 10-12
}

# 最终结果范围映射 (1-4主类别编号 -> 1-12随机结果范围)
# PLC期望的最终结果将从这些范围内随机选择
# 按本轮识别日志、真实 ROI 类别及平台货架截图校准：从左到右为孔洞、污渍、划痕、破损。
RANGE_MAPPING = {
    1: [1, 2, 3],     # 孔洞 / Annulus
    2: [4, 5, 6],     # 污渍 / Spot
    3: [7, 8, 9],     # 划痕 / Curve
    4: [10, 11, 12]   # 破损 / Gap
}
