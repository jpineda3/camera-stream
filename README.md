# camera-stream

MJPEG camera streaming service over HTTP. Uses ffmpeg to capture frames from a V4L2 camera device and serves them via FastAPI as a browser-viewable MJPEG stream on port 8888.

---

## Prerequisites

- Ubuntu/Debian Linux with a USB or integrated camera
- Python 3.10+
- ffmpeg
- v4l-utils (for camera identification)

Install system dependencies:

```bash
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3-pip
```

---

## 1. Identify Your Camera Device

### List connected cameras

```bash
v4l2-ctl --list-devices
```

Example output:

```
HIK 1080P USB CAMERA: HIK 1080P (usb-0000:00:14.0-2.3.2):
        /dev/video4
        /dev/video5
        /dev/media2

Integrated_Webcam_FHD: Integrat (usb-0000:00:14.0-6):
        /dev/video0
        /dev/video1
        /dev/video2
        /dev/video3
```

Each camera typically registers multiple `/dev/videoN` entries. The **first** device listed under each camera is the one that provides the video capture stream. The others are metadata or infrared interfaces.

### Verify the device supports MJPEG capture

```bash
v4l2-ctl --device=/dev/video4 --list-formats-ext
```

Look for a line containing `'MJPG' (Motion-JPEG, compressed)` with your desired resolution listed. For example:

```
[0]: 'MJPG' (Motion-JPEG, compressed)
        Size: Discrete 1920x1080
                Interval: Discrete 0.033s (30.000 fps)
```

If MJPEG is not listed, the device won't work with this service's default configuration. Only MJPEG-capable devices are supported.

### Quick capture test

Verify the camera actually produces frames:

```bash
ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 30 -i /dev/video4 -frames:v 1 -y /tmp/test.jpg
```

If this produces `/tmp/test.jpg` without errors, your camera and device path are correct.

---

## 2. Add Your User to the `video` Group

Camera devices under `/dev/video*` are owned by the `video` group. Your service user must be a member to access them without root.

### Check current groups

```bash
groups $USER
```

### Add to the `video` group

```bash
sudo usermod -aG video $USER
```

**You must log out and back in** (or reboot) for the group change to take effect. Verify with:

```bash
groups $USER
# Should include "video" in the list
```

### Verify device access

```bash
test -r /dev/video4 && echo "OK: device is readable" || echo "FAIL: no read access"
```

---

## 3. Configure the Application

Edit `main.py` and set the constants at the top of the file to match your camera:

```python
DEVICE = "/dev/video4"    # your camera's device path from step 1
WIDTH = 1920              # resolution width
HEIGHT = 1080             # resolution height
FPS = 30                  # framerate
```

These values must match a format the camera actually supports (as listed by `v4l2-ctl --list-formats-ext`). If the resolution/framerate combo doesn't match, ffmpeg will fail to open the device.

---

## 4. Install Python Dependencies

```bash
cd /home/svc_edgeai/camera-stream
pip install -r requirements.txt
```

The dependencies are:

| Package  | Purpose                      |
|----------|------------------------------|
| fastapi  | HTTP server and routing      |
| uvicorn  | ASGI server to run FastAPI   |

---

## 5. Test Manually

Run the server directly to confirm everything works:

```bash
python3 main.py
```

Open a browser and navigate to:

```
http://<machine-ip>:8888
```

You should see a live MJPEG stream from the camera. The raw stream is also available at `/stream`.

Press `Ctrl+C` to stop.

---

## 6. Set Up the Systemd Service

### Copy the service file

```bash
sudo cp camera-stream.service /etc/systemd/system/camera-stream.service
```

### Review the service configuration

The service file runs as user `svc_edgeai` by default. If your user is different, edit the file:

```bash
sudo nano /etc/systemd/system/camera-stream.service
```

```ini
[Unit]
Description=Camera Stream Service
After=network.target

[Service]
Type=simple
User=svc_edgeai
WorkingDirectory=/home/svc_edgeai/camera-stream
ExecStart=/usr/bin/python3 /home/svc_edgeai/camera-stream/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Fields to adjust for your setup:

| Field            | Description                              |
|------------------|------------------------------------------|
| `User`           | The Linux user that runs the service     |
| `WorkingDirectory` | Path to the camera-stream directory    |
| `ExecStart`      | Full path to python3 and main.py         |

### Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-stream.service
sudo systemctl start camera-stream.service
```

### Check the service status

```bash
sudo systemctl status camera-stream.service
```

### View logs

```bash
journalctl -u camera-stream.service -f
```

### Restart after config changes

```bash
sudo systemctl restart camera-stream.service
```

---

## Troubleshooting

### "Permission denied" on `/dev/videoN`

Your user is not in the `video` group, or you haven't logged out/back in since adding them. See step 2.

### ffmpeg exits immediately / no frames

- Verify the device path is correct: `v4l2-ctl --list-devices`
- Verify the resolution and framerate match a supported format: `v4l2-ctl --device=/dev/video4 --list-formats-ext`
- Check if another process has the camera open: `fuser /dev/video4`

### Camera device path changed after reboot

USB cameras can get reassigned different `/dev/videoN` numbers after a reboot depending on enumeration order. To get a stable device path, use a udev rule:

```bash
# Find your camera's unique attributes
udevadm info --query=all --name=/dev/video4 | grep -E "ID_SERIAL|ID_VENDOR|ID_MODEL"

# Create a udev rule (example for HIK camera)
sudo tee /etc/udev/rules.d/99-camera.rules << 'EOF'
SUBSYSTEM=="video4linux", ATTRS{idVendor}=="2bdf", ATTRS{idProduct}=="0291", ATTR{index}=="0", SYMLINK+="camera_hik"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then use `/dev/camera_hik` as your `DEVICE` in `main.py`.

### Stream is laggy or choppy

- Lower the resolution (e.g., `1280x720`)
- Lower the framerate (e.g., `15`)
- Check USB bandwidth — multiple USB cameras on the same USB controller can starve each other
- Use `htop` to check CPU usage; MJPEG decoding/encoding is CPU-intensive

### Port 8888 already in use

```bash
sudo lsof -i :8888
```

Kill the conflicting process or change the port in `main.py` at the `uvicorn.run()` call.

---

## Architecture

```
USB Camera
    │
    ▼
/dev/videoN (V4L2 device)
    │
    ▼
ffmpeg (captures MJPEG frames via v4l2, pipes to stdout)
    │
    ▼
Camera class (reads stdout pipe, extracts JPEG frames by SOI/EOI markers)
    │
    ▼
FastAPI endpoints
    ├── GET /        → HTML page with embedded <img> tag
    └── GET /stream  → multipart/x-mixed-replace MJPEG stream
    │
    ▼
Browser (renders live video)
```
