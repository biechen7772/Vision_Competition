"""验证在线裁剪、分类结果映射及跨平台权重加载，无需启动界面或仿真。"""

import hashlib
import io
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import torch
from PIL import Image, ImageDraw

from config import MODEL_PATH, ROI_BBOX, ROI_SOURCE_SIZE
from image_processor import ImageProcessor
from model_loader import load_yolo_model
from roi_utils import crop_roi
from roi_storage import resolve_roi_directory
from tcp_communication import TCPCommunication


NAMES = {0: "stain", 1: "hole", 2: "scratch", 3: "damage"}


class ForeignPath:
    """在 Windows 上生成包含 Linux PosixPath 的测试权重。"""

    def __reduce__(self):
        return pathlib.PosixPath, ("/datasets", "example")


class ROIClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Image.new("RGB", ROI_SOURCE_SIZE, "blue")
        left, top, right, bottom = ROI_BBOX
        ImageDraw.Draw(cls.source).rectangle(
            (left, top, right - 1, bottom - 1), fill="red"
        )
        cls.source.putpixel((left, top), (255, 255, 0))
        cls.source.putpixel((right - 1, bottom - 1), (255, 0, 255))
        buffer = io.BytesIO()
        cls.source.save(buffer, format="PNG")
        cls.image_data = buffer.getvalue()

    def setUp(self):
        self.roi_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.roi_directory.cleanup)
        directory_patch = patch("image_processor.ROI_SAVE_DIR", self.roi_directory.name)
        directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.logger = Mock()
        self.model = Mock(task="classify", names=NAMES)
        with patch("image_processor.load_yolo_model", return_value=self.model):
            self.processor = ImageProcessor(None, None, self.logger)

    def test_roi_preserves_exact_pixels_and_original(self):
        cropped = crop_roi(self.source)
        self.assertEqual(cropped.size, (1464, 1464))
        self.assertEqual(cropped.getpixel((0, 0)), (255, 255, 0))
        self.assertEqual(cropped.getpixel((1463, 1463)), (255, 0, 255))
        self.assertEqual(cropped.getpixel((700, 700)), (255, 0, 0))
        self.assertEqual(self.source.size, (4096, 3000))
        self.assertEqual(self.source.getpixel((0, 0)), (0, 0, 255))

    def test_four_classes_receive_roi_and_use_correct_unique_slots(self):
        expected_slots = {0: {4, 5, 6}, 1: {1, 2, 3}, 2: {7, 8, 9}, 3: {10, 11, 12}}
        assigned = []
        for class_id, slots in expected_slots.items():
            self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
                top1=class_id, top1conf=torch.tensor(0.9)
            ))]
            class_slots = {
                self.processor.process_image(self.image_data) for _ in range(3)
            }
            self.assertEqual(class_slots, slots)
            assigned.extend(class_slots)
        self.assertEqual(set(assigned), set(range(1, 13)))
        for call in self.model.call_args_list:
            image = call.args[0]
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (1464, 1464))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 0))

    def test_invalid_size_does_not_infer_or_allocate_slot(self):
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20)).save(buffer, format="PNG")
        with self.assertRaises(ValueError):
            self.processor.process_image(buffer.getvalue())
        self.model.assert_not_called()
        self.assertEqual(self.processor.tracker.used_numbers, [])
        self.assertIsNone(self.processor.last_saved_roi_path)
        self.assertEqual(list(pathlib.Path(self.roi_directory.name).rglob("*.png")), [])

    def test_saved_roi_matches_model_pixels_without_overwriting(self):
        self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
            top1=0, top1conf=torch.tensor(0.9)
        ))]
        paths = []
        for _ in range(2):
            self.processor.process_image(self.image_data)
            path = self.processor.last_saved_roi_path
            paths.append(path)
            self.assertIn("roi_1248_800_2712_2264_1464x1464", path.name)
            self.assertEqual(len(path.parent.name), 8)
            with Image.open(path) as saved:
                received = self.model.call_args.args[0]
                self.assertEqual(saved.format, "PNG")
                self.assertEqual(saved.size, received.size)
                self.assertEqual(saved.mode, received.mode)
                self.assertEqual(saved.tobytes(), received.tobytes())
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(path.is_file() for path in paths))

    def test_roi_is_retained_when_inference_fails(self):
        self.model.side_effect = RuntimeError("inference failed")
        with self.assertRaises(RuntimeError):
            self.processor.process_image(self.image_data)
        self.assertTrue(self.processor.last_saved_roi_path.is_file())

    def test_save_failure_does_not_change_tcp_result(self):
        self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
            top1=1, top1conf=torch.tensor(0.9)
        ))]
        # 用文件占用输出目录，验证真实文件系统错误被隔离。
        blocked = pathlib.Path(self.roi_directory.name) / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        self.processor.roi_save_dir = blocked
        response = self.run_camera_response(self.image_data)
        self.assertIn(response, {b"Camera:Result=1", b"Camera:Result=2", b"Camera:Result=3"})
        self.assertIsNone(self.processor.last_saved_roi_path)
        self.assertTrue(any("保存失败，继续识别" in call.args[0]
                            for call in self.logger.log.call_args_list))

    def test_disabled_saving_still_infers(self):
        self.processor.roi_save_enabled = False
        self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
            top1=1, top1conf=torch.tensor(0.9)
        ))]
        self.processor.process_image(self.image_data)
        self.model.assert_called_once()
        self.assertIsNone(self.processor.last_saved_roi_path)
        self.assertEqual(list(pathlib.Path(self.roi_directory.name).rglob("*.png")), [])

    def test_roi_directory_is_relative_to_source_or_executable(self):
        project = pathlib.Path(__file__).resolve().parents[1]
        with patch("roi_storage.sys.frozen", False, create=True):
            self.assertEqual(resolve_roi_directory("roi_images"), project / "roi_images")
        exe = pathlib.Path(self.roi_directory.name) / "VisionApp.exe"
        with patch("roi_storage.sys.frozen", True, create=True), patch(
            "roi_storage.sys.executable", str(exe)
        ), patch("roi_storage.sys._MEIPASS", "unrelated temporary bundle", create=True):
            self.assertEqual(resolve_roi_directory("roi_images"), exe.parent / "roi_images")
            absolute = pathlib.Path(self.roi_directory.name) / "custom"
            self.assertEqual(resolve_roi_directory(absolute), absolute)

    def test_out_of_bounds_roi_is_rejected(self):
        with self.assertRaises(ValueError):
            crop_roi(self.source, bbox=(0, 0, 5000, 3000))

    def test_missing_probabilities_do_not_allocate_slot(self):
        for result in ([], [SimpleNamespace(probs=None)]):
            with self.subTest(result=result):
                self.model.return_value = result
                with self.assertRaises(RuntimeError):
                    self.processor.process_image(self.image_data)
                self.assertEqual(self.processor.tracker.used_numbers, [])

    def test_unknown_prediction_does_not_allocate_slot(self):
        self.model.names = {0: "unknown"}
        self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
            top1=0, top1conf=torch.tensor(0.9)
        ))]
        with self.assertRaises(RuntimeError):
            self.processor.process_image(self.image_data)
        self.assertEqual(self.processor.tracker.used_numbers, [])

    def test_model_path_is_relative_to_project(self):
        with patch("image_processor.load_yolo_model", return_value=self.model) as load:
            self.processor._load_model()
        self.assertEqual(
            load.call_args.args[0],
            pathlib.Path(__file__).resolve().parents[1] / MODEL_PATH,
        )

    def test_packaged_model_path_uses_bundle_directory(self):
        project_dir = pathlib.Path(__file__).resolve().parents[1]
        with patch("image_processor.sys.frozen", True, create=True), patch(
            "image_processor.sys._MEIPASS", str(project_dir), create=True
        ), patch("image_processor.load_yolo_model", return_value=self.model) as load:
            self.processor._load_model()
        self.assertEqual(load.call_args.args[0], project_dir / MODEL_PATH)

    def test_best1_class_order_uses_names_for_slot_mapping(self):
        self.model.names = {0: "damage", 1: "hole", 2: "scratch", 3: "stain"}
        for class_id, expected in {0: {10, 11, 12}, 1: {1, 2, 3},
                                   2: {7, 8, 9}, 3: {4, 5, 6}}.items():
            with self.subTest(class_id=class_id):
                self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
                    top1=class_id, top1conf=torch.tensor(0.9)
                ))]
                assigned = {self.processor.process_image(self.image_data)
                            for _ in range(3)}
                self.assertEqual(assigned, expected)

    def test_incompatible_model_is_rejected_at_startup(self):
        for model in (
            Mock(task="detect", names=NAMES),
            Mock(task="classify", names={0: "unknown"}),
        ):
            with self.subTest(model=model), patch(
                "image_processor.load_yolo_model", return_value=model
            ):
                with self.assertRaises(RuntimeError):
                    self.processor._load_model()

    def run_camera_response(self, image_data):
        frame = io.BytesIO(len(image_data).to_bytes(4, "big") + image_data)
        camera = Mock()
        camera.recv.side_effect = frame.read
        camera.gettimeout.return_value = 15
        plc = Mock()
        communication = TCPCommunication(self.logger, self.processor)
        communication.socket_timeout = 15
        communication.virtual_socket = camera
        communication._display_image = Mock()
        self.assertTrue(communication.send_trigger_to_virtual(plc))
        camera.sendall.assert_called_once_with(b"Camera:Start=True")
        communication._display_image.assert_called_once_with(image_data)
        return plc.sendall.call_args.args[0]

    def test_tcp_returns_classification_slot_after_cropping(self):
        self.model.return_value = [SimpleNamespace(probs=SimpleNamespace(
            top1=1, top1conf=torch.tensor(0.9)
        ))]
        response = self.run_camera_response(self.image_data)
        self.assertIn(response, {b"Camera:Result=1", b"Camera:Result=2", b"Camera:Result=3"})
        self.assertEqual(self.model.call_args.args[0].size, (1464, 1464))

    def test_tcp_returns_image_error_for_invalid_roi_input(self):
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20)).save(buffer, format="PNG")
        self.assertEqual(self.run_camera_response(buffer.getvalue()), b"Camera:Result=-1")
        self.model.assert_not_called()
        self.assertEqual(self.processor.tracker.used_numbers, [])

    def test_tcp_returns_error_for_missing_classification(self):
        self.model.return_value = []
        self.assertEqual(self.run_camera_response(self.image_data), b"Camera:Result=-3")
        self.assertEqual(self.processor.tracker.used_numbers, [])


