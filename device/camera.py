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
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from daylight import Daylight

LOG = logging.getLogger("backyard")
MAX_IMAGE = 8 * 1024 * 1024
MIN_CAPTURE_TIME = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


class PermanentUploadError(ValueError):
    pass


def error_code(error):
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, PermanentUploadError):
        return str(error)
    return type(error).__name__


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
        self.db.execute("create table if not exists health (key text primary key, value text not null)")
        self.db.execute("create table if not exists quarantine (id text primary key, failed_at text not null, code text not null)")
        self.db.commit()

    def _health(self, key, value):
        self.db.execute("insert into health values (?,?) on conflict(key) do update set value=excluded.value", (key, value))

    def _error(self, operation, code, now):
        self._health("last_error", json.dumps({"at": now, "operation": operation, "code": code}))

    def error(self, operation, code):
        with self.db:
            self._error(operation, code, utc_now().isoformat())
            if operation == "upload":
                self._health("upload_attempt", "retrying")

    def add(self, data, captured_at, mock=False, trigger="scheduled", event_id=None, motion_score=None):
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9") or len(data) > MAX_IMAGE:
            raise ValueError("Capture must be a JPEG no larger than 8 MiB")
        identifier = str(uuid.uuid4())
        with self.db:
            self.db.execute("insert into captures values (?,?,?,?,?,?,?,?,?)", (identifier, captured_at, hashlib.sha256(data).hexdigest(), len(data), int(mock), data, trigger, event_id, motion_score))
            self._health("last_capture_at", captured_at)
        return identifier

    def first(self):
        row = self.db.execute("select * from captures where id not in (select id from quarantine) order by captured_at,id limit 1").fetchone()
        return dict(zip(("id", "captured_at", "sha256", "bytes", "mock", "jpeg", "trigger", "event_id", "motion_score"), row)) if row else None

    def size(self):
        return self.db.execute("select coalesce(sum(bytes),0) from captures").fetchone()[0]

    def count(self):
        return self.db.execute("select count(*) from captures where id not in (select id from quarantine)").fetchone()[0]

    def uploaded(self, identifier):
        with self.db:
            self.db.execute("delete from captures where id=?", (identifier,))
            self._health("last_upload_at", utc_now().isoformat())
            self._health("upload_attempt", "ok")

    def quarantine(self, identifier, code):
        now = utc_now().isoformat()
        with self.db:
            self.db.execute("insert into quarantine values (?,?,?)", (identifier, now, code))
            self._error("upload", code, now)
            self._health("upload_attempt", "quarantined")

    def status(self):
        health = dict(self.db.execute("select key,value from health"))
        pending = self.count()
        quarantined = self.db.execute("select count(*) from quarantine").fetchone()[0]
        if health.get("upload_attempt") == "retrying":
            upload_status = "retrying"
        elif pending:
            upload_status = "pending"
        elif quarantined:
            upload_status = "quarantined"
        elif health.get("last_upload_at"):
            upload_status = "ok"
        else:
            upload_status = "idle"
        return {"pending": pending, "bytes": self.size(), "quarantined": quarantined,
                "last_capture_at": health.get("last_capture_at"),
                "last_upload_at": health.get("last_upload_at"),
                "upload_status": upload_status,
                "last_error": json.loads(health.get("last_error", "null"))}


def http_error_json(error):
    try:
        payload = json.loads(error.read(8192))
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
        jpeg = item["jpeg"]
        if (len(jpeg) != item["bytes"] or len(jpeg) > MAX_IMAGE or
                not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9") or
                hashlib.sha256(jpeg).hexdigest() != item["sha256"]):
            raise PermanentUploadError("invalid_queued_jpeg")
        try:
            captured_at = dt.datetime.fromisoformat(item["captured_at"].replace("Z", "+00:00"))
        except ValueError:
            raise PermanentUploadError("invalid_capture_timestamp") from None
        if captured_at.tzinfo is None or captured_at < MIN_CAPTURE_TIME:
            raise PermanentUploadError("invalid_capture_timestamp")
        self.login()
        path = f'{self.user_id}/{item["id"]}.jpg'
        # Immutable UUID path. A lost response is safe: verify existing bytes on conflict.
        try:
            self.request("/storage/v1/object/backyard-images/" + path, item["jpeg"], "POST", "image/jpeg")
        except urllib.error.HTTPError as error:
            duplicate = error.code == 409
            if error.code == 400:
                payload = http_error_json(error)
                duplicate = (payload.get("error") == "Duplicate" or
                             payload.get("code") in ("ResourceAlreadyExists", "KeyAlreadyExists"))
            if not duplicate:
                if error.code == 401:
                    self.expires = 0
                raise
            existing = self.request("/storage/v1/object/authenticated/backyard-images/" + path, content_type="image/jpeg")
            if hashlib.sha256(existing).hexdigest() != item["sha256"]:
                raise PermanentUploadError("object_hash_conflict") from error
        metadata = {k: item[k] for k in ("id", "captured_at", "sha256", "bytes")}
        metadata.update(device_id=self.user_id, object_path=path, is_mock=bool(item["mock"]))
        metadata.update(trigger=item.get("trigger", "scheduled"), event_id=item.get("event_id"), motion_score=item.get("motion_score"))
        # Ignore a duplicate row only after checking it exactly matches this capture.
        try:
            self.request("/rest/v1/captures", metadata, "POST", headers={"Prefer": "return=minimal"})
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.expires = 0
            if error.code == 400:
                payload = http_error_json(error)
                message = payload.get("message", "")
                if (payload.get("code") == "23514" and isinstance(message, str) and
                        any(f'"{constraint}"' in message for constraint in (
                            "capture_event_shape", "captures_trigger_check", "captures_motion_score_check",
                            "captures_sha256_check", "captures_bytes_check"))):
                    raise PermanentUploadError("invalid_capture_metadata") from error
            if error.code != 409:
                raise
            rows = self.request("/rest/v1/captures?id=eq." + item["id"] + "&select=*")
            if not rows:
                try:
                    verified = self.request("/rest/v1/rpc/verify_hidden_capture", {"expected": metadata}, "POST")
                except urllib.error.HTTPError as verify_error:
                    if verify_error.code == 404:
                        raise error from None
                    raise
                if verified is True:
                    return
                raise PermanentUploadError("metadata_conflict") from error
            if any(rows[0].get(k) != v for k, v in metadata.items() if k != "captured_at"):
                raise PermanentUploadError("metadata_conflict") from error
            if dt.datetime.fromisoformat(rows[0]["captured_at"].replace("Z", "+00:00")) != captured_at:
                raise PermanentUploadError("metadata_conflict") from error


