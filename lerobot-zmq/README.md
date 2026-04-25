# LeRobot ZMQ

This directory contains a LeRobot-compatible stereo camera transport for the Raspberry Pi 5 setup in this repository.

- `pi-side/` publishes `left` and `right` frames from the Waveshare IMX219-83 stereo camera using Picamera2.
- `host-side/` subscribes to the same stream from the host machine, decodes both images, and shows a live OpenCV preview with diagnostics.

The Pi-side publisher uses LeRobot's current ZMQ camera message schema:

```json
{
  "timestamps": {
    "left": 1713916800.0,
    "right": 1713916800.01
  },
  "metadata": {
    "left": {
      "wall_time_s": 1713916800.0,
      "sensor_timestamp_ns": 123456789000
    },
    "right": {
      "wall_time_s": 1713916800.01,
      "sensor_timestamp_ns": 123456837000
    }
  },
  "images": {
    "left": "<base64-jpeg>",
    "right": "<base64-jpeg>"
  }
}
```

The top-level `timestamps` remain wall-clock seconds for compatibility. `metadata` is extra diagnostic data; LeRobot's `ZMQCamera` ignores it today, but the benchmark and publisher stats can use `sensor_timestamp_ns` to report camera-driver timestamp skew when Picamera2 provides it.

Example Pi-side run:

```bash
cd pi-side
uv run publisher.py --bind-host 0.0.0.0 --port 5555 --width 1280 --height 720 --fps 15
```

Enable low-overhead aggregate publisher stats by logging every N frames:

```bash
cd pi-side
uv run publisher.py --bind-host 0.0.0.0 --port 5555 --width 1280 --height 720 --fps 15 --stats-interval 60
```

Run a finite Pi-side pipeline benchmark without a host subscriber:

```bash
cd pi-side
uv run tools/benchmark_pipeline.py --width 1280 --height 720 --fps 15 --frames 300 --output-json benchmark-1280x720-15fps.json
```

Example host-side run:

```bash
cd host-side
uv run consumer.py --server-address <PI_LAN_IP> --port 5555
```
