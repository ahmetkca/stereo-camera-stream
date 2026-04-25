# Agent Instructions

This repository is the canonical project root for the Raspberry Pi 5 Waveshare IMX219-83 stereo camera streaming experiments. Treat parent directories as local workspace scaffolding, not as part of this repo.

## Project Goal

- Build and compare stereo camera streaming implementations for the Waveshare IMX219-83 stereo camera on Raspberry Pi 5.
- The main robotics target is LeRobot data collection and teleoperation for an open-source SO-ARM101/SO101 setup with one follower arm and one leader arm.
- The most important current implementation is `lerobot-zmq/`, which publishes stereo frames in the JSON-over-ZeroMQ schema expected by LeRobot's `ZMQCamera`.

## Local Environment

- Development commonly happens from WSL2 Ubuntu 24.04 on a Windows 11 host.
- WSL2 may not resolve `raspberrypi5.local`.
- To reach the Raspberry Pi 5 over mDNS, use the Windows SSH client from WSL:

```bash
ssh.exe ahmetkca@raspberrypi5.local
```

- If an explicit Pi IP is known, normal `ssh ahmetkca@<ip>` from WSL is also fine.

## Repository Layout

- `lerobot-zmq/` - LeRobot-compatible ZMQ stereo transport.
  - `pi-side/publisher.py` runs on the Raspberry Pi and publishes `left` and `right` JPEG frames.
  - `host-side/consumer.py` runs on the host for previewing and validating the Pi-side stream.
- `mjpeg-http/`, `gstreamer/`, `websocket-jpeg/`, `webrtc/`, `rtsp-mediamtx/`, `depth-map/` - alternative streaming experiments.
- `shared/` - shared camera tuning and calibration material.
- `.worktrees/` - local git worktrees. This is ignored and should not be committed.
- `.context/` - ignored local reference checkouts of external projects. Use this for source-code research.

## `.context` Reference Repos

External repositories used for direct source-code reference should be cloned under `.context/` and must remain untracked.

Known useful checkouts:

```bash
git clone https://github.com/huggingface/lerobot.git .context/lerobot
git clone https://github.com/TheRobotStudio/SO-ARM100.git .context/SO-ARM100
```

When researching LeRobot behavior, prefer local files under `.context/lerobot` before web browsing. Key paths:

- `.context/lerobot/src/lerobot/cameras/zmq/camera_zmq.py`
- `.context/lerobot/src/lerobot/cameras/zmq/configuration_zmq.py`
- `.context/lerobot/src/lerobot/cameras/zmq/image_server.py`
- `.context/lerobot/src/lerobot/robots/so_follower/so_follower.py`
- `.context/lerobot/src/lerobot/robots/so_follower/config_so_follower.py`
- `.context/lerobot/src/lerobot/scripts/lerobot_teleoperate.py`
- `.context/lerobot/src/lerobot/scripts/lerobot_record.py`
- `.context/lerobot/docs/source/cameras.mdx`
- `.context/lerobot/docs/source/so101.mdx`
- `.context/lerobot/docs/source/il_robots.mdx`
- `.context/lerobot/docs/source/hil_data_collection.mdx`
- `.context/lerobot/docs/source/introduction_processors.mdx`

For SO-ARM100/SO101 hardware and optional camera mounts, start with:

- `.context/SO-ARM100/README.md`
- `.context/SO-ARM100/SO100.md`
- `.context/SO-ARM100/3DPRINT.md`
- `.context/SO-ARM100/media/`
- `.context/SO-ARM100/STL/`
- `.context/SO-ARM100/STEP/`

Do not commit `.context/` contents or depend on them at runtime.

## LeRobot ZMQ Compatibility

LeRobot's `ZMQCamera` expects a publisher that sends JSON strings shaped like:

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

The keys under `images` and `timestamps` are LeRobot camera names. In this repo they default to `left` and `right`.

Example Pi-side publisher:

```bash
cd lerobot-zmq/pi-side
uv run publisher.py --bind-host 0.0.0.0 --port 5555 --width 1280 --height 720 --fps 15
```

Example host-side preview:

```bash
cd lerobot-zmq/host-side
uv run consumer.py --server-address <PI_LAN_IP> --port 5555
```

Example LeRobot camera configuration for a follower robot using the same publisher:

```bash
--robot.cameras='{
  left:  {type: zmq, server_address: "<PI_LAN_IP>", port: 5555, camera_name: "left",  width: 1280, height: 720, fps: 15},
  right: {type: zmq, server_address: "<PI_LAN_IP>", port: 5555, camera_name: "right", width: 1280, height: 720, fps: 15}
}'
```

When changing the ZMQ publisher, keep the LeRobot subscriber contract in mind:

- `ZMQCameraConfig.camera_name` selects one image from a multi-camera JSON message.
- `SOFollower.get_observation()` reads configured cameras with `cam.read_latest()`.
- Camera feature shapes come from configured `height` and `width`; keep CLI examples and publisher defaults aligned.
- Color-channel handling is easy to regress. Preserve tests and document any `RGB888`, BGR, OpenCV, or JPEG encoder changes.

## Development Commands

Use `uv run` inside the relevant subproject.

Pi-side protocol tests:

```bash
cd lerobot-zmq/pi-side
uv run pytest
```

Host-side protocol tests:

```bash
cd lerobot-zmq/host-side
uv run pytest
```

Other implementations usually have their own `pyproject.toml`, `mise.toml`, or README. Read the local README before changing commands.

## Engineering Guidelines

- Prefer small, focused changes in the implementation being worked on.
- Keep Pi-side code and host-side test/preview code separate unless a shared protocol helper is clearly worth extracting.
- Avoid adding runtime dependencies to the Pi-side path unless they are available and practical on Raspberry Pi OS.
- Preserve hardware-specific behavior such as camera tuning files, sensor size, transforms, frame rate controls, and color encoding unless the change is intentionally tested on the Pi.
- Never assume `.context` repos are present in another clone. If committed docs reference them, describe how to clone them.
- Do not modify vendored or reference repos under `.context`; if a change is needed upstream, make it in the correct upstream checkout or document it separately.

## Git Notes

- This repo may have local worktrees under `.worktrees/`; do not delete or rewrite them unless explicitly asked.
- Check `git status --short --branch` before editing.
- Do not revert unrelated user changes.
- Keep `.context/`, `.worktrees/`, virtual environments, captured images, and video outputs untracked.
