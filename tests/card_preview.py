from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab
from app import HuaciTongApp

app = HuaciTongApp()
app.history.append({"mode": "explain", "text": "Transformer", "answer": "Transformer 是一种主要依靠注意力机制处理序列信息的神经网络架构。它能并行理解上下文，常用于文本生成、翻译和图像理解。"})
app.show_card("解释", app.history[-1]["answer"], app.history[-1]["text"])

def capture():
    ImageGrab.grab(window=app.popup.winfo_id()).save("card-window.png")
    app.quit()

app.root.after(800, capture)
app.run()
