"""固定相机图像的 ROI 裁剪，可供数据集制作和在线推理共用。"""

from config import ROI_BBOX, ROI_SOURCE_SIZE


def crop_roi(image, bbox=ROI_BBOX, source_size=ROI_SOURCE_SIZE):
    """裁剪物料区域；拒绝尺寸不匹配或越界，避免 Pillow 自动补黑边。"""
    if image.size != source_size:
        raise ValueError(f"ROI 原图尺寸应为 {source_size}，实际为 {image.size}")

    left, top, right, bottom = bbox
    width, height = image.size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"ROI {bbox} 超出图像范围 {image.size} 或区域为空")

    return image.crop(bbox)
