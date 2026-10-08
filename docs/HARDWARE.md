# Pi 3 A+ + Camera Module 3 bring-up

Do the cloud mock upload first. The Pi runs only Python and `rpicam-still`; do not build Next.js on its 512 MB RAM.

## 1. Prepare the card and camera

1. Use Raspberry Pi Imager on your Mac. Select Raspberry Pi 3 A+ and a current Raspberry Pi OS Lite image (Bookworm or later; 32-bit Lite is a conservative option for this board). The card will be erased by Imager: check you selected the intended 32 GB microSD.
2. In Imager customization set hostname `backyard-camera`, your own login user, a strong password or SSH public key, Wi-Fi SSID/password, WLAN country, and timezone. Enable SSH. Save these privately. The 3 A+ has no Ethernet; Wi-Fi must be configured before headless boot.
3. Disconnect Pi power. Fit the Camera Module 3 using the Pi 3's standard 15-pin ribbon. Open the CSI connector latch gently, insert straight with contacts facing the connector's contacts (on Pi 3 the blue backing faces toward the USB side), then close the latch. Follow the linked hardware guide if orientation is unclear. Never connect/remove it while powered.
4. Insert the microSD, connect the official 5.1 V / 2.5 A supply and allow several minutes for first boot.

## 2. Confirm basic camera capture

Replace `YOUR_USER` below with the Imager login:

```sh
ssh YOUR_USER@backyard-camera.local
sudo apt update
sudo apt install -y python3 rpicam-apps-lite
rpicam-hello --list-cameras
rpicam-still --nopreview --timeout 2000 --autofocus-mode auto --width 2304 --height 1296 --quality 85 --output /tmp/backyard-test.jpg
ls -lh /tmp/backyard-test.jpg
timedatectl status
```

Expected: the camera list shows an IMX708, a nonempty JPEG is created, and system time is synchronized. If package `rpicam-apps-lite` is unavailable for your chosen image, use `rpicam-apps`. On Bookworm and later, use `rpicam-*`, not legacy `raspistill`. Camera Module 3 is unsupported by the legacy camera stack.

From the Mac inspect the result:

```sh
scp YOUR_USER@backyard-camera.local:/tmp/backyard-test.jpg ./backyard-test.jpg
open ./backyard-test.jpg
```

If no camera: power off, reseat ribbon at both ends, ensure the current OS has `camera_auto_detect=1` in `/boot/firmware/config.txt`, then retry. Do not enable legacy camera mode. If `.local` fails, use the IP shown by your router.

## 3. Install the device files

From this repository on your Mac:

```sh
scp device/camera.py device/backyard-camera.service YOUR_USER@backyard-camera.local:/tmp/
scp device/config.json YOUR_USER@backyard-camera.local:/tmp/backyard-camera.json
```

On the Pi:

```sh
sudo useradd --system --user-group --home-dir /var/lib/backyard-camera --shell /usr/sbin/nologin backyard
sudo usermod -aG video,render backyard
sudo install -d -o root -g root -m 755 /opt/backyard-camera/device
sudo install -d -o backyard -g backyard -m 700 /var/lib/backyard-camera
sudo install -o root -g root -m 644 /tmp/camera.py /opt/backyard-camera/device/camera.py
sudo install -o backyard -g backyard -m 600 /tmp/backyard-camera.json /etc/backyard-camera.json
sudo install -o root -g root -m 644 /tmp/backyard-camera.service /etc/systemd/system/backyard-camera.service
sudo -u backyard nano /etc/backyard-camera.json
```

Set `queue_dir` to `/var/lib/backyard-camera/queue`; retain `interval_seconds: 300`. Confirm the URL, publishable key, device email and password. Remove the transferred temporary config once the installed copy is checked: `rm /tmp/backyard-camera.json`.

If rerunning setup and user `backyard` already exists, skip `useradd`. Raspberry Pi OS normally provides `video` and `render`; if either is missing, investigate the camera/OS install rather than ignoring device permission failures.

## 4. First real upload

```sh
cd /var/lib/backyard-camera
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --once
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --status
```

Expect `Uploaded` and `pending: 0`. Open the website and confirm a REAL photograph is visible at the right UTC time. Only then enable the service:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now backyard-camera
sudo systemctl status backyard-camera --no-pager
sudo journalctl -u backyard-camera -n 40 --no-pager
```

Wait a little over five minutes and verify another image appears. Reboot once and verify the service starts and uploads again.

## 5. Offline test and placement

For a safe queue test while connected by SSH, stop the service, then capture offline explicitly (do not disable Wi-Fi and strand your SSH session):

```sh
sudo systemctl stop backyard-camera
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --once --offline
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --status
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --upload-only
sudo systemctl start backyard-camera
```

Expect queue count 1 before upload and 0 afterward. This tests the local recovery path; an actual network-outage test can be done later with physical access.

Frame only the scene you intend to publish. Start indoors looking through a clean window, reduce indoor reflections, and check autofocus before sealing any enclosure. An IP65 box is not a complete weatherproof installation: cable entries, condensation and heat still need physical inspection.

## Routine checks

```sh
sudo journalctl -u backyard-camera --since '1 hour ago' --no-pager
df -h /var/lib/backyard-camera
vcgencmd get_throttled
sudo -u backyard python3 /opt/backyard-camera/device/camera.py --config /etc/backyard-camera.json --status
```

`get_throttled=0x0` indicates no current/historical throttling flags since boot. Upload failures retain queued files; repeated capture errors mean inspect the camera and service permissions. Stop with `sudo systemctl stop backyard-camera` before manually capturing into the same queue.

References: [Camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html), [Camera hardware](https://www.raspberrypi.com/documentation/accessories/camera.html), [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
