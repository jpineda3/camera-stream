import subprocess
import threading
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

app = FastAPI()

DEVICE = "/dev/video4"
WIDTH = 1920
HEIGHT = 1080
FPS = 30


class Camera:
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        cmd = [
            "ffmpeg",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-framerate", str(FPS),
            "-i", DEVICE,
            "-c:v", "mjpeg",
            "-q:v", "3",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start == -1:
                    buf = b""
                    break
                end = buf.find(b"\xff\xd9", start + 2)
                if end == -1:
                    buf = buf[start:]
                    break
                frame = buf[start:end + 2]
                buf = buf[end + 2:]
                with self.lock:
                    self.frame = frame

    def get_frame(self):
        with self.lock:
            return self.frame


camera = Camera()


def generate_frames():
    while True:
        frame = camera.get_frame()
        if frame is None:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )


@app.get("/")
def index():
    return HTMLResponse(
        """<!DOCTYPE html>
<html>
<head><title>Camera Stream</title></head>
<body style="margin:0;background:#111;display:flex;align-items:center;justify-content:center;height:100vh">
  <img src="/stream" style="max-width:100%;max-height:100vh">
</body>
</html>"""
    )


@app.get("/stream")
def stream():
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)
