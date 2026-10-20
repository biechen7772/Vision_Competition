import io
import sys
import random
from pathlib import Path
import tkinter as tk
from PIL import Image

from model_loader import load_yolo_model
from roi_utils import crop_roi
from roi_storage import resolve_roi_directory, save_roi_image

# 从 config 中引入常量
from config import (
    MAX_IMAGE_WIDTH, 
    MAX_IMAGE_HEIGHT, 
    MODEL_PATH, 
    ROI_BBOX,
    ROI_SAVE_ENABLED,
    ROI_SAVE_DIR,
    SHAPE_COLOR_MAP, 
    RANGE_MAPPING
)

class PlacementTracker:
    """
    缺陷堆叠追踪器：用于确保在 12 次结果中，每一个 1-12 的结果只出现一次。
    这实现了您之前代码中 1-12 随机不重复的逻辑，用于模拟防堆叠。
    """
    def __init__(self, logger):
        self.logger = logger
        # 用于追踪最近 12 个结果，确保不重复
        self.available_numbers = list(range(1, 13))  # 1-12 的可用数字列表
        self.used_numbers = []  # 已使用的数字列表

    def check_placement(self, main_category_index: int) -> int:
        """
        根据缺陷主类别 (1-4) 选定最终的 1-12 结果，并确保不重复。

        Args:
            main_category_index: YOLO 类别映射到的 1-4 主类别编号。

        Returns:
            最终发送给 PLC 的 1-12 结果编号。
        """
        if main_category_index not in RANGE_MAPPING:
            self.logger.log(f"错误：主类别编号 {main_category_index} 不在 RANGE_MAPPING 中，返回默认值 6。")
            return 6

        # 1. 获取该类别对应的可用范围
        target_range = RANGE_MAPPING[main_category_index]
        
        # 2. 找出该范围内尚未使用的数字
        possible_results = [
            num for num in target_range if num in self.available_numbers
        ]

        # 3. 如果该范围内的数字都用完了，执行重置逻辑
        if not possible_results:
            if not self.available_numbers:
                # 整个 1-12 的数字都用完了，开始新一轮
                self.logger.log("所有 1-12 数字已用完，重置追踪器，开始新一轮。")
                self.available_numbers = list(range(1, 13))
                self.used_numbers = []
                # 重新计算可用结果
                possible_results = [
                    num for num in target_range if num in self.available_numbers
                ]
            else:
                # 仅该类别对应的范围用完，但其他数字还有剩余
                self.logger.log(f"主类别 {main_category_index} 对应的范围 {target_range} 已全部使用，随机从剩余可用数字中选取。")
                result = random.choice(self.available_numbers)
                
                self.available_numbers.remove(result)
                self.used_numbers.append(result)
                return result

        # 4. 从可用数字中随机选择一个
        result = random.choice(possible_results)

        # 5. 更新追踪器状态
        self.available_numbers.remove(result)
        self.used_numbers.append(result)

        self.logger.log(f"追踪器状态 - 选中结果: {result}, 范围: {target_range}")
        self.logger.log(f"追踪器状态 - 剩余可用数字: {self.available_numbers}")
        
        return result