def drain(queue, cloud, limit=100):
    quarantined = 0
    for _ in range(limit):
        item = queue.first()
        if item is None:
            break
        try:
            cloud.upload(item)
        except PermanentUploadError as error:
            code = error_code(error)
            queue.quarantine(item["id"], code)
            quarantined += 1
            LOG.error("Quarantined %s (%s); image retained locally", item["id"], code)
            continue
        except Exception as error:
            if isinstance(error, urllib.error.HTTPError) and error.code == 401:
                cloud.expires = 0
            code = error_code(error)
            queue.error("upload", code)
            LOG.warning("Upload deferred (%s); queue retained", code)
            raise
        queue.uploaded(item["id"])
        LOG.info("Uploaded %s; pending=%s", item["id"], queue.count())
    return quarantined


def record_capture_error(queue, code):
    try:
        queue.error("capture", code)
    except sqlite3.Error as error:
        LOG.warning("Could not save capture health status (%s)", error_code(error))


def has_capacity(queue, config):
    if (shutil.disk_usage(queue.root).free < config.get("min_free_bytes", 256 * 1024**2) + MAX_IMAGE or
            queue.size() + MAX_IMAGE > config.get("max_queue_bytes", 2 * 1024**3)):
        record_capture_error(queue, "queue_limit")
        LOG.warning("Queue/disk limit reached: preserving queued images and skipping new capture")
        return False
    return True


def capture(queue, config, mock):
    if not has_capacity(queue, config):
        return
    captured_at = utc_now().isoformat()
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


def capture_failed(queue, error):
    code = error_code(error)
    record_capture_error(queue, code)
    LOG.error("Capture failed (%s); continuing", code)


def configured_cloud(queue, config):
    try:
        return Cloud(config)
    except (ValueError, KeyError):
        queue.error("upload", "cloud_config")
        LOG.error("Cloud configuration is invalid; queue retained")
        raise ValueError("Invalid cloud configuration") from None


def upload_pending(queue, config, limit=100):
    try:
        quarantined = drain(queue, configured_cloud(queue, config), limit)
    except Exception:
        raise SystemExit(1) from None
    if quarantined:
        raise SystemExit(1)


def worker(config, stop):
    queue = Queue(config["queue_dir"])
    try:
        cloud = None
        delay = 5
        while not stop.is_set():
            try:
                if cloud is None:
                    cloud = configured_cloud(queue, config)
                drain(queue, cloud)
                delay = 5
            except Exception:
                delay = min(delay * 2, 300)
            stop.wait(delay + random.uniform(0, 2))
    finally:
        queue.db.close()


def run_scheduled(queue, config, mock, stop, interval, daylight):
    deadline = time.monotonic()
    while not stop.is_set():
        if mock or daylight.allows(utc_now()):
            try:
                capture(queue, config, mock)
            except Exception as error:
                capture_failed(queue, error)
        deadline += interval
        if deadline < time.monotonic():
            deadline = time.monotonic() + interval
        stop.wait(max(0, deadline - time.monotonic()))


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
    if args.status:
        queue = Queue(config["queue_dir"])
        try:
            print(json.dumps(queue.status()))
        finally:
            queue.db.close()
        return
    root = Path(config["queue_dir"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    interval = float(config.get("interval_seconds", 300))
    if interval < 1:
        raise ValueError("interval_seconds must be at least 1")
    with (root / "camera.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue = Queue(root)
        try:
            if args.upload_only:
                upload_pending(queue, config, limit=1000000)
                return
            if args.once:
                try:
                    capture(queue, config, args.mock)
                except Exception as error:
                    capture_failed(queue, error)
                    raise SystemExit(1) from None
                if not args.offline:
                    upload_pending(queue, config)
                return
            daylight = None if args.mock else Daylight(config)
            stop = threading.Event()
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: stop.set())
            uploader = None
            if not args.offline:
                uploader = threading.Thread(target=worker, args=(config, stop), daemon=True)
                uploader.start()
            try:
                run_scheduled(queue, config, args.mock, stop, interval, daylight)
            finally:
                stop.set()
                if uploader:
                    uploader.join(timeout=35)
        finally:
            queue.db.close()


if __name__ == "__main__":
    main()
