"""Small grayscale motion detector and non-blocking capture planner."""
import uuid
import numpy as np


class Detector:
    def __init__(self, config):
        self.threshold = float(config.get('pixel_threshold', 25))
        self.fraction = float(config.get('changed_fraction', .02))
        self.frames = int(config.get('consecutive_frames', 3))
        self.warmup = float(config.get('warmup_seconds', 3))
        self.regions = config.get('ignore_regions', [])
        if not 0 < self.threshold <= 255 or not 0 < self.fraction <= 1 or self.frames < 1 or self.warmup < 0:
            raise ValueError('Invalid motion sensitivity')
        for box in self.regions:
            if len(box) != 4 or not 0 <= box[0] < box[2] <= 1 or not 0 <= box[1] < box[3] <= 1:
                raise ValueError('Ignore regions must be normalized [left,top,right,bottom] rectangles')
        self.previous = None
        self.started = None
        self.streak = 0
        self.mask = None

    def update(self, gray, now):
        gray = np.asarray(gray, dtype=np.float32)
        if gray.ndim != 2:
            raise ValueError('Expected grayscale frame')
        if self.previous is None:
            self.mask = np.ones(gray.shape, dtype=bool)
            h, w = gray.shape
            for x1, y1, x2, y2 in self.regions:
                self.mask[int(y1*h):int(y2*h), int(x1*w):int(x2*w)] = False
            if not self.mask.any():
                raise ValueError('Ignore regions cover the whole preview')
            self.previous, self.started = gray.copy(), now
            return False, 0.0
        if gray.shape != self.previous.shape:
            raise ValueError('Preview dimensions changed')
        delta = gray - self.previous
        # Subtract global brightness change to suppress exposure/cloud flicker.
        delta -= np.median(delta[self.mask])
        score = float(np.mean(np.abs(delta[self.mask]) >= self.threshold))
        self.previous = gray.copy()
        self.streak = self.streak + 1 if score >= self.fraction else 0
        return now - self.started >= self.warmup and self.streak >= self.frames, score


class Planner:
    def __init__(self, config, interval=300):
        self.interval = float(interval)
        self.cooldown = float(config.get('cooldown_seconds', 30))
        self.spacing = float(config.get('burst_spacing_seconds', 1))
        self.count = int(config.get('burst_count', 3))
        if self.interval < 1 or self.cooldown < 1 or self.spacing <= 0 or not 1 <= self.count <= 10:
            raise ValueError('Invalid capture timing')
        self.next_scheduled = 0
        self.next_motion = 0
        self.pending = []

    def update(self, now, moving, score):
        if moving and not self.pending and now >= self.next_motion:
            event = str(uuid.uuid4())
            self.pending = [(now+i*self.spacing, {'trigger':'motion','event_id':event,'motion_score':score}) for i in range(self.count)]
            self.next_motion = now + max(self.cooldown, self.count*self.spacing)
        # One capture per frame. Motion capture can also satisfy the baseline deadline.
        if self.pending and now >= self.pending[0][0]:
            _, metadata = self.pending.pop(0)
            if now >= self.next_scheduled:
                self.next_scheduled = now + self.interval
            return metadata
        if now >= self.next_scheduled:
            self.next_scheduled = now + self.interval
            return {'trigger':'scheduled','event_id':None,'motion_score':None}
        return None