class ImageProcessor:
    def __init__(self, image_label, image_info_label, logger):
        self.image_label = image_label
        self.image_info_label = image_info_label
        self.logger = logger
        self.current_image = None
        self.photo_image = None
        self.roi_save_enabled = ROI_SAVE_ENABLED
        self.roi_save_dir = resolve_roi_directory(ROI_SAVE_DIR)
        self.last_saved_roi_path = None
        
        # 初始化防堆叠追踪器
        self.tracker = PlacementTracker(logger)
        
        # 步骤 1: 模型加载 (确保 PyInstaller 兼容性)
        self.model = self._load_model()
        self.logger.log(f"YOLO 分类模型加载完成：{MODEL_PATH}，类别：{self.model.names}")
        for name in ("hole", "stain", "scratch", "damage"):
            self.logger.log(f"货位映射：{name} -> {RANGE_MAPPING[SHAPE_COLOR_MAP[name]]}")
        self.logger.log(f"推理前启用 ROI 裁剪：{ROI_BBOX}")
        if self.roi_save_enabled:
            self.logger.log(f"ROI 图片自动保存目录：{self.roi_save_dir}")
        else:
            self.logger.log("ROI 图片自动保存已关闭")

    def _load_model(self):
        """处理 PyInstaller 打包后的资源路径，并加载模型。"""
        base_path = (
            Path(sys._MEIPASS)
            if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parent
        )
        model_path = base_path / MODEL_PATH
        
        try:
            # 检查模型文件是否存在
            if not model_path.is_file():
                raise FileNotFoundError(f"模型文件未找到：{model_path}")
            
            # 加载 YOLO 模型
            model = load_yolo_model(model_path)
            if model.task != "classify":
                raise ValueError(f"需要分类模型，当前模型任务为 {model.task}")
            unknown_classes = set(model.names.values()) - set(SHAPE_COLOR_MAP)
            if unknown_classes:
                raise ValueError(f"模型类别未配置放置映射：{sorted(unknown_classes)}")
            return model
        except Exception as e:
            self.logger.log(f"模型加载失败: {e}")
            raise RuntimeError(
                f"YOLO 分类模型加载失败，请检查 {MODEL_PATH} 和 PyInstaller 配置。"
            ) from e

    
    def display_image(self, image_data: bytes):
        """显示接收到的图像"""
        try:
            # 将图像数据转换为 PIL 格式
            image = Image.open(io.BytesIO(image_data))
            
            # 保存当前图像数据
            self.current_image = image
            
            # 获取图像尺寸
            width, height = image.size
            self.logger.log(f"准备显示图像: {width}x{height} 像素")
            
            # 调整图像大小以适应显示区域
            scale = min(MAX_IMAGE_WIDTH / width, MAX_IMAGE_HEIGHT / height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            
            # 调整图像大小 (使用 LANCZOS 进行高质量缩放)
            # PIL.Image.LANCZOS 是更推荐的缩放方法
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 转换为 Tkinter 可用的格式
            self.photo_image = tk.PhotoImage(data=self.pil_to_photoimage(resized_image))
            
            # 在标签上显示图像
            self.image_label.config(image=self.photo_image)
            
            # 更新图像信息标签
            self.image_info_label.config(text=f"图像尺寸: {width}x{height} 像素")
            
            self.logger.log("图像已成功显示在界面上")
            
        except Exception as e:
            self.logger.log(f"显示图像错误: {str(e)}")
    
    def pil_to_photoimage(self, pil_image: Image.Image) -> bytes:
        """将 PIL 图像转换为 PhotoImage 格式"""
        # 确保图像是 RGB 或 RGBA 模式
        if pil_image.mode not in ('RGB', 'RGBA'):
            pil_image = pil_image.convert('RGB')
        
        # 创建临时二进制缓冲区
        bio = io.BytesIO()
        
        # 以 PNG 格式保存图像到缓冲区
        pil_image.save(bio, format='PNG')
        
        # 获取二进制数据
        return bio.getvalue()
    
    def process_image(self, image_data: bytes) -> int:
        """
        解码原图、裁剪 ROI、执行缺陷分类，并返回 1-12 的最终结果。

        Args:
            image_data: 接收到的图像二进制数据。

        Returns:
            发送给 PLC 的最终结果编号 (1-12)。
        """
        self.last_saved_roi_path = None
        try:
            self.logger.log("开始图像分析处理...")
            
            # 步骤 1: 将二进制图像数据转换为 PIL 图像
            with Image.open(io.BytesIO(image_data)) as source_image:
                image = source_image.convert('RGB')

            roi_image = crop_roi(image)
            self.logger.log(f"ROI 裁剪完成：{image.size} -> {roi_image.size}")

            # 保存的就是接下来交给模型的 ROI，识别失败的样本也保留。
            if self.roi_save_enabled:
                try:
                    self.last_saved_roi_path = save_roi_image(
                        roi_image, self.roi_save_dir, ROI_BBOX
                    )
                    self.logger.log(f"ROI 图片已保存：{self.last_saved_roi_path}")
                except Exception as save_error:
                    self.logger.log(f"警告：ROI 图片保存失败，继续识别：{save_error}")

            # 步骤 2: 裁剪图直接在内存中送入分类模型；输入尺寸沿用权重配置。
            results = self.model(roi_image, verbose=False)

            # 步骤 3: 分类模型返回 probs，不返回检测框 boxes。
            if not results or results[0].probs is None:
                raise RuntimeError("模型没有返回分类概率")
            probs = results[0].probs
            cls_id = int(probs.top1)
            max_prob_name = self.model.names[cls_id]
            max_prob_value = float(probs.top1conf.item())
            if max_prob_name not in SHAPE_COLOR_MAP:
                raise RuntimeError(f"未配置的模型类别：{max_prob_name}")

            self.logger.log(f"识别到的缺陷: {max_prob_name}, 置信度: {max_prob_value:.2f}")

            # 步骤 4: 映射到 1-4 主类别编号 (PLC 逻辑分类)
            # 使用 config.SHAPE_COLOR_MAP
            main_category_index = SHAPE_COLOR_MAP[max_prob_name]
            
            # 步骤 5: 应用防堆叠追踪器逻辑，生成最终的 1-12 结果
            final_result = self.tracker.check_placement(main_category_index)
            
            self.logger.log(f"图像处理完成，YOLO主类别 -> {main_category_index}, 最终结果值: {final_result}")
            
            return final_result
            
        except Exception as e:
            self.logger.log(f"图像处理过程中发生错误: {str(e)}")
            # 交由 TCP 层返回既有错误码，避免识别失败时发送有效货位编号。
            raise
