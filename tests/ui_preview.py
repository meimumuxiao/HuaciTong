from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import HuaciTongApp

app = HuaciTongApp()
app.root.after(200, app.show_setup)
app.root.after(20_000, app.quit)
app.run()
