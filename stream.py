#!/usr/bin/env python3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np
from libcamera import Transform
from picamera2 import Picamera2
from pathlib import Path

PORT = 8080
RESOLUTION = (1920, 1080)
SENSOR_SIZE = (3280, 2464)   # full sensor readout for max FOV, ISP scales to RESOLUTION
JPEG_QUALITY = 80
TARGET_FPS = 20

latest_frame = None
frame_lock = threading.Lock()


def capture_loop():
    global latest_frame

    tuning_file = Path(__file__).parent / "imx219_waveshare.json"
    tuning = Picamera2.load_tuning_file(str(tuning_file))

    cam0 = Picamera2(0, tuning=tuning)
    cam1 = Picamera2(1, tuning=tuning)

    sensor = {"output_size": SENSOR_SIZE, "bit_depth": 10}
    flip = Transform(hflip=True, vflip=True)
    cfg0 = cam0.create_video_configuration(main={"size": RESOLUTION, "format": "RGB888"}, sensor=sensor, transform=flip)
    cfg1 = cam1.create_video_configuration(main={"size": RESOLUTION, "format": "RGB888"}, sensor=sensor, transform=flip)

    cam0.configure(cfg0)
    cam1.configure(cfg1)

    cam0.start()
    cam1.start()

    print("Both cameras started")

    frame_interval = 1.0 / TARGET_FPS
    while True:
        t_start = time.monotonic()

        f0 = cam0.capture_array("main")
        f1 = cam1.capture_array("main")

        cv2.putText(f0, "LEFT  (cam0)", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(f1, "RIGHT (cam1)", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        combined = np.hstack((f0, f1))

        ok, buf = cv2.imencode(".jpg", combined, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue

        with frame_lock:
            latest_frame = buf.tobytes()

        elapsed = time.monotonic() - t_start
        sleep_for = frame_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)


class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._serve_index()
        elif self.path == "/stream":
            self._serve_mjpeg()
        else:
            self.send_error(404)

    def _serve_index(self):
        html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Stereo Camera</title>
  <style>
    body {{ margin: 0; background: #111; }}
    img  {{ width: 100%; display: block; }}
  </style>
</head>
<body>
  <img src="/stream"/>
</body>
</html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with frame_lock:
                    frame = latest_frame
                if frame is None:
                    time.sleep(0.01)
                    continue
                self.wfile.write(
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()

    print("Waiting for first frame...")
    while latest_frame is None:
        time.sleep(0.05)

    server = HTTPServer(("0.0.0.0", PORT), StreamHandler)
    print(f"Streaming at http://raspberrypi5.local:{PORT}")
    server.serve_forever()
