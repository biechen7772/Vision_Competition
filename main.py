import multiprocessing
import sys


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--gui-self-test":
        from gui_self_test import run_gui_self_test
        return run_gui_self_test(sys.argv[2])
    # 在打包后的程序中检查实际包含的界面、模型及通信依赖。
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from packaging_self_test import run_self_test
        return run_self_test(sys.argv[2])

    import tkinter as tk
    from main_window import MainWindow

    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
