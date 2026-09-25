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

# 缺陷检测模型配置 (新增)
MODEL_PATH = "best.pt"

# 缺陷种类映射 (YOLO类别名 -> 1-4主类别编号)
# 这个映射对应 image_processor.py 中的逻辑
SHAPE_COLOR_MAP = {
    'Annulus': 1,   # 空心缺陷类 -> 对应结果 7-9
    'Spot': 2,      # 黑点 -> 对应结果 4-6
    'Curve': 3,     # 曲线类 -> 对应结果 10-12
    'Gap': 4        # 缺口 -> 对应结果 1-3
}

# 最终结果范围映射 (1-4主类别编号 -> 1-12随机结果范围)
# PLC期望的最终结果将从这些范围内随机选择
RANGE_MAPPING = {
    4: [1, 2, 3],     # 缺陷 4 (Gap/缺口) -> 结果 1, 2, 3 中选
    2: [4, 5, 6],     # 缺陷 2 (Spot/黑点) -> 结果 4, 5, 6 中选
    1: [7, 8, 9],     # 缺陷 1 (Annulus/空心) -> 结果 7, 8, 9 中选
    3: [10, 11, 12]   # 缺陷 3 (Curve/曲线) -> 结果 10, 11, 12 中选
}