import io
import os
import sys
import random
import numpy as np
import tkinter as tk
from PIL import Image

# 引入 YOLO 模型类
from ultralytics import YOLO

# 从 config 中引入常量
from config import (
    MAX_IMAGE_WIDTH, 
    MAX_IMAGE_HEIGHT, 
    MODEL_PATH, 
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
        
        # 初始化防堆叠追踪器
        self.tracker = PlacementTracker(logger)
        
        # 步骤 1: 模型加载 (确保 PyInstaller 兼容性)
        self.model = self._load_model()
        self.logger.log("YOLOv8 模型加载完成。")

    def _load_model(self):
        """处理 PyInstaller 打包后的资源路径，并加载模型。"""
        model_path = MODEL_PATH
        
        if getattr(sys, 'frozen', False):
            # 运行在 PyInstaller 打包后的环境中
            base_path = sys._MEIPASS
            model_path = os.path.join(base_path, MODEL_PATH)
        
        try:
            # 检查模型文件是否存在
            if not os.path.exists(model_path):
                self.logger.log(f"错误: 模型文件未找到于路径: {model_path}")
                # 尝试使用相对路径作为后备（仅在非打包环境中可能工作）
                model_path = MODEL_PATH
            
            # 加载 YOLO 模型
            model = YOLO(model_path)
            return model
        except Exception as e:
            self.logger.log(f"模型加载失败: {e}")
            raise RuntimeError("YOLO 模型加载失败，请检查 best.pt 文件和 PyInstaller 配置。")

    
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
        处理接收到的图像，执行缺陷检测，应用防堆叠逻辑，并返回 1-12 的最终结果。

        Args:
            image_data: 接收到的图像二进制数据。

        Returns:
            发送给 PLC 的最终结果编号 (1-12)。
        """
        try:
            self.logger.log("开始图像分析处理...")
            
            # 步骤 1: 将二进制图像数据转换为 PIL 图像
            image = Image.open(io.BytesIO(image_data)).convert('RGB')
            
            # 步骤 2: 执行 YOLOv8 推理
            # results 对象包含检测到的所有目标
            results = self.model(image, verbose=False)
            
            # 初始化最高置信度的类别信息
            max_prob_name = None
            max_prob_value = 0.0
            
            # 步骤 3: 提取最高置信度的缺陷类别 (假设只关注单个最主要的缺陷)
            if results and results[0].boxes:
                # 遍历检测到的所有框
                for box in results[0].boxes:
                    conf = box.conf.cpu().numpy()[0]
                    cls_id = int(box.cls.cpu().numpy()[0])
                    
                    if conf > max_prob_value:
                        max_prob_value = conf
                        # 获取类别名称
                        max_prob_name = self.model.names[cls_id]

            if not max_prob_name:
                self.logger.log("模型未检测到有效缺陷 (置信度低于阈值或无目标)。")
                # 如果未检测到缺陷，默认为 'Gap' (缺口)，对应结果 1-3
                max_prob_name = 'Gap' 
            
            self.logger.log(f"检测到的主要缺陷: {max_prob_name}, 置信度: {max_prob_value:.2f}")

            # 步骤 4: 映射到 1-4 主类别编号 (PLC 逻辑分类)
            # 使用 config.SHAPE_COLOR_MAP
            main_category_index = SHAPE_COLOR_MAP.get(max_prob_name, 4) # 默认使用 4 (Gap/缺口)
            
            # 步骤 5: 应用防堆叠追踪器逻辑，生成最终的 1-12 结果
            final_result = self.tracker.check_placement(main_category_index)
            
            self.logger.log(f"图像处理完成，YOLO主类别 -> {main_category_index}, 最终结果值: {final_result}")
            
            return final_result
            
        except Exception as e:
            self.logger.log(f"图像处理过程中发生错误: {str(e)}")
            # 如果出现严重异常，返回默认的安全结果 6
            return 6