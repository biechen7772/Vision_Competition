import tkinter as tk
from tkinter import ttk, messagebox
from logger import Logger
from image_processor import ImageProcessor
from tcp_communication import TCPCommunication
from ui_dispatcher import UIDispatcher
import threading

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("视觉界面")
        self.root.geometry("900x600")
        
        # 初始化各个组件
        self.setup_styles()
        self.create_widgets()
        
        # 初始化日志系统
        self.ui_dispatcher = UIDispatcher(self.root)
        self.logger = Logger(self.log_text, self.ui_dispatcher)
        self.service_busy = False
        self.closing = False
        
        # 初始化图像处理器
        self.image_processor = ImageProcessor(self.image_label, self.image_info, self.logger)
        
        # 初始化TCP通信
        # TCP handler runs in worker threads; marshal image widget updates to
        # Tkinter's main loop instead of touching widgets from those threads.
        self.tcp_communication = TCPCommunication(
            self.logger,
            self.image_processor,
            ui_dispatcher=self.ui_dispatcher,
        )
        
        # 添加启动日志
        self.logger.log("程序已启动")
        self.logger.log("请配置服务器和客户端参数，然后点击'启动服务'按钮")
         # 在初始化完成后自动启动服务
        self.root.protocol("WM_DELETE_WINDOW", self.close_window)
        self.root.after(0, self.start_server)
    
 
    
    def setup_styles(self):
        """设置应用的样式"""
        style = ttk.Style()
        
        # 根据系统判断使用哪种主题
        if "clam" in style.theme_names():
            style.theme_use("clam")
        
        # 配置标签框架样式
        style.configure("TLabelframe", borderwidth=2, relief="solid", padding=5)
        style.configure("TLabelframe.Label", font=("Arial", 10, "bold"))
        
        # 配置按钮样式
        style.configure("TButton", padding=5, font=("Arial", 9))
        
        # 配置标签样式
        style.configure("TLabel", font=("Arial", 9))
        
        # 配置输入框样式
        style.configure("TEntry", padding=2)
    
    def create_widgets(self):
        # 创建PLC服务器组框架
        plc_frame = ttk.LabelFrame(self.root, text="Python服务器(PLC客户端)")
        plc_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        
        # 创建配置变量
        self.plc_host = tk.StringVar(value="0.0.0.0")
        self.plc_port = tk.IntVar(value=50050)
        self.virtual_host = tk.StringVar(value="127.0.0.1")
        self.virtual_port = tk.IntVar(value=5001)
        self.socket_timeout = tk.IntVar(value=15)
        
        ttk.Label(plc_frame, text="IP地址:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Entry(plc_frame, textvariable=self.plc_host, width=15).grid(row=0, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(plc_frame, text="端口:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Entry(plc_frame, textvariable=self.plc_port, width=15).grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # 创建Virtual客户端组框架
        virtual_frame = ttk.LabelFrame(self.root, text="Python客户端(Virtual服务器)")
        virtual_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        
        ttk.Label(virtual_frame, text="IP地址:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Entry(virtual_frame, textvariable=self.virtual_host, width=15).grid(row=0, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(virtual_frame, text="端口:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Entry(virtual_frame, textvariable=self.virtual_port, width=15).grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # 创建单独的超时设置框架
        timeout_frame = ttk.LabelFrame(self.root, text="通信设置")
        timeout_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")
        
        ttk.Label(timeout_frame, text="超时设置(秒):").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        ttk.Entry(timeout_frame, textvariable=self.socket_timeout, width=15).grid(row=0, column=1, sticky=tk.W, pady=5)
        
        # 控制按钮放在右侧
        control_frame = ttk.LabelFrame(self.root, text="控制")
        control_frame.grid(row=0, column=2, rowspan=3, padx=10, pady=5, sticky="nsew")
        
        self.start_button = ttk.Button(control_frame, text="启动服务", command=self.start_server)
        self.start_button.pack(padx=10, pady=10, fill="x")
        
        self.stop_button = ttk.Button(control_frame, text="停止服务", command=self.stop_server, state=tk.DISABLED)
        self.stop_button.pack(padx=10, pady=10, fill="x")
        
        # 图像显示区域
        self.image_frame = ttk.LabelFrame(self.root, text="接收的图像")
        self.image_frame.grid(row=0, column=3, rowspan=3, padx=10, pady=5, sticky="nsew")
        
        # 创建图像标签
        self.image_label = ttk.Label(self.image_frame)
        self.image_label.pack(padx=10, pady=10, fill="both", expand=True)
        
        # 图像信息标签
        self.image_info = ttk.Label(self.image_frame, text="未接收图像", anchor="center")
        self.image_info.pack(padx=5, pady=5)
        
        # 创建日志框架
        log_frame = ttk.LabelFrame(self.root, text="操作日志")
        log_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=10, sticky="nsew")
        
        # 在框架内创建日志区域和滚动条
        self.log_text = tk.Text(log_frame, height=15, width=70)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        # 将清空日志按钮移至日志区域旁边
        self.clear_log_button = ttk.Button(log_frame, text="清空日志", command=self.clear_log)
        
        # 使用pack布局管理器放置日志组件
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.clear_log_button.pack(side=tk.BOTTOM, anchor=tk.SE, padx=5, pady=5)
        
        # 设置行和列的权重，使组件可以随窗口调整大小
        self.root.rowconfigure(3, weight=1)
        for col in range(4):
            self.root.columnconfigure(col, weight=1 if col == 3 else 0)
    
    def start_server(self):
        """启动服务器"""
        if self.service_busy or self.closing:
            return
        try:
            settings = (self.plc_host.get(), self.plc_port.get(), self.virtual_host.get(),
                        self.virtual_port.get(), self.socket_timeout.get())
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("错误", f"通信配置无效：{exc}")
            return
        # 设置TCP通信配置
        self.tcp_communication.set_config(
            *settings
        )
        
        self.service_busy = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        threading.Thread(target=self._start_service, daemon=True, name="service-start").start()

    def _start_service(self):
        success = self.tcp_communication.start_server()
        self.ui_dispatcher(self._service_started, success)

    def _service_started(self, success):
        self.service_busy = False
        if success:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.NORMAL)
            messagebox.showerror("错误", "无法启动服务器，请检查配置和网络连接")
    
    def stop_server(self):
        """停止服务器"""
        if self.service_busy or self.closing:
            return
        self.service_busy = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        threading.Thread(target=self._stop_service, daemon=True, name="service-stop").start()

    def _stop_service(self):
        self.tcp_communication.stop_server()
        self.ui_dispatcher(self._service_stopped)

    def _service_stopped(self):
        self.service_busy = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def close_window(self):
        self.closing = True
        self.ui_dispatcher.close()
        self.root.destroy()
    
    def clear_log(self):
        """清空日志"""
        self.logger.clear_log()
