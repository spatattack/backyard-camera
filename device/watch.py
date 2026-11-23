#!/usr/bin/env python3
"""Motion + scheduled capture. Recorded video is offline unless --upload is explicit."""
import argparse
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time

from camera import Queue, capture_failed, has_capacity, upload_pending, utc_now, worker
from daylight import Daylight
from motion import Detector, Planner

LOG = logging.getLogger('backyard')


class PiSource:
    def __init__(self, fps):
        from picamera2 import Picamera2
        from libcamera import controls
        self.camera = Picamera2()
        config = self.camera.create_video_configuration(
            main={'size': (2304, 1296), 'format': 'RGB888'},
            lores={'size': (320, 180), 'format': 'YUV420'},
            buffer_count=3, controls={'FrameRate': fps, 'AfMode': controls.AfModeEnum.Continuous})
        self.camera.align_configuration(config)
        self.camera.configure(config)
        self.width, self.height = self.camera.camera_configuration()['lores']['size']
        self.camera.options["quality"] = 85
        self.camera.start()
        self.started = time.monotonic()

    def read(self):
        request = self.camera.capture_request()
        try:
            gray = request.make_array('lores')[:self.height, :self.width].copy()
        except Exception:
            self.release(request)
            raise
        return time.monotonic()-self.started, gray, request

    def jpeg(self, frame):
        result = io.BytesIO()
        frame.save('main', result, format='JPEG')
        return result.getvalue()

    def release(self, frame):
        frame.release()

    def close(self):
        self.camera.stop()
        self.camera.close()


class VideoSource:
    def __init__(self, path, fps):
        import cv2
        self.cv = cv2
        self.video = cv2.VideoCapture(str(path))
        self.rate = self.video.get(cv2.CAP_PROP_FPS)
        if not self.video.isOpened() or not 0 < self.rate < 1000:
            raise ValueError('Cannot decode video or determine frame rate')
        self.index, self.next_sample, self.step = 0, 0, 1/fps

    def read(self):
        while True:
            ok, frame = self.video.read()
            if not ok:
                return None
            now = self.index/self.rate
            self.index += 1
            if now + 1e-6 >= self.next_sample:
                self.next_sample = now + self.step
                gray = self.cv.cvtColor(self.cv.resize(frame, (320,180)), self.cv.COLOR_BGR2GRAY)
                return now, gray, frame

    def jpeg(self, frame):
        ok, encoded = self.cv.imencode('.jpg', frame, [self.cv.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError('JPEG encoding failed')
        return encoded.tobytes()

    def release(self, frame):
        pass

    def close(self):
        self.video.release()


def run(source, config, stop, mock=False, daylight=None):
    queue = Queue(config['queue_dir'])
    detector = Detector(config.get('motion', {}))
    planner = Planner(config.get('motion', {}), config.get('interval_seconds',300))
    new_session = True
    count = 0
    try:
        while not stop.is_set():
            if daylight is not None and not daylight.allows(utc_now()):
                if not new_session:
                    detector = Detector(config.get('motion', {}))
                    planner = Planner(config.get('motion', {}), config.get('interval_seconds',300))
                    new_session = True
                stop.wait(30)
                continue
            try:
                sample = source.read()
            except Exception as error:
                capture_failed(queue, error)
                stop.wait(1)
                continue
            if sample is None:
                break
            now, gray, frame = sample
            try:
                if new_session:
                    planner.next_scheduled = now + detector.warmup
                    new_session = False
                moving, score = detector.update(gray, now)
                metadata = planner.update(now, moving, score)
                if not metadata:
                    continue
                try:
                    if not has_capacity(queue, config):
                        continue
                    captured_at = utc_now()
                    if daylight is not None and not daylight.allows(captured_at):
                        continue
                    identifier = queue.add(source.jpeg(frame), captured_at.isoformat(), mock, **metadata)
                except Exception as error:
                    capture_failed(queue, error)
                    continue
                count += 1
                LOG.info('Queued %s trigger=%s event=%s source_seconds=%.2f score=%.3f',identifier,metadata['trigger'],metadata['event_id'],now,score)
            finally:
                try:
                    source.release(frame)
                except Exception as error:
                    capture_failed(queue, error)
    finally:
        source.close()
        queue.db.close()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--video', help='Replay a recorded video on Mac; never starts a camera')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--offline', action='store_true')
    group.add_argument('--upload', action='store_true', help='Explicitly upload labelled mock video captures')
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    config = json.loads(Path(args.config).read_text())
    config['queue_dir'] = str(Path(config.get('queue_dir','queue')).resolve())
    fps = float(config.get('motion',{}).get('preview_fps',5))
    if not 1 <= fps <= 10:
        parser.error('preview_fps must be between 1 and 10')
    root = Path(config['queue_dir']); root.mkdir(parents=True,exist_ok=True)
    lock = (root/'camera.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stop = threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_: stop.set())
    initial_queue = Queue(root)
    initial_queue.db.close()
    Detector(config.get("motion", {}))
    Planner(config.get("motion", {}), config.get("interval_seconds", 300))
    daylight = None if args.video else Daylight(config)
    source = VideoSource(args.video,fps) if args.video else PiSource(fps)
    upload = not args.offline and (not args.video or args.upload)
    uploader = None
    if upload and not args.video:
        uploader = threading.Thread(target=worker,args=(config,stop),daemon=True);uploader.start()
    try:
        count = run(source,config,stop,mock=bool(args.video),daylight=daylight)
        LOG.info('Capture session finished: %d images',count)
        if upload and args.video:
            queue = Queue(root)
            try: upload_pending(queue,config,limit=1000000)
            finally: queue.db.close()
    finally:
        stop.set()
        if uploader: uploader.join(timeout=35)


if __name__ == '__main__': main()
