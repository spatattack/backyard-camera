#!/usr/bin/env python3
"""Motion + scheduled capture. Recorded video is offline unless --upload is explicit."""
import argparse
import datetime as dt
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import threading
import time

from camera import Queue, MAX_IMAGE, worker, drain, Cloud
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
        gray = request.make_array('lores')[:self.height, :self.width].copy()
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


def run(source, config, stop, mock=False):
    queue = Queue(config['queue_dir'])
    detector = Detector(config.get('motion', {}))
    planner = Planner(config.get('motion', {}), config.get('interval_seconds',300))
    planner.next_scheduled = detector.warmup
    count = 0
    try:
        while not stop.is_set():
            sample = source.read()
            if sample is None:
                break
            now, gray, frame = sample
            try:
                moving, score = detector.update(gray, now)
                metadata = planner.update(now, moving, score)
                if not metadata:
                    continue
                if queue.size()+MAX_IMAGE > config.get('max_queue_bytes',2*1024**3) or shutil.disk_usage(queue.root).free < config.get('min_free_bytes',256*1024**2)+MAX_IMAGE:
                    LOG.warning('Queue/disk limit reached; skipping capture')
                    continue
                # Replay uses ingestion time and is always labelled mock.
                captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
                identifier = queue.add(source.jpeg(frame), captured_at, mock, **metadata)
                count += 1
                LOG.info('Queued %s trigger=%s event=%s source_seconds=%.2f score=%.3f',identifier,metadata['trigger'],metadata['event_id'],now,score)
            finally:
                source.release(frame)
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
    source = VideoSource(args.video,fps) if args.video else PiSource(fps)
    upload = not args.offline and (not args.video or args.upload)
    uploader = None
    if upload and not args.video:
        uploader = threading.Thread(target=worker,args=(config,stop),daemon=True);uploader.start()
    try:
        count = run(source,config,stop,mock=bool(args.video))
        LOG.info('Capture session finished: %d images',count)
        if upload and args.video:
            queue = Queue(root)
            try: drain(queue,Cloud(config),limit=1000000)
            finally: queue.db.close()
    finally:
        stop.set()
        if uploader: uploader.join(timeout=35)


if __name__ == '__main__': main()
