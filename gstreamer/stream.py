#!/usr/bin/env python3
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

Gst.init(None)

PORT = 8080
WIDTH = 1280
HEIGHT = 720
FRAMERATE = 15
JPEG_QUALITY = 80

# Camera device names (libcamera pipeline handler IDs for Pi 5)
CAM0 = "/base/axi/pcie@1000120000/rp1/i2c@88000/imx219@10"
CAM1 = "/base/axi/pcie@1000120000/rp1/i2c@80000/imx219@10"

INDEX_HTML = b"""<!DOCTYPE html>
<html>
<head>
  <title>Stereo Camera (GStreamer)</title>
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
    <img id="left" src="/stream/left">
    <label id="lbl-left">LEFT (cam0)</label>
  </div>
  <div class="view">
    <img id="right" src="/stream/right">
    <label id="lbl-right">RIGHT (cam1)</label>
  </div>
  <script>
    function trackFps(imgId, lblId, name) {
      const img = document.getElementById(imgId);
      const lbl = document.getElementById(lblId);
      let frames = 0, last = Date.now();
      img.addEventListener('load', () => {
        frames++;
        const now = Date.now();
        if (now - last >= 1000) {
          lbl.textContent = name + ' ' + frames + ' fps';
          frames = 0;
          last = now;
        }
      });
    }
    trackFps('left',  'lbl-left',  'LEFT (cam0)');
    trackFps('right', 'lbl-right', 'RIGHT (cam1)');
  </script>
</body>
</html>"""


class CameraStream:
    """Wraps a single GStreamer pipeline and exposes the latest JPEG frame."""

    def __init__(self, camera_name: str):
        self.frame: bytes | None = None
        self.condition = threading.Condition()

        pipeline_str = (
            f"libcamerasrc camera-name={camera_name} ! "
            f"video/x-raw,format=NV12,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 ! "
            f"videoflip method=rotate-180 ! "
            f"videoconvert ! "
            f"jpegenc quality={JPEG_QUALITY} ! "
            f"appsink name=sink emit-signals=true sync=false drop=true max-buffers=1"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            data = bytes(info.data)
            buf.unmap(info)
            with self.condition:
                self.frame = data
                self.condition.notify_all()
        return Gst.FlowReturn.OK

    def start(self):
        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self._pipeline.set_state(Gst.State.NULL)


cam0_stream = CameraStream(CAM0)
cam1_stream = CameraStream(CAM1)


class StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(INDEX_HTML)))
            self.end_headers()
            self.wfile.write(INDEX_HTML)
        elif self.path == "/stream/left":
            self._serve_mjpeg(cam0_stream)
        elif self.path == "/stream/right":
            self._serve_mjpeg(cam1_stream)
        else:
            self.send_error(404)

    def _serve_mjpeg(self, stream: CameraStream):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with stream.condition:
                    stream.condition.wait()
                    frame = stream.frame
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
    # GLib main loop handles GStreamer bus messages in background
    loop = GLib.MainLoop()
    threading.Thread(target=loop.run, daemon=True).start()

    cam0_stream.start()
    cam1_stream.start()
    print("Both cameras started (GStreamer)")

    server = ThreadedHTTPServer(("0.0.0.0", PORT), StreamHandler)
    print(f"Streaming at http://raspberrypi5.local:{PORT}")
    server.serve_forever()
