# Motion-triggered capture

Motion detection is implemented; person/animal recognition and AI photo selection are not.

## Mac: replay a video

From the repository root, use a Python interpreter with a working certificate store:

```sh
python3 -m venv .venv
.venv/bin/pip install -r device/requirements-motion.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python device/watch.py --config device/config.example.json --video /absolute/path/to/clip.mp4
.venv/bin/python device/camera.py --config device/config.example.json --status
```

Replay runs faster than real time. Motion timing and cooldown use video frame time; uploaded capture dates use replay time. All replay captures have `is_mock=true`. Replay is **offline by default**. Use a separate `queue_dir` in a copy of the config to isolate experiments. To intentionally upload the queued test captures, run `device/camera.py --config device/config.json --upload-only`, or run replay with the real config and `--upload`. Real video uploaded this way becomes public in the archive.

The automated replay test generates a short video containing a moving rectangle and verifies one scheduled image plus a grouped three-shot burst. No personal video is needed for the tests.

## Pi: enable motion mode

Keep the existing scheduled-only setup available as a fallback. Stop the service before replacing files or running another capture process.

```sh
sudo systemctl stop backyard-camera
sudo apt update
sudo apt install -y python3-picamera2 python3-numpy
```

Copy `device/camera.py`, `device/motion.py`, and `device/watch.py` from the repository to `/opt/backyard-camera/device/` (root-owned, mode 644). Picamera2 must come from Raspberry Pi OS apt packages; do not install the Mac OpenCV requirements on the Pi. It only needs NumPy and Picamera2.

The existing device config continues to work with defaults. Optionally copy the `motion` section from `config.example.json` into `/etc/backyard-camera.json`, retaining your own credentials and absolute `queue_dir`.

First test in the foreground (Ctrl-C to stop):

```sh
sudo -u backyard /usr/bin/python3 /opt/backyard-camera/device/watch.py --config /etc/backyard-camera.json --offline
sudo -u backyard /usr/bin/python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --status
```

Walk into the camera's view and inspect the logs for `trigger=motion` and three shared event IDs. Then drain the queue with `--upload-only` and check the website. To enable service mode:

```sh
sudo systemctl edit backyard-camera
```

Paste this override:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 /opt/backyard-camera/device/watch.py --config /etc/backyard-camera.json
```

Then:

```sh
sudo systemctl daemon-reload
sudo systemctl restart backyard-camera
sudo journalctl -u backyard-camera -n 40 --no-pager
```

For scheduled-only fallback, edit that same override and set the executable back to `device/camera.py`, then reload/restart. Updated `camera.py` reads both old and new queues. Do not roll back to an old copy of that file after the queue has gained motion columns.

## Defaults and tuning

| Setting | Default | Meaning |
|---|---:|---|
| preview_fps | 5 | Frames checked per second (1–10) |
| pixel_threshold | 25 | Minimum grayscale difference per pixel |
| changed_fraction | 0.02 | At least 2% of unmasked pixels must change |
| consecutive_frames | 3 | Sustained changes required |
| warmup_seconds | 3 | Allow exposure/autofocus to settle |
| burst_count | 3 | Stills per event (maximum 10) |
| burst_spacing_seconds | 1 | Seconds between burst frames |
| cooldown_seconds | 30 | Minimum interval between burst starts |
| ignore_regions | [] | Rectangles excluded from detection |

For a tree occupying the top-left quarter: `"ignore_regions": [[0, 0, 0.5, 0.5]]`. Coordinates are normalized fractions `[left, top, right, bottom]`. Ignoring an area affects detection, not the saved photograph. Do not mask the entire image.

The detector compares consecutive grayscale frames and subtracts a global brightness offset. This helps with exposure changes but cannot eliminate shadows, rain, camera shake or moving leaves. Tiny/distant/slow-moving subjects can be missed. Lower `changed_fraction` for sensitivity; increase it or mask noisy areas to reduce triggers.

Motion bursts do not block preview analysis. A motion capture at a scheduled deadline also satisfies that deadline; quiet periods still produce five-minute photographs. The normal offline queue, disk budget and separate uploader apply. The Pi holds a single camera session with a 320×180 luminance stream and 2304×1296 still stream. Preview alignment may adjust the small stream dimensions. No continuous video is saved or streamed.

## Hardware acceptance checks

Pi 3 A+ throughput and memory use remain unmeasured. Confirm autofocus, JPEG colours, CPU/RAM, five-minute baseline, burst timing, disk limit behavior, reboot startup and real offline recovery. If encoding slows capture, reduce main resolution in `PiSource` or preview FPS. Actual timing depends on the hardware; no claim of precise one-second spacing is made until measured.

Reference: [official Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf).
