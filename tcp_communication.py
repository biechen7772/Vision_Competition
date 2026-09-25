import socket
import threading
import time
from config import (
    ERROR_INCOMPLETE_IMAGE, ERROR_CONNECTION_TIMEOUT,
    ERROR_COMMUNICATION_ERROR, ERROR_CONNECTION_REFUSED,
    PLC_CMD_CAMERA_TRIGGER, VIRTUAL_CMD_CAMERA_START,
    PLC_RESPONSE_RESULT, LOG_TIMEOUT
)

class TCPCommunication:
    def __init__(self, logger, image_processor):
        self.logger = logger
        self.image_processor = image_processor
        
        # 服务器和客户端状态
        self.server_running = False
        self.server_socket = None
        self.server_thread = None
        self.client_socket = None
        self.virtual_socket = None
        
        # 配置参数
        self.plc_host = None
        self.plc_port = None
        self.virtual_host = None
        self.virtual_port = None
        self.socket_timeout = None
    
    def set_config(self, plc_host, plc_port, virtual_host, virtual_port, socket_timeout):
        """设置通信配置参数"""
        self.plc_host = plc_host
        self.plc_port = plc_port
        self.virtual_host = virtual_host
        self.virtual_port = virtual_port
        self.socket_timeout = socket_timeout
    
    def start_server(self):
        """启动TCP服务器并连接到Virtual服务器"""
        try:
            self.logger.log("正在启动Python TCP服务器...")
            
            # 首先尝试连接到Virtual服务器
            self.logger.log(f"正在连接Virtual服务器 {self.virtual_host}:{self.virtual_port}...")
            try:
                self.virtual_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.virtual_socket.settimeout(self.socket_timeout)
                self.virtual_socket.connect((self.virtual_host, self.virtual_port))
                self.logger.log(f"已成功连接到Virtual服务器 {self.virtual_host}:{self.virtual_port}")
                
                # 清空可能的缓冲数据
                self.clear_socket_buffer(self.virtual_socket, "初始连接后")
            except Exception as ve:
                self.logger.log(f"连接Virtual服务器失败: {str(ve)}")
                return False
            
            # 然后创建并启动Python服务器(用于连接PLC)
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.plc_host, self.plc_port))
            self.server_socket.listen(5)
            self.server_running = True
            
            self.logger.log(f"Python TCP服务器已成功启动 - {self.plc_host}:{self.plc_port}")
            self.logger.log("等待PLC客户端连接...")
            
            # 启动服务器线程
            self.server_thread = threading.Thread(target=self.accept_connections)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            return True
            
        except Exception as e:
            self.logger.log(f"启动服务器错误: {str(e)}")
            return False
    
    def stop_server(self):
        """停止TCP服务器"""
        self.logger.log("正在停止Python TCP服务器...")
        self.server_running = False
        
        # 关闭服务器套接字
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
        
        # 关闭与Virtual服务器的连接
        if self.virtual_socket:
            try:
                self.virtual_socket.close()
                self.logger.log("已关闭与Virtual服务器的连接")
            except Exception as e:
                self.logger.log(f"关闭Virtual连接时出错: {str(e)}")
            self.virtual_socket = None
        
        self.logger.log("Python TCP服务器已停止")
    
    def accept_connections(self):
        """接受来自PLC的连接请求"""
        while self.server_running:
            try:
                client_socket, addr = self.server_socket.accept()
                self.logger.log(f"新的PLC客户端已连接: {addr[0]}:{addr[1]}")
                
                # 为每个客户端创建一个处理线程
                client_thread = threading.Thread(target=self.handle_plc_client, args=(client_socket,))
                client_thread.daemon = True
                client_thread.start()
                
            except Exception as e:
                if self.server_running:
                    self.logger.log(f"接受连接错误: {str(e)}")
                break
    
    def handle_plc_client(self, client_socket):
        """处理来自PLC的请求"""
        try:
            client_addr = client_socket.getpeername()
            self.logger.log(f"开始处理来自 {client_addr[0]}:{client_addr[1]} 的PLC客户端请求")
            self.logger.log("等待PLC客户端发送触发命令...")
            
            while self.server_running:
                data = client_socket.recv(1024)
                if not data:
                    self.logger.log(f"PLC客户端 {client_addr[0]}:{client_addr[1]} 已断开连接")
                    break
                
                original_message = data.decode('utf-8').strip()
                self.logger.log(f"收到PLC客户端消息: {original_message}")
                
                # 对消息进行规范化处理（去除所有空格和换行）
                normalized_message = original_message.replace(" ", "").replace("\r", "").replace("\n", "").lower()
                normalized_trigger = PLC_CMD_CAMERA_TRIGGER.lower().replace(" ", "")
                
                # 简单地检查标准化后的消息是否包含触发命令
                if normalized_trigger in normalized_message:
                    self.logger.log(f"检测到拍照触发命令: {original_message}")
                    self.logger.log("准备向Virtual发送拍照请求...")
                    
                    # 发送触发命令并处理响应
                    self.send_trigger_to_virtual(client_socket)
                else:
                    self.logger.log(f"收到未识别的命令: {original_message}, 忽略")
            
        except Exception as e:
            self.logger.log(f"处理PLC客户端错误: {str(e)}")
        finally:
            self.logger.log(f"关闭与PLC客户端 {client_addr[0]}:{client_addr[1]} 的连接")
            client_socket.close()
    
    def send_trigger_to_virtual(self, plc_client_socket):
        """向Virtual发送拍照命令并接收照片"""
        # 检查连接是否存在
        if not self.virtual_socket:
            self.logger.log("Virtual连接不存在，尝试重新连接...")
            try:
                self.virtual_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.virtual_socket.settimeout(self.socket_timeout)
                self.virtual_socket.connect((self.virtual_host, self.virtual_port))
                self.logger.log(f"已重新连接到Virtual服务器 {self.virtual_host}:{self.virtual_port}")
            except Exception as e:
                self.logger.log(f"连接Virtual服务器失败: {str(e)}")
                self.send_result_to_plc(ERROR_CONNECTION_REFUSED, plc_client_socket)
                return
        
        try:
            # 发送拍照命令
            self.virtual_socket.sendall(VIRTUAL_CMD_CAMERA_START.encode('utf-8'))
            self.logger.log(f"已发送拍照命令到Virtual: {VIRTUAL_CMD_CAMERA_START}")
            
            # 接收图像大小
            size_data = self.virtual_socket.recv(4)
            if not size_data or len(size_data) < 4:
                self.logger.log(f"接收图像大小数据不完整: 收到 {len(size_data) if size_data else 0} 字节")
                self.send_result_to_plc(ERROR_INCOMPLETE_IMAGE, plc_client_socket)
                return
            
            image_size = int.from_bytes(size_data, byteorder='big')
            
            # 验证图像大小是否合理 (例如不超过100MB)
            if image_size <= 0 or image_size > 100 * 1024 * 1024:
                self.logger.log(f"收到无效的图像大小: {image_size} 字节，超出合理范围")
                self.send_result_to_plc(ERROR_INCOMPLETE_IMAGE, plc_client_socket)
                return
            
            self.logger.log(f"接收到图像大小信息: {image_size} 字节")
            
            # 接收图像数据
            received_data = b''
            remaining = image_size
            
            self.logger.log(f"开始接收图像数据，总大小: {image_size} 字节...")
            progress = 0
            start_time = time.time()
            
            while remaining > 0:
                # 添加部分超时检查，防止无限等待
                if time.time() - start_time > self.socket_timeout:
                    self.logger.log(f"接收图像数据超时({self.socket_timeout}秒)")
                    self.send_result_to_plc(ERROR_CONNECTION_TIMEOUT, plc_client_socket)
                    return
                
                chunk = self.virtual_socket.recv(min(4096, remaining))
                if not chunk:
                    self.logger.log("接收图像中断: Virtual连接意外关闭")
                    self.virtual_socket = None
                    self.send_result_to_plc(ERROR_COMMUNICATION_ERROR, plc_client_socket)
                    return
                
                received_data += chunk
                remaining -= len(chunk)
                
                # 每接收约25%进度输出一次日志
                new_progress = int((1 - remaining / image_size) * 100)
                if new_progress - progress >= 25:
                    progress = new_progress
                    self.logger.log(f"图像接收进度: {progress}%")
            
            # 验证接收到的数据是否完整
            if len(received_data) == image_size:
                self.logger.log("图像数据接收完成，开始处理图像...")
                
                # 清空接收缓冲区中可能的额外数据
                self.clear_socket_buffer(self.virtual_socket, "图像接收完成后")
                
                # 保存并显示图像
                self.image_processor.display_image(received_data)
                
                # 处理图像
                result = self.image_processor.process_image(received_data)
                
                # 向PLC发送处理结果
                self.send_result_to_plc(result, plc_client_socket)
            else:
                self.logger.log(f"接收图像数据不完整: 已接收 {len(received_data)}/{image_size} 字节")
                self.send_result_to_plc(ERROR_INCOMPLETE_IMAGE, plc_client_socket)
            
        except socket.timeout:
            self.logger.log(f"接收Virtual图像超时({self.socket_timeout}秒)")
            self.send_result_to_plc(ERROR_CONNECTION_TIMEOUT, plc_client_socket)
            
        except ConnectionRefusedError:
            self.logger.log(f"无法连接到Virtual服务器 {self.virtual_host}:{self.virtual_port} - 连接被拒绝")
            self.send_result_to_plc(ERROR_CONNECTION_REFUSED, plc_client_socket)
            self.virtual_socket = None
            
        except Exception as e:
            self.logger.log(f"与Virtual通信错误: {str(e)}")
            self.send_result_to_plc(ERROR_COMMUNICATION_ERROR, plc_client_socket)
            if "connection" in str(e).lower() or "broken" in str(e).lower():
                self.virtual_socket = None
    
    def send_result_to_plc(self, result, plc_socket):
        """向PLC发送处理结果"""
        try:
            # 使用常量格式化结果消息
            result_message = PLC_RESPONSE_RESULT.format(result)
            plc_socket.sendall(result_message.encode('utf-8'))
            
            self.logger.log(f"已发送处理结果到PLC客户端: {result_message}")
            
        except Exception as e:
            self.logger.log(f"发送结果到PLC客户端错误: {str(e)}")
    
    def clear_socket_buffer(self, socket_obj, stage_desc=""):
        """彻底清空套接字接收缓冲区"""
        if not socket_obj:
            return
        
        socket_obj.settimeout(LOG_TIMEOUT)  # 设置很短的超时时间
        total_cleared = 0
        try:
            # 循环读取直到没有更多数据
            start_time = time.time()
            while time.time() - start_time < 2:  # 最多花2秒时间清空缓冲区
                try:
                    chunk = socket_obj.recv(8192)  # 使用更大的缓冲区一次读取更多数据
                    if not chunk:
                        # 对端关闭了连接
                        self.logger.log("连接已关闭")
                        return False
                    total_cleared += len(chunk)
                    # 只有清除了大量数据时才输出日志
                    if len(chunk) > 100:
                        self.logger.log(f"清除了 {len(chunk)} 字节数据")
                except socket.timeout:
                    # 没有更多数据可读，缓冲区已清空
                    break
        except Exception as e:
            self.logger.log(f"清空缓冲区时发生错误: {str(e)}")
            return False
        finally:
            # 恢复正常超时
            socket_obj.settimeout(self.socket_timeout)
        
        # 只有在清除了数据时才输出总结日志
        if total_cleared > 0:
            self.logger.log(f"{stage_desc} - 清空缓冲区，共 {total_cleared} 字节")
        
        return True