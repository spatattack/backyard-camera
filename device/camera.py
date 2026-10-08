#!/usr/bin/env python3
"""Durable, bounded offline camera queue. Python standard library only."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

LOG = logging.getLogger("backyard")
MAX_IMAGE = 8 * 1024 * 1024


class Queue:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "queue.sqlite3", timeout=30)
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("pragma synchronous=FULL")
        self.db.execute("create table if not exists captures (id text primary key, captured_at text not null, sha256 text not null, bytes integer not null, mock integer not null, jpeg blob not null)")
        columns = {r[1] for r in self.db.execute("pragma table_info(captures)")}
        for name, definition in (("trigger", "text not null default 'scheduled'"), ("event_id", "text"), ("motion_score", "real")):
            if name not in columns:
                self.db.execute(f'alter table captures add column "{name}" {definition}')
        self.db.commit()

    def add(self, data, captured_at, mock=False, trigger="scheduled", event_id=None, motion_score=None):
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9") or len(data) > MAX_IMAGE:
            raise ValueError("Capture must be a JPEG no larger than 8 MiB")
        identifier = str(uuid.uuid4())
        with self.db:
            self.db.execute("insert into captures values (?,?,?,?,?,?,?,?,?)", (identifier, captured_at, hashlib.sha256(data).hexdigest(), len(data), int(mock), data, trigger, event_id, motion_score))
        return identifier

    def first(self):
        row = self.db.execute("select * from captures order by captured_at,id limit 1").fetchone()
        return dict(zip(("id", "captured_at", "sha256", "bytes", "mock", "jpeg", "trigger", "event_id", "motion_score"), row)) if row else None

    def size(self):
        return self.db.execute("select coalesce(sum(bytes),0) from captures").fetchone()[0]

    def count(self):
        return self.db.execute("select count(*) from captures").fetchone()[0]

    def remove(self, identifier):
        with self.db:
            self.db.execute("delete from captures where id=?", (identifier,))


class Cloud:
    def __init__(self, config):
        self.config = config
        self.url = config["supabase_url"].rstrip("/")
        if urllib.parse.urlparse(self.url).scheme != "https":
            raise ValueError("Supabase URL must use HTTPS")
        self.token = None
        self.user_id = None
        self.expires = 0

    def request(self, path, data=None, method="GET", content_type="application/json", headers=None):
        h = {"apikey": self.config["publishable_key"], "Content-Type": content_type}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        h.update(headers or {})
        body = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, data=body, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw and content_type == "application/json" else raw

    def login(self):
        if time.time() < self.expires:
            return
        self.token = None
        result = self.request("/auth/v1/token?grant_type=password", {"email": self.config["email"], "password": self.config["password"]}, "POST")
        self.token, self.user_id = result["access_token"], result["user"]["id"]
        self.expires = time.time() + result.get("expires_in", 3600) - 60

    def upload(self, item):
        self.login()
        path = f'{self.user_id}/{item["id"]}.jpg'
        # Immutable UUID path. A lost response is safe: verify existing bytes on conflict.
        try:
            self.request("/storage/v1/object/backyard-images/" + path, item["jpeg"], "POST", "image/jpeg")
        except urllib.error.HTTPError as error:
            if error.code not in (400, 409):
                if error.code == 401:
                    self.expires = 0
                raise
            existing = self.request("/storage/v1/object/authenticated/backyard-images/" + path, content_type="image/jpeg")
            if hashlib.sha256(existing).hexdigest() != item["sha256"]:
                raise ValueError("Existing object differs; retaining queued capture") from error
        metadata = {k: item[k] for k in ("id", "captured_at", "sha256", "bytes")}
        metadata.update(device_id=self.user_id, object_path=path, is_mock=bool(item["mock"]))
        metadata.update(trigger=item.get("trigger", "scheduled"), event_id=item.get("event_id"), motion_score=item.get("motion_score"))
        # Ignore a duplicate row only after checking it exactly matches this capture.
        try:
            self.request("/rest/v1/captures", metadata, "POST", headers={"Prefer": "return=minimal"})
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.expires = 0
            if error.code != 409:
                raise
            rows = self.request("/rest/v1/captures?id=eq." + item["id"] + "&select=*")
            if not rows or any(rows[0].get(k) != v for k, v in metadata.items() if k != "captured_at"):
                raise ValueError("Existing metadata differs; retaining queued capture") from error
            if dt.datetime.fromisoformat(rows[0]["captured_at"].replace("Z", "+00:00")) != dt.datetime.fromisoformat(item["captured_at"]):
                raise ValueError("Existing capture time differs") from error


def drain(queue, cloud, limit=100):
    for _ in range(limit):
        item = queue.first()
        if item is None:
            return
        cloud.upload(item)
        queue.remove(item["id"])
        LOG.info("Uploaded %s; pending=%s", item["id"], queue.count())


def capture(queue, config, mock):
    if queue.size() + MAX_IMAGE > config.get("max_queue_bytes", 2 * 1024**3) or shutil.disk_usage(queue.root).free < config.get("min_free_bytes", 256 * 1024**2) + MAX_IMAGE:
        LOG.warning("Queue/disk limit reached: preserving queued images and skipping new capture")
        return
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if mock:
        data = Path(mock).read_bytes()
    else:
        temp = queue.root / "capture.part.jpg"
        try:
            subprocess.run(["rpicam-still", "--nopreview", "--timeout", "2000", "--autofocus-mode", "auto", "--width", "2304", "--height", "1296", "--quality", "85", "--output", str(temp)], check=True, timeout=45)
            data = temp.read_bytes()
        finally:
            temp.unlink(missing_ok=True)
    identifier = queue.add(data, captured_at, bool(mock))
    LOG.info("Queued %s; pending=%s", identifier, queue.count())


def worker(config, stop):
    queue = Queue(config["queue_dir"])
    cloud = Cloud(config)
    delay = 5
    while not stop.is_set():
        try:
            drain(queue, cloud)
            delay = 5
        except Exception as error:
            # Do not log auth responses, passwords, or bearer tokens.
            if isinstance(error, urllib.error.HTTPError) and error.code == 401:
                cloud.expires = 0
            LOG.warning("Upload deferred (%s); queue retained", type(error).__name__)
            delay = min(delay * 2, 300)
        stop.wait(delay + random.uniform(0, 2))
    queue.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mock", metavar="JPEG", help="Copy this JPEG instead of using the Pi camera")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Capture only; never connect to cloud")
    parser.add_argument("--upload-only", action="store_true", help="Drain pending captures and exit")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.offline and args.upload_only:
        parser.error("--offline cannot be combined with --upload-only")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    config = json.loads(Path(args.config).read_text())
    config["queue_dir"] = str(Path(config.get("queue_dir", "queue")).resolve())
    queue = Queue(config["queue_dir"])
    if args.status:
        print(json.dumps({"pending": queue.count(), "bytes": queue.size()}))
        return
    lock = (queue.root / "camera.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    interval = float(config.get("interval_seconds", 300))
    if interval < 1:
        raise ValueError("interval_seconds must be at least 1")
    if args.upload_only:
        drain(queue, Cloud(config), limit=1000000)
        return
    if args.once:
        capture(queue, config, args.mock)
        if not args.offline:
            drain(queue, Cloud(config))
        return
    stop = threading.Event()
    uploader = None
    if not args.offline:
        uploader = threading.Thread(target=worker, args=(config, stop), daemon=True)
        uploader.start()
    try:
        deadline = time.monotonic()
        while True:
            try:
                capture(queue, config, args.mock)
            except Exception as error:
                LOG.error("Capture failed (%s); retry at next interval", type(error).__name__)
            deadline += interval
            if deadline < time.monotonic():
                deadline = time.monotonic() + interval
            time.sleep(max(0, deadline - time.monotonic()))
    except KeyboardInterrupt:
        stop.set()
        if uploader:
            uploader.join(timeout=35)
    finally:
        queue.db.close()


if __name__ == "__main__":
    main()
