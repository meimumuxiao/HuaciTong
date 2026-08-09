from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk

import win32clipboard

from core import APP_NAME, MODEL_BYTES, LocalModelServer, download_model, model_is_ready


BG = "#eaf2fb"
CARD = "#ffffff"
CARD_2 = "#dcebfa"
LINE = "#bcd6f2"
TEXT = "#1a2026"
SUBTLE = "#5b6b78"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2f6fe0"
SUCCESS = "#2e9e6e"
ERROR = "#d64550"

user32 = ctypes.windll.user32


def enable_dpi_awareness() -> None:
    """开启 Windows DPI 感知，避免高分屏/缩放下字体发虚模糊。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()
kernel32 = ctypes.windll.kernel32
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_F8 = 0x77
VK_F9 = 0x78
KEYEVENTF_KEYUP = 0x0002
MODEL_IDLE_SECONDS = 300


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def runtime_path() -> Path:
    bundled = resource_path("runtime")
    if (bundled / "llama-server.exe").is_file():
        return bundled
    development = bundled / "b10229"
    return development if development.is_dir() else bundled


class HotkeyListener(threading.Thread):
    def __init__(self, events: queue.Queue):
        super().__init__(daemon=True)
        self.events = events
        self.thread_id = None

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        ok8 = user32.RegisterHotKey(None, 8, 0, VK_F8)
        ok9 = user32.RegisterHotKey(None, 9, 0, VK_F9)
        self.events.put(("hotkey-status", bool(ok8), bool(ok9)))
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if int(msg.wParam) == 8:
                    self.events.put(("query", "explain"))
                elif int(msg.wParam) == 9:
                    self.events.put(("query", "translate"))
        if ok8:
            user32.UnregisterHotKey(None, 8)
        if ok9:
            user32.UnregisterHotKey(None, 9)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


class HuaciTongApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.events: queue.Queue = queue.Queue()
        self.listener = HotkeyListener(self.events)
        self.engine = LocalModelServer(runtime_path())
        self.busy = False
        self.installing = False
        self.cancel_install = False
        self.last_activity = 0.0
        self.history: list[dict[str, str]] = []
        self.popup: tk.Toplevel | None = None
        self.setup: tk.Toplevel | None = None
        self.tray_icon = None
        self.status_var: tk.StringVar | None = None
        self.progress_var: tk.DoubleVar | None = None
        self.install_button: tk.Button | None = None
        self.listener.start()
        self.setup_tray()
        self.root.after(60, self.process_events)
        self.root.after(10_000, self.release_idle_model)
        if not model_is_ready():
            self.root.after(250, self.show_setup)

    def setup_tray(self):
        try:
            import pystray
            from PIL import Image

            image = Image.open(resource_path("assets/quickgloss-logo.png"))
            menu = pystray.Menu(
                pystray.MenuItem("打开划词通", lambda: self.root.after(0, self.show_setup), default=True),
                pystray.MenuItem("退出", lambda: self.root.after(0, self.quit)),
            )
            self.tray_icon = pystray.Icon("HuaciTong", image, "划词通 · F8 解释 · F9 翻译", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            self.tray_icon = None

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "query":
                    self.begin_query(event[1])
                elif kind == "hotkey-status":
                    missing = [key for key, ok in (("F8", event[1]), ("F9", event[2])) if not ok]
                    if missing:
                        self.show_card("快捷键冲突", "、".join(missing) + " 已被其他程序占用，请关闭冲突程序后重启划词通。", error=True)
                elif kind == "result":
                    self.finish_query(event[1], event[2], event[3], event[4])
                elif kind == "install-progress":
                    self.update_install(event[1], event[2])
                elif kind == "install-complete":
                    self.finish_install(event[1])
        except queue.Empty:
            pass
        self.root.after(60, self.process_events)

    def selected_text(self) -> str:
        previous = ""
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                previous = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:
            previous = ""
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x43, 0, 0, 0)
        user32.keybd_event(0x43, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.16)
        selected = ""
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                selected = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)).strip()
            win32clipboard.EmptyClipboard()
            if previous:
                win32clipboard.SetClipboardText(previous, win32clipboard.CF_UNICODETEXT)
        except Exception:
            pass
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        return selected[:6000]

    def begin_query(self, mode: str):
        if self.busy:
            return
        if not model_is_ready():
            self.show_setup()
            return
        text = self.selected_text()
        if not text:
            self.show_card("没有读取到文字", "请先用鼠标选中一段文字，再按 F8 解释或 F9 翻译。", error=True)
            return
        parent = self.history[-1]["answer"] if self.history and mode == "explain" else ""
        self.busy = True
        self.show_loading(mode, text)
        threading.Thread(target=self.query_worker, args=(mode, text, parent), daemon=True).start()

    def query_worker(self, mode: str, text: str, parent: str):
        try:
            answer = self.engine.complete(mode, text, parent)
            self.events.put(("result", mode, text, answer, ""))
        except Exception as error:
            self.events.put(("result", mode, text, str(error), str(error)))

    def finish_query(self, mode: str, text: str, answer: str, error: str):
        self.busy = False
        self.last_activity = time.monotonic()
        if not error:
            self.history.append({"mode": mode, "text": text, "answer": answer})
        title = "翻译" if mode == "translate" else "解释"
        self.show_card(title, answer, source=text, error=bool(error))

    def release_idle_model(self):
        if self.engine.process and not self.busy and time.monotonic() - self.last_activity >= MODEL_IDLE_SECONDS:
            self.engine.stop()
        self.root.after(10_000, self.release_idle_model)

    def ensure_popup(self):
        if self.popup and self.popup.winfo_exists():
            return self.popup
        popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=LINE)
        popup.bind("<Escape>", lambda _event: popup.withdraw())
        popup.bind("<Alt-Left>", lambda _event: self.go_back())
        self.popup = popup
        return popup

    def clear_popup(self):
        popup = self.ensure_popup()
        for child in popup.winfo_children():
            child.destroy()
        return popup

    def position_popup(self, popup, width=440, height=390):
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        screen_w, screen_h = popup.winfo_screenwidth(), popup.winfo_screenheight()
        x = min(max(16, point.x + 18), screen_w - width - 16)
        y = min(max(16, point.y + 18), screen_h - height - 60)
        popup.geometry(f"{width}x{height}+{x}+{y}")

    def show_loading(self, mode: str, source: str):
        popup = self.clear_popup()
        header = tk.Frame(popup, bg=CARD, height=52)
        header.pack(fill="x", padx=1, pady=(1, 0))
        title = "正在翻译" if mode == "translate" else "正在解释"
        tk.Label(header, text=title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=18, pady=15)
        key = "F9" if mode == "translate" else "F8"
        tk.Label(header, text=key, bg=CARD_2, fg=SUBTLE, font=("Segoe UI", 9, "bold"), padx=8, pady=3).pack(side="right", padx=14)
        body = tk.Frame(popup, bg=CARD)
        body.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        tk.Label(body, text="本地模型正在理解选中内容…", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=20, pady=(32, 8))
        tk.Label(body, text=source[:90] + ("…" if len(source) > 90 else ""), bg=CARD, fg=SUBTLE, wraplength=395, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=20)
        self.position_popup(popup, height=230)
        popup.deiconify()
        popup.lift()

    def show_card(self, title: str, answer: str, source: str = "", error: bool = False):
        popup = self.clear_popup()
        header = tk.Frame(popup, bg=CARD, height=52)
        header.pack(fill="x", padx=1, pady=(1, 0))
        tk.Label(header, text=title, bg=CARD, fg=ERROR if error else TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=18, pady=15)
        tk.Button(header, text="×", command=popup.withdraw, bg=CARD, fg=SUBTLE, bd=0, font=("Microsoft YaHei UI", 15), activebackground=CARD_2, activeforeground=TEXT).pack(side="right", padx=9)
        body = tk.Frame(popup, bg=CARD)
        body.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        if source:
            tk.Label(body, text=source[:100] + ("…" if len(source) > 100 else ""), bg=CARD_2, fg=SUBTLE, wraplength=380, justify="left", anchor="w", padx=12, pady=8, font=("Microsoft YaHei UI", 9)).pack(fill="x", padx=18, pady=(14, 8))
        text = tk.Text(body, bg=CARD, fg=ERROR if error else TEXT, insertbackground=TEXT, selectbackground=ACCENT, relief="flat", bd=0, wrap="word", font=("Microsoft YaHei UI", 10), height=10)
        text.insert("1.0", answer)
        text.configure(state="disabled", cursor="arrow")
        text.pack(fill="both", expand=True, padx=18, pady=(8, 6))
        footer = tk.Frame(body, bg=CARD)
        footer.pack(fill="x", padx=14, pady=(4, 12))
        if len(self.history) > 1:
            self.small_button(footer, "← 返回", self.go_back).pack(side="left", padx=4)
        self.small_button(footer, "复制", lambda: self.copy_text(answer)).pack(side="left", padx=4)
        tk.Label(footer, text="可继续选词按 F8", bg=CARD, fg=SUBTLE, font=("Microsoft YaHei UI", 8)).pack(side="right", padx=5)
        self.position_popup(popup)
        popup.deiconify()
        popup.lift()
        text.configure(state="normal")

    def small_button(self, parent, label: str, command):
        return tk.Button(parent, text=label, command=command, bg=CARD_2, fg=TEXT, bd=0, padx=11, pady=5, font=("Microsoft YaHei UI", 9), activebackground=LINE, activeforeground=TEXT)

    def copy_text(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def go_back(self):
        if len(self.history) <= 1:
            return
        self.history.pop()
        item = self.history[-1]
        self.show_card("翻译" if item["mode"] == "translate" else "解释", item["answer"], item["text"])

    def show_setup(self):
        if self.setup and self.setup.winfo_exists():
            self.setup.deiconify()
            self.setup.lift()
            self.refresh_setup()
            return
        win = tk.Toplevel(self.root)
        self.setup = win
        win.title(APP_NAME)
        win.geometry("540x470")
        win.resizable(False, False)
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        try:
            win.iconbitmap(resource_path("assets/quickgloss.ico"))
        except Exception:
            pass
        tk.Label(win, text="划词通", bg=BG, fg=TEXT, font=("Microsoft YaHei UI", 24, "bold")).pack(anchor="w", padx=36, pady=(32, 2))
        tk.Label(win, text="选中即懂，按键即译", bg=BG, fg=SUBTLE, font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=36)
        shortcuts = tk.Frame(win, bg=BG)
        shortcuts.pack(fill="x", padx=28, pady=(26, 18))
        self.shortcut_card(shortcuts, "F8", "解释", "专业词、句子、概念", 0)
        self.shortcut_card(shortcuts, "F9", "翻译", "中英自动判断", 1)
        self.status_var = tk.StringVar()
        tk.Label(win, textvariable=self.status_var, bg=BG, fg=SUBTLE, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=36, pady=(4, 0))
        self.progress_var = tk.DoubleVar(value=0)
        style = ttk.Style(win)
        style.theme_use("clam")
        style.configure("H.Horizontal.TProgressbar", troughcolor=CARD_2, background=ACCENT, bordercolor=CARD_2, lightcolor=ACCENT, darkcolor=ACCENT)
        ttk.Progressbar(win, variable=self.progress_var, maximum=100, style="H.Horizontal.TProgressbar").pack(fill="x", padx=36, pady=(10, 18), ipady=2)
        tk.Label(win, text="本地运行 · 无需 API Key · 不上传选中文字", bg=BG, fg=SUBTLE, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=36)
        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=36, pady=(24, 0))
        self.install_button = tk.Button(buttons, command=self.primary_action, bg=ACCENT, fg="#ffffff", bd=0, padx=22, pady=10, font=("Microsoft YaHei UI", 10, "bold"), activebackground=ACCENT_HOVER, activeforeground="#ffffff")
        self.install_button.pack(side="right")
        tk.Button(buttons, text="最小化到托盘", command=win.withdraw, bg=CARD_2, fg=TEXT, bd=0, padx=18, pady=10, font=("Microsoft YaHei UI", 9), activebackground=LINE, activeforeground=TEXT).pack(side="right", padx=8)
        self.refresh_setup()

    def shortcut_card(self, parent, key: str, title: str, detail: str, column: int):
        card = tk.Frame(parent, bg=CARD, width=230, height=105)
        card.grid(row=0, column=column, padx=8, sticky="nsew")
        card.grid_propagate(False)
        parent.grid_columnconfigure(column, weight=1)
        tk.Label(card, text=key, bg=CARD_2, fg=ACCENT, font=("Segoe UI", 11, "bold"), padx=10, pady=5).place(x=15, y=17)
        tk.Label(card, text=title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).place(x=70, y=17)
        tk.Label(card, text=detail, bg=CARD, fg=SUBTLE, font=("Microsoft YaHei UI", 9)).place(x=16, y=67)

    def refresh_setup(self):
        if not self.status_var or not self.install_button or self.installing:
            return
        if model_is_ready():
            self.progress_var.set(100)
            self.status_var.set("本地模型已安装 · F8 / F9 已就绪")
            self.install_button.configure(text="开始使用", state="normal")
        else:
            self.progress_var.set(0)
            self.status_var.set("首次使用需要安装约 688 MB 的离线语言模型")
            self.install_button.configure(text="安装离线模型", state="normal")

    def primary_action(self):
        if model_is_ready():
            self.setup.withdraw()
        elif not self.installing:
            self.installing = True
            self.cancel_install = False
            self.install_button.configure(text="正在安装…", state="disabled")
            threading.Thread(target=self.install_worker, daemon=True).start()

    def install_worker(self):
        try:
            download_model(lambda done, total: self.events.put(("install-progress", done, total)), lambda: self.cancel_install)
            self.events.put(("install-complete", ""))
        except Exception as error:
            self.events.put(("install-complete", str(error)))

    def update_install(self, done: int, total: int):
        self.progress_var.set(min(99.5, done * 100 / max(total, 1)))
        self.status_var.set(f"正在安装 · {done / 1_000_000:.0f} / {total / 1_000_000:.0f} MB")

    def finish_install(self, error: str):
        self.installing = False
        if error:
            self.status_var.set(error)
            self.install_button.configure(text="继续安装", state="normal")
        else:
            self.progress_var.set(100)
            self.status_var.set("安装完成 · F8 / F9 已就绪")
            self.install_button.configure(text="开始使用", state="normal")

    def quit(self):
        self.cancel_install = True
        self.listener.stop()
        self.engine.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    HuaciTongApp().run()
