#!/usr/bin/env python3
import io
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

PORT = 8080
RESOLUTION = (1280, 720)
SENSOR_SIZE = (3280, 2464)   # full sensor readout for max FOV
JPEG_QUALITY = 80

INDEX_HTML = b"""<!DOCTYPE html>
<html>
<head>
  <title>Stereo Camera</title>
  <style>
    body { margin: 0; background: #111; display: flex; }
    .view { position: relative; flex: 1; }
    img { width: 100%; display: block; }
    label {
      position: absolute; top: 8px; left: 8px;
      color: #0f0; font: bold 14px monospace;
      text-shadow: 1px 1px 2px #000;
    }
  </style>
</head>
<body>
  <div class="view">
    <img src="/stream/left">
    <label>LEFT (cam0)</label>
  </div>
  <div class="view">
    <img src="/stream/right">
    <label>RIGHT (cam1)</label>
  </div>
</body>
</html>"""


class CameraOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


output0 = CameraOutput()
output1 = CameraOutput()


def start_cameras():
    tuning_file = Path(__file__).parent / "imx219_waveshare.json"
    tuning = Picamera2.load_tuning_file(str(tuning_file))

    cam0 = Picamera2(0, tuning=tuning)
    cam1 = Picamera2(1, tuning=tuning)

    sensor = {"output_size": SENSOR_SIZE, "bit_depth": 10}
    flip = Transform(hflip=True, vflip=True)

    cfg0 = cam0.create_video_configuration(
        main={"size": RESOLUTION},
        sensor=sensor,
        transform=flip,
    )
    cfg1 = cam1.create_video_configuration(
        main={"size": RESOLUTION},
        sensor=sensor,
        transform=flip,
    )

    cam0.configure(cfg0)
    cam1.configure(cfg1)

    cam0.start_recording(MJPEGEncoder(), FileOutput(output0))
    cam1.start_recording(MJPEGEncoder(), FileOutput(output1))

    print("Both cameras started")


class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.end_headers()
            self.wfile.write(INDEX_HTML)
        elif self.path == "/stream/left":
            self._serve_mjpeg(output0)
        elif self.path == "/stream/right":
            self._serve_mjpeg(output1)
        else:
            self.send_error(404)

    def _serve_mjpeg(self, output):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    start_cameras()
    server = ThreadedHTTPServer(("0.0.0.0", PORT), StreamHandler)
    print(f"Streaming at http://raspberrypi5.local:{PORT}")
    server.serve_forever()