class ModelLoaderTests(unittest.TestCase):
    def test_standard_weights_use_normal_loader(self):
        with patch("model_loader.YOLO", return_value=Mock()) as yolo, patch(
            "model_loader.torch.load"
        ) as load:
            load_yolo_model("example.pt")
        yolo.assert_called_once_with("example.pt")
        load.assert_not_called()

    def test_foreign_path_uses_temporary_copy_without_global_patch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = pathlib.Path(temp_dir) / "foreign.pt"
            torch.save({"train_args": {"data": ForeignPath()}}, str(source))
            original_hash = hashlib.sha256(source.read_bytes()).digest()
            original_path_class = pathlib.PosixPath
            temporary_paths = []
            model = SimpleNamespace(model=SimpleNamespace(), overrides={})

            def fake_yolo(path):
                if path == str(source):
                    raise NotImplementedError("cannot instantiate 'PosixPath' on your system")
                temporary_paths.append(pathlib.Path(path))
                checkpoint = torch.load(path, map_location="cpu", weights_only=False)
                self.assertIsInstance(checkpoint["train_args"]["data"], pathlib.PurePosixPath)
                return model

            with patch("model_loader.YOLO", side_effect=fake_yolo):
                self.assertIs(load_yolo_model(source), model)
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original_hash)
            self.assertIs(pathlib.PosixPath, original_path_class)
            self.assertFalse(temporary_paths[0].exists())
            self.assertEqual(model.overrides["model"], str(source))

    def test_unrelated_load_error_is_not_retried(self):
        with patch("model_loader.YOLO", side_effect=NotImplementedError("other error")), patch(
            "model_loader.torch.load"
        ) as load:
            with self.assertRaises(NotImplementedError):
                load_yolo_model("example.pt")
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
