from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


APP_ID = "HuaciTong"
APP_NAME = "划词通"
MODEL_NAME = "MiniCPM5-1B"
MODEL_FILENAME = "MiniCPM5-1B-Q4_K_M.gguf"
MODEL_BYTES = 688_065_920
MODEL_SHA256 = "81b64d05a23b17b34c475f42b3e72fbde62d4b92cc34541f7a8031d0752deafa"
REVISION = "87007042419d30c1d8f38ef065424ee33870831e"
MODEL_URLS = (
    f"https://www.modelscope.cn/models/OpenBMB/MiniCPM5-1B-GGUF/resolve/master/{MODEL_FILENAME}",
    f"https://huggingface.co/openbmb/MiniCPM5-1B-GGUF/resolve/{REVISION}/{MODEL_FILENAME}?download=true",
)


def data_dir() -> Path:
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_ID
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def model_path() -> Path:
    folder = data_dir() / "models"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / MODEL_FILENAME


def file_sha256(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def model_is_ready(verify: bool = False) -> bool:
    target = model_path()
    if not target.is_file() or target.stat().st_size != MODEL_BYTES:
        return False
    return not verify or file_sha256(target) == MODEL_SHA256


def download_model(
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    destination = model_path()
    partial = destination.with_suffix(".gguf.part")
    if shutil.disk_usage(destination.parent).free < 1_100_000_000:
        raise RuntimeError("磁盘空间不足，请至少留出 1.1 GB 可用空间。")
    last_error: Exception | None = None
    for url in MODEL_URLS:
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > MODEL_BYTES:
                partial.unlink()
                offset = 0
            headers = {"User-Agent": "HuaciTong/2.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                resumed = offset > 0 and getattr(response, "status", None) == 206
                if offset and not resumed:
                    offset = 0
                done = offset
                with partial.open("ab" if resumed else "wb") as output:
                    while True:
                        if cancelled and cancelled():
                            raise RuntimeError("下载已暂停，下次会继续。")
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        done += len(block)
                        if progress:
                            progress(min(done, MODEL_BYTES), MODEL_BYTES)
            if partial.stat().st_size != MODEL_BYTES or file_sha256(partial) != MODEL_SHA256:
                partial.unlink(missing_ok=True)
                raise RuntimeError("模型校验失败，损坏文件已清除。")
            partial.replace(destination)
            if progress:
                progress(MODEL_BYTES, MODEL_BYTES)
            return destination
        except Exception as error:
            last_error = error
    raise RuntimeError(f"模型下载失败：{last_error}") from last_error


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_messages(mode: str, text: str, parent_context: str = "") -> list[dict[str, str]]:
    if mode == "translate":
        target = "自然、准确的英文" if re.search(r"[\u3400-\u9fff]", text) else "自然、准确的简体中文"
        instruction = f"把选中内容翻译成{target}。保留数字、代码、专有名词和原有段落，只输出译文。"
    else:
        instruction = (
            "用普通人一看就懂的简体中文解释选中内容。第一句直接说它是什么，再说明它在这里有什么用；"
            "必要时给一个很短的例子。总共不超过180个汉字，不复述任务。"
        )
    context = f"\n上一级解释：{parent_context[:1200]}" if parent_context else ""
    return [
        {"role": "system", "content": "你是准确、克制的中文划词助手。直接回答，不使用表格。"},
        {"role": "user", "content": f"{instruction}\n\n选中内容：{text}{context}"},
    ]


class LocalModelServer:
    def __init__(self, runtime_dir: Path, model: Path | None = None):
        self.runtime_dir = runtime_dir
        self.model = model or model_path()
        self.port = _free_port()
        self.api_token = secrets.token_urlsafe(24)
        self.process: subprocess.Popen | None = None
        self._log_stream = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_ready(self) -> bool:
        try:
            request = urllib.request.Request(
                f"{self.base_url}/health", headers={"Authorization": f"Bearer {self.api_token}"}
            )
            with urllib.request.urlopen(request, timeout=0.4) as response:
                return response.status == 200
        except Exception:
            return False

    def start(self, timeout: float = 70.0) -> None:
        if self.is_ready():
            return
        if not model_is_ready():
            raise RuntimeError("离线语言模型尚未安装。")
        executable = self.runtime_dir / "llama-server.exe"
        if not executable.is_file():
            raise RuntimeError("本地推理组件缺失，请重新下载划词通。")
        self.stop()
        threads = max(2, min(6, (os.cpu_count() or 4) - 1))
        command = [
            str(executable), "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
            "-c", "4096", "-t", str(threads), "-b", "256", "-ub", "256", "-np", "1",
            "--api-key", self.api_token, "--no-webui",
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        self._log_stream = (data_dir() / "server.log").open("w", encoding="utf-8", errors="replace")
        self.process = subprocess.Popen(
            command, cwd=self.runtime_dir, stdin=subprocess.DEVNULL,
            stdout=self._log_stream, stderr=subprocess.STDOUT, creationflags=flags,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.stop()
                raise RuntimeError("模型启动失败，可能是内存不足。")
            if self.is_ready():
                return
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("模型启动超时，请关闭占用内存较多的程序后重试。")

    def complete(self, mode: str, text: str, parent_context: str = "", timeout: int = 100) -> str:
        self.start()
        payload = json.dumps({
            "model": MODEL_NAME,
            "messages": build_messages(mode, text, parent_context),
            "max_tokens": 300,
            "temperature": 0.2 if mode == "translate" else 0.45,
            "top_p": 0.9,
            "chat_template_kwargs": {"enable_thinking": False},
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"本地模型出错：{detail[:200]}") from error
        except urllib.error.URLError as error:
            raise RuntimeError("本地模型暂时没有响应，请稍后再试。") from error
        content = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        if not content:
            raise RuntimeError("模型没有返回可读内容。")
        return content

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
        if self._log_stream:
            self._log_stream.close()
            self._log_stream = None
