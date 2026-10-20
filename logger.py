import time
import tkinter as tk
from tkinter import ttk
from ui_dispatcher import UIDispatcher

class Logger:
    def __init__(self, log_text_widget, dispatcher=None):
        self.log_text = log_text_widget
        self.dispatcher = dispatcher if dispatcher is not None else UIDispatcher(log_text_widget)
        
    def log(self, message):
        """添加日志消息到界面"""
        # 过滤掉可能导致空行的特殊字符
        message = message.replace('\r', ' ').replace('\n', ' ')
        
        # 如果消息过长，做适当截断
        max_length = 150
        if len(message) > max_length:
            message = message[:max_length] + "..."
        
        # 添加时间戳并插入到日志
        log_entry = f"{time.strftime('%H:%M:%S')} - {message}\n"
        self.dispatcher(self._append, log_entry)

    def _append(self, log_entry):
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
    
    def clear_log(self):
        """清空日志区域"""
        self.dispatcher(self._clear)

    def _clear(self):
        self.log_text.delete(1.0, tk.END)
        self.log("日志已清空")
