"""TCP communication between the PLC, the virtual camera and the vision code.

The wire format is kept compatible with the existing simulator:

* PLC -> Python: ``Camera:Trigger=True``
* Python -> Virtual: ``Camera:Start=True``
* Python -> PLC: ``Camera:Result=<value>``
* Virtual -> Python: 4-byte big-endian image size followed by image bytes

The class deliberately serializes a complete capture request. The virtual
camera uses one request/response stream, so interleaving two requests would
make the following image impossible to associate with the right PLC request.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional, Set, Tuple

from config import (
    ERROR_COMMUNICATION_ERROR,
    ERROR_CONNECTION_REFUSED,
    ERROR_CONNECTION_TIMEOUT,
    ERROR_INCOMPLETE_IMAGE,
    LOG_TIMEOUT,
    PLC_CMD_CAMERA_TRIGGER,
    PLC_RESPONSE_RESULT,
    VIRTUAL_CMD_CAMERA_START,
)


MAX_IMAGE_SIZE = 100 * 1024 * 1024
MAX_PLC_COMMAND_BUFFER = 4096
ACCEPT_POLL_TIMEOUT = 0.5


class TCPCommunication:
    """Manage the PLC server socket and the connection to the virtual camera."""

    def __init__(
        self,
        logger,
        image_processor,
        ui_dispatcher: Optional[Callable[..., object]] = None,
    ):
        self.logger = logger
        self.image_processor = image_processor

        # ui_dispatcher accepts ``(callback, *args)`` and can marshal Tkinter
        # updates to the main thread. With no dispatcher, the class retains the
        # old behaviour for non-GUI callers and tests.
        self.ui_dispatcher = ui_dispatcher

        self.server_running = False
        self.server_socket: Optional[socket.socket] = None
        self.server_thread: Optional[threading.Thread] = None
        self.virtual_socket: Optional[socket.socket] = None

        self.plc_host = None
        self.plc_port = None
        self.virtual_host = None
        self.virtual_port = None
        self.socket_timeout = None

        self._stop_event = threading.Event()
        self._virtual_lock = threading.RLock()
        self._client_lock = threading.Lock()
        self._client_sockets: Set[socket.socket] = set()
        self._client_threads: Set[threading.Thread] = set()

    def set_config(
        self,
        plc_host,
        plc_port,
        virtual_host,
        virtual_port,
        socket_timeout,
    ):
        """Set communication parameters.

        Validation is deferred to :meth:`start_server` so a GUI can update all
        fields before receiving a single configuration error.
        """

        self.plc_host = plc_host
        self.plc_port = plc_port
        self.virtual_host = virtual_host
        self.virtual_port = virtual_port
        self.socket_timeout = socket_timeout

    def start_server(self) -> bool:
        """Connect to Virtual and start listening for PLC clients."""

        if self.server_running:
            self.logger.log("Python TCP服务器已经在运行")
            return True

        server_socket = None
        try:
            self._validate_config()
            self._stop_event.clear()

            self.logger.log("正在连接Virtual服务器...")
            with self._virtual_lock:
                if self._connect_virtual_locked() is None:
                    self._stop_event.set()
                    return False

            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            server_socket.bind((self.plc_host, self.plc_port))
            server_socket.listen(5)
            # A short accept timeout allows stop_server() to observe the stop
            # event even when no PLC is connected.
            server_socket.settimeout(ACCEPT_POLL_TIMEOUT)

            self.server_socket = server_socket
            self.server_running = True
            self.server_thread = threading.Thread(
                target=self.accept_connections,
                name="plc-accept",
                daemon=True,
            )
            self.server_thread.start()

            self.logger.log(
                f"Python TCP服务器已启动 - {self.plc_host}:{self.plc_port}"
            )
            self.logger.log("等待PLC客户端连接...")
            return True

        except (TypeError, ValueError) as exc:
            self.logger.log(f"通信配置无效: {exc}")
        except OSError as exc:
            self.logger.log(f"启动TCP服务器失败: {exc}")
        except Exception as exc:
            self.logger.log(f"启动TCP服务器发生未知错误: {exc}")

        # Startup can fail after Virtual has connected or after the listening
        # socket has been created. Always return to a clean state.
        self._stop_event.set()
        self.server_running = False
        self._close_socket(server_socket)
        self._close_server_socket()
        with self._virtual_lock:
            self._close_virtual_socket_locked()
        return False

    def stop_server(self) -> None:
        """Stop the listener and close all active TCP connections."""

        self.logger.log("正在停止Python TCP服务器...")
        self._stop_event.set()
        self.server_running = False

        self._close_server_socket()

        with self._client_lock:
            client_sockets = list(self._client_sockets)
            client_threads = list(self._client_threads)
        for client_socket in client_sockets:
            self._close_socket(client_socket)

        with self._virtual_lock:
            self._close_virtual_socket_locked()

        current_thread = threading.current_thread()
        if self.server_thread and self.server_thread is not current_thread:
            self.server_thread.join(timeout=1.0)
        self.server_thread = None

        for client_thread in client_threads:
            if client_thread is not current_thread:
                client_thread.join(timeout=1.0)

        with self._client_lock:
            self._client_sockets.clear()
            self._client_threads.clear()

        self.logger.log("Python TCP服务器已停止")

    def accept_connections(self) -> None:
        """Accept PLC clients and create one handler thread per client."""

        while not self._stop_event.is_set():
            server_socket = self.server_socket
            if server_socket is None:
                break

            try:
                client_socket, addr = server_socket.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    self.logger.log(f"接受PLC连接错误: {exc}")
                break

            try:
                client_socket.settimeout(self._timeout_value())
            except OSError:
                self._close_socket(client_socket)
                continue

            client_thread = threading.Thread(
                target=self.handle_plc_client,
                args=(client_socket,),
                name="plc-client",
                daemon=True,
            )
            with self._client_lock:
                self._client_sockets.add(client_socket)
                self._client_threads.add(client_thread)
            self.logger.log(f"新的PLC客户端已连接: {addr[0]}:{addr[1]}")
            client_thread.start()

    def handle_plc_client(self, client_socket: socket.socket) -> None:
        """Receive PLC commands, preserving the current delimiter-free format."""

        client_addr = self._peer_name(client_socket)
        command_buffer = bytearray()
        current_thread = threading.current_thread()

        try:
            self.logger.log(
                f"开始处理PLC客户端请求: {client_addr[0]}:{client_addr[1]}"
            )

            while not self._stop_event.is_set():
                try:
                    data = client_socket.recv(4096)
                except socket.timeout:
                    # The timeout only gives the loop a chance to observe the
                    # stop event; it is not a communication failure.
                    continue
                except OSError as exc:
                    if not self._stop_event.is_set():
                        self.logger.log(f"读取PLC消息失败: {exc}")
                    break

                if not data:
                    self.logger.log(
                        f"PLC客户端 {client_addr[0]}:{client_addr[1]} 已断开连接"
                    )
                    break

                command_buffer.extend(data)
                self.logger.log(f"PLC接收 {client_addr[0]}:{client_addr[1]}：{data[:128]!r}")
                trigger_count, command_buffer = self._extract_trigger_commands(
                    command_buffer
                )
                for _ in range(trigger_count):
                    if self._stop_event.is_set():
                        break
                    self.logger.log(f"检测到拍照触发命令，来自 {client_addr[0]}:{client_addr[1]}")
                    self.send_trigger_to_virtual(client_socket)

        except Exception as exc:
            self.logger.log(f"处理PLC客户端错误: {exc}")
        finally:
            with self._client_lock:
                self._client_sockets.discard(client_socket)
                self._client_threads.discard(current_thread)
            self._close_socket(client_socket)
            self.logger.log(
                f"已关闭PLC客户端连接: {client_addr[0]}:{client_addr[1]}"
            )

    def send_trigger_to_virtual(self, plc_client_socket: socket.socket) -> bool:
        """Capture one image, run recognition, and return a PLC result.

        The lock covers the complete request/response/recognition sequence.
        This prevents two PLC handler threads from interleaving messages on the
        single Virtual TCP stream and from concurrently changing the vision
        processor's placement tracker.
        """

        with self._virtual_lock:
            virtual_socket = self._connect_virtual_locked()
            if virtual_socket is None:
                return self.send_result_to_plc(
                    ERROR_CONNECTION_REFUSED, plc_client_socket
                )

            try:
                self._send_command(virtual_socket, VIRTUAL_CMD_CAMERA_START)
                self.logger.log(
                    f"已发送拍照命令到Virtual: {VIRTUAL_CMD_CAMERA_START}"
                )

                size_data = self._recv_exactly(virtual_socket, 4)
                image_size = int.from_bytes(size_data, byteorder="big")
                if image_size <= 0 or image_size > MAX_IMAGE_SIZE:
                    raise ValueError(f"无效的图像大小: {image_size} 字节")

                self.logger.log(f"接收到图像大小: {image_size} 字节")
                received_data = self._recv_exactly(virtual_socket, image_size)
                self.logger.log("图像接收完成，开始处理图像")

                # Do not blindly drain the socket here. That can consume the
                # beginning of the next valid framed message.
                self._display_image(received_data)
                result = self.image_processor.process_image(received_data)
                if not isinstance(result, int):
                    raise ValueError(f"视觉结果不是整数: {result!r}")

                self.logger.log(f"视觉处理完成，结果值: {result}")
                return self.send_result_to_plc(result, plc_client_socket)

            except socket.timeout:
                self.logger.log(
                    f"接收Virtual图像超时({self._timeout_value()}秒)"
                )
                self._close_virtual_socket_locked()
                return self.send_result_to_plc(
                    ERROR_CONNECTION_TIMEOUT, plc_client_socket
                )
            except ConnectionRefusedError as exc:
                self.logger.log(f"Virtual连接被拒绝: {exc}")
                self._close_virtual_socket_locked()
                return self.send_result_to_plc(
                    ERROR_CONNECTION_REFUSED, plc_client_socket
                )
            except (
                BrokenPipeError,
                ConnectionResetError,
                ConnectionAbortedError,
                EOFError,
            ) as exc:
                self.logger.log(f"Virtual连接中断: {exc}")
                self._close_virtual_socket_locked()
                return self.send_result_to_plc(
                    ERROR_COMMUNICATION_ERROR, plc_client_socket
                )
            except ValueError as exc:
                self.logger.log(f"图像数据无效: {exc}")
                self._close_virtual_socket_locked()
                return self.send_result_to_plc(
                    ERROR_INCOMPLETE_IMAGE, plc_client_socket
                )
            except OSError as exc:
                self.logger.log(f"Virtual通信错误: {exc}")
                self._close_virtual_socket_locked()
                return self.send_result_to_plc(
                    ERROR_COMMUNICATION_ERROR, plc_client_socket
                )
            except Exception as exc:
                self.logger.log(f"图像处理或通信异常: {exc}")
                return self.send_result_to_plc(
                    ERROR_COMMUNICATION_ERROR, plc_client_socket
                )

    def send_result_to_plc(
        self,
        result,
        plc_socket: Optional[socket.socket],
    ) -> bool:
        """Send a result using the existing PLC response format."""

        if plc_socket is None:
            self.logger.log("PLC连接不存在，无法发送处理结果")
            return False

        result_message = PLC_RESPONSE_RESULT.format(result)
        try:
            plc_socket.sendall(result_message.encode("utf-8"))
            self.logger.log(f"已发送处理结果到PLC: {result_message}")
            return True
        except OSError as exc:
            self.logger.log(f"发送结果到PLC失败: {exc}")
            return False

    def clear_socket_buffer(
        self,
        socket_obj: Optional[socket.socket],
        stage_desc: str = "",
        max_duration: float = 0.2,
        max_bytes: int = 64 * 1024,
    ) -> bool:
        """Explicitly drain stale data for diagnostics only.

        This method is retained for compatibility but is no longer called as
        part of normal image processing. Blind draining is unsafe when the
        protocol has no message framing because it may discard a valid message.
        """

        if socket_obj is None:
            return False

        previous_timeout = socket_obj.gettimeout()
        cleared = 0
        deadline = time.monotonic() + max_duration
        try:
            socket_obj.settimeout(min(LOG_TIMEOUT, max_duration))
            while cleared < max_bytes and time.monotonic() < deadline:
                try:
                    chunk = socket_obj.recv(min(8192, max_bytes - cleared))
                except socket.timeout:
                    break
                if not chunk:
                    break
                cleared += len(chunk)
            if cleared:
                self.logger.log(
                    f"{stage_desc} - 显式清理socket缓冲区 {cleared} 字节"
                )
            return True
        except OSError as exc:
            self.logger.log(f"清理socket缓冲区失败: {exc}")
            return False
        finally:
            try:
                socket_obj.settimeout(previous_timeout)
            except OSError:
                pass

    def _validate_config(self) -> None:
        if not self.plc_host or not self.virtual_host:
            raise ValueError("PLC和Virtual地址不能为空")

        for name, port in (
            ("PLC端口", self.plc_port),
            ("Virtual端口", self.virtual_port),
        ):
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError(f"{name}必须是1到65535之间的整数")

        timeout = self._timeout_value()
        if timeout <= 0:
            raise ValueError("通信超时时间必须大于0")

    def _timeout_value(self) -> float:
        try:
            timeout = float(self.socket_timeout)
        except (TypeError, ValueError):
            raise ValueError("通信超时时间必须是数字")
        if timeout <= 0:
            raise ValueError("通信超时时间必须大于0")
        return timeout

    def _connect_virtual_locked(self) -> Optional[socket.socket]:
        if self.virtual_socket is not None:
            return self.virtual_socket

        virtual_socket = None
        try:
            virtual_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            virtual_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            virtual_socket.settimeout(self._timeout_value())
            virtual_socket.connect((self.virtual_host, self.virtual_port))
            self.virtual_socket = virtual_socket
            self.logger.log(
                f"已连接Virtual服务器 {self.virtual_host}:{self.virtual_port}"
            )
            return virtual_socket
        except OSError as exc:
            self.logger.log(
                f"连接Virtual服务器失败 {self.virtual_host}:{self.virtual_port}: {exc}"
            )
            self._close_socket(virtual_socket)
            return None

    def _send_command(self, socket_obj: socket.socket, command: str) -> None:
        socket_obj.sendall(command.encode("utf-8"))

    def _recv_exactly(self, socket_obj: socket.socket, size: int) -> bytes:
        """Receive exactly ``size`` bytes or raise on timeout/EOF."""

        if size < 0:
            raise ValueError("接收长度不能为负数")

        deadline = time.monotonic() + self._timeout_value()
        result = bytearray()
        previous_timeout = socket_obj.gettimeout()
        try:
            while len(result) < size:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise socket.timeout()
                socket_obj.settimeout(remaining_time)
                chunk = socket_obj.recv(size - len(result))
                if not chunk:
                    raise EOFError("对端在数据接收完成前关闭了连接")
                result.extend(chunk)
            return bytes(result)
        finally:
            try:
                socket_obj.settimeout(previous_timeout)
            except OSError:
                pass

    def _extract_trigger_commands(
        self,
        command_buffer: bytearray,
    ) -> Tuple[int, bytearray]:
        """Extract known trigger commands from the delimiter-free protocol."""

        normalized_buffer = bytes(command_buffer)
        for whitespace in (b" ", b"\t", b"\r", b"\n"):
            normalized_buffer = normalized_buffer.replace(whitespace, b"")
        normalized_buffer = normalized_buffer.lower()
        trigger = PLC_CMD_CAMERA_TRIGGER.replace(" ", "").lower().encode("utf-8")

        count = normalized_buffer.count(trigger)
        if count:
            end = normalized_buffer.rfind(trigger) + len(trigger)
            normalized_buffer = normalized_buffer[end:]
        # 保留下一条命令的前缀，不能因前一条完整命令而清空半包。
        for size in range(min(len(normalized_buffer), len(trigger) - 1), 0, -1):
            if normalized_buffer.endswith(trigger[:size]):
                return count, bytearray(normalized_buffer[-size:])
        return count, bytearray()

    def _display_image(self, image_data: bytes) -> None:
        if self.ui_dispatcher is None:
            self.image_processor.display_image(image_data)
            return
        self.ui_dispatcher(self.image_processor.display_image, image_data)

    def _peer_name(self, socket_obj: socket.socket) -> Tuple[str, int]:
        try:
            address = socket_obj.getpeername()
            return address[0], address[1]
        except OSError:
            return "unknown", 0

    def _close_server_socket(self) -> None:
        server_socket = self.server_socket
        self.server_socket = None
        self._close_socket(server_socket)

    def _close_virtual_socket_locked(self) -> None:
        virtual_socket = self.virtual_socket
        self.virtual_socket = None
        self._close_socket(virtual_socket)

    @staticmethod
    def _close_socket(socket_obj: Optional[socket.socket]) -> None:
        if socket_obj is None:
            return
        try:
            socket_obj.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            socket_obj.close()
        except OSError:
            pass
