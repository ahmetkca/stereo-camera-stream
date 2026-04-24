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
  "images": {
    "left": "<base64-jpeg>",
    "right": "<base64-jpeg>"
  }
}
```

Example Pi-side run:

```bash
cd pi-side
uv run publisher.py --bind-host 0.0.0.0 --port 5555 --width 1280 --height 720 --fps 15
```

Example host-side run:

```bash
cd host-side
uv run consumer.py --server-address <PI_LAN_IP> --port 5555
```
