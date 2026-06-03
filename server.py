#!/usr/bin/env python3
import cgi
import base64
import hashlib
import hmac
import html
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import shutil
import sqlite3
import string
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import oss2
os.environ.setdefault("MPLCONFIGDIR", "/tmp/sharephotos-matplotlib")
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import cv2
import numpy as np

try:
    import redis
except Exception:
    redis = None

try:
    import qrcode
    import qrcode.image.svg
except Exception:
    qrcode = None

try:
    import httpx
except Exception:
    httpx = None

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except Exception:
    hashes = None
    serialization = None
    ec = None

try:
    import fcntl
except Exception:
    fcntl = None

try:
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    Image = None

try:
    from insightface.app import FaceAnalysis
except Exception:
    FaceAnalysis = None


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
UPLOADS = DATA / "uploads"
THUMBS = DATA / "thumbs"
PREVIEWS = DATA / "previews"
AVATARS = DATA / "avatars"
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower() or "sqlite"
DB_FILE = DATA / "db.json"
SQLITE_DB_FILE = Path(os.environ.get("SQLITE_DB_FILE", str(DATA / "sharephotos.db")))
LOG_DIR = Path(os.environ.get("LOG_DIR", str(DATA / "logs")))
LEGACY_ALBUM_OWNER_USERNAME = os.environ.get("LEGACY_ALBUM_OWNER_USERNAME", "lpf").strip().lower() or "lpf"
APP_ASSOCIATED_DOMAIN = os.environ.get("APP_ASSOCIATED_DOMAIN", "picme.me").strip() or "picme.me"
IOS_BUNDLE_IDENTIFIER = os.environ.get("IOS_BUNDLE_IDENTIFIER", "com.sharephotos.app").strip() or "com.sharephotos.app"
APP_DOWNLOAD_URL = os.environ.get("APP_DOWNLOAD_URL", "").strip()
ANDROID_APP_PACKAGE = os.environ.get("ANDROID_APP_PACKAGE", "com.sharephotos.app").strip() or "com.sharephotos.app"
ANDROID_CERT_SHA256 = [
    item.strip().upper()
    for item in os.environ.get(
        "ANDROID_CERT_SHA256",
        "5C:59:9E:E6:03:D3:99:A1:7D:FD:D2:41:EA:5B:23:8E:70:4F:0F:3C:17:B6:FD:5E:A7:84:97:71:95:59:EF:F4",
    ).split(",")
    if item.strip()
]
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID", "").strip()
APNS_KEY_ID = os.environ.get("APNS_KEY_ID", "").strip()
APNS_AUTH_KEY_PATH = os.environ.get("APNS_AUTH_KEY_PATH", "").strip()
APNS_AUTH_KEY = os.environ.get("APNS_AUTH_KEY", "").strip()
APNS_TOPIC = os.environ.get("APNS_TOPIC", IOS_BUNDLE_IDENTIFIER).strip() or IOS_BUNDLE_IDENTIFIER
APNS_ENVIRONMENT = os.environ.get("APNS_ENVIRONMENT", "production").strip().lower() or "production"
SHARE_IMAGE_PATH = "/assets/share-logo.png?v=share-logo-1"


class DailyLogFileHandler(logging.Handler):
    def __init__(self, log_dir, prefix="sharephotos", backup_days=14):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.backup_days = int(backup_days)
        self.current_date = None
        self.stream = None

    def _path_for_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return today, self.log_dir / ("%s-%s.log" % (self.prefix, today))

    def _open_current(self):
        today, path = self._path_for_today()
        if self.stream and self.current_date == today:
            return
        if self.stream:
            self.stream.close()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_date = today
        self.stream = path.open("a", encoding="utf-8")

    def emit(self, record):
        try:
            self._open_current()
            self.stream.write(self.format(record) + "\n")
            self.stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        super().close()


class EventDefaultFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "event"):
            record.event = "-"
        return True


def setup_logger(name="sharephotos"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(process)d:%(module)s] %(event)s %(message)s")
    event_filter = EventDefaultFilter()
    logger.addFilter(event_filter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(event_filter)
    logger.addHandler(console)
    try:
        file_handler = DailyLogFileHandler(
            LOG_DIR,
            "sharephotos",
            int(os.environ.get("LOG_BACKUP_DAYS", "14") or "14"),
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(event_filter)
        logger.addHandler(file_handler)
    except Exception as error:
        logger.warning("file logging unavailable: %s", error, extra={"event": "logging.file_unavailable"})
    logger.propagate = False
    return logger


LOGGER = setup_logger()


class StoreLock:
    def __init__(self):
        self._thread_lock = threading.RLock()
        self._depth = 0
        self._file = None

    def __enter__(self):
        self._thread_lock.acquire()
        if self._depth == 0 and fcntl is not None:
            DATA.mkdir(parents=True, exist_ok=True)
            self._file = (DATA / "db.lock").open("a+")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        self._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self._depth -= 1
        if self._depth == 0 and self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
        self._thread_lock.release()


LOCK = StoreLock()
JOB_QUEUE = queue.Queue()
QUEUED_FACE_JOBS = set()
REDIS_HOST = os.environ.get("REDIS_HOST", "redis").strip() or "redis"
REDIS_PORT = os.environ.get("REDIS_PORT", "6379").strip() or "6379"
REDIS_DB = os.environ.get("REDIS_DB", "0").strip() or "0"
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
if not REDIS_URL and REDIS_PASSWORD:
    REDIS_URL = "redis://:%s@%s:%s/%s" % (REDIS_PASSWORD, REDIS_HOST, REDIS_PORT, REDIS_DB)
FACE_QUEUE_NAME = os.environ.get("FACE_QUEUE_NAME", "sharephotos:face:jobs").strip() or "sharephotos:face:jobs"
FACE_QUEUE_SET_NAME = os.environ.get("FACE_QUEUE_SET_NAME", "%s:queued" % FACE_QUEUE_NAME).strip() or "%s:queued" % FACE_QUEUE_NAME
FACE_JOB_PHOTO_ANALYZE = "photo_analyze"
FACE_JOB_AVATAR_ANALYZE = "avatar_analyze"
FACE_JOB_ALBUM_MATCH = "album_match"
FACE_WORKER_MODE = os.environ.get("FACE_WORKER_MODE", "inline").strip().lower()
WORKER_API_URL = os.environ.get("WORKER_API_URL", "").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "").strip()
REDIS_CLIENT = None
if REDIS_URL and redis is not None:
    try:
        REDIS_CLIENT = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        REDIS_CLIENT.ping()
    except Exception as error:
        LOGGER.warning("error=%s", error, extra={"event": "redis.connect_failed"})
        REDIS_CLIENT = None
THUMB_SPECS = {
    "tiny": (96, 72),
    "card": (420, 78),
    "cover": (900, 82),
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}
LIVE_IMAGE_EXTS = {".heic", ".heif"}
LIVE_VIDEO_EXTS = {".mov", ".mp4"}
OSS_ENDPOINT = os.environ.get("OSS_ENDPOINT", "").strip()
OSS_BUCKET = os.environ.get("OSS_BUCKET", "").strip()
OSS_ACCESS_KEY_ID = os.environ.get("OSS_ACCESS_KEY_ID", "").strip()
OSS_ACCESS_KEY_SECRET = os.environ.get("OSS_ACCESS_KEY_SECRET", "").strip()
OSS_PREFIX = os.environ.get("OSS_PREFIX", "").strip().strip("/")
OSS_AUTO_MIGRATE = os.environ.get("OSS_AUTO_MIGRATE", "").strip().lower() in {"1", "true", "yes", "on"}
try:
    OSS_UPLOAD_URL_EXPIRES = int(os.environ.get("OSS_UPLOAD_URL_EXPIRES", "900") or "900")
except (TypeError, ValueError):
    LOGGER.warning("Invalid OSS_UPLOAD_URL_EXPIRES, fallback to 900", extra={"event": "config.invalid"})
    OSS_UPLOAD_URL_EXPIRES = 900
try:
    OSS_SIGNED_URL_EXPIRES = int(os.environ.get("OSS_SIGNED_URL_EXPIRES", "3600") or "3600")
except (TypeError, ValueError):
    LOGGER.warning("Invalid OSS_SIGNED_URL_EXPIRES, fallback to 3600", extra={"event": "config.invalid"})
    OSS_SIGNED_URL_EXPIRES = 3600

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("video/quicktime", ".mov")

class OSSService:
    def __init__(self):
        self.endpoint = OSS_ENDPOINT
        self.bucket_name = OSS_BUCKET
        self.prefix = OSS_PREFIX
        self.expires = OSS_SIGNED_URL_EXPIRES
        self.bucket = None
        if OSS_ENDPOINT and OSS_BUCKET and OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET:
            self.bucket = oss2.Bucket(
                oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET),
                OSS_ENDPOINT,
                OSS_BUCKET,
            )

    def enabled(self):
        return self.bucket is not None

    def normalize_endpoint(self):
        return self.endpoint.replace("https://", "").replace("http://", "").strip("/")

    def public_url(self, object_key):
        if not object_key:
            return ""
        return "https://%s.%s/%s" % (self.bucket_name, self.normalize_endpoint(), object_key)

    def generateObjectKey(self, resource_type, album_id=None, photo_id=None, ext="", user_id=None):
        ext = ext.lower()
        if ext and not ext.startswith("."):
            ext = ".%s" % ext
        segments = []
        if self.prefix:
            segments.append(self.prefix)
        if resource_type == "original":
            segments.extend(["original", album_id, "%s%s" % (photo_id, ext)])
        elif resource_type == "preview":
            segments.extend(["preview", album_id, "%s.jpg" % photo_id])
        elif resource_type == "thumb":
            segments.extend(["thumb", album_id, "%s.webp" % photo_id])
        elif resource_type == "faces":
            segments.extend(["faces", user_id or album_id or "unknown", "%s.jpg" % photo_id])
        elif resource_type == "avatars":
            segments.extend(["avatars", "%s.jpg" % (user_id or photo_id)])
        else:
            segments.extend([resource_type, album_id or "common", "%s%s" % (photo_id or uuid.uuid4(), ext)])
        return "/".join(str(item).strip("/") for item in segments if str(item).strip("/"))

    def uploadFile(self, path, object_key, mime_type=None, resource_type=None):
        if not self.enabled() or not path or not Path(path).is_file():
            return {}
        path = Path(path)
        content_type = mime_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        headers = {"Content-Type": content_type}
        try:
            with path.open("rb") as fh:
                self.bucket.put_object(object_key, fh, headers=headers)
        except Exception as error:
            LOGGER.warning(
                "object_key=%s resource_type=%s error=%s",
                object_key,
                resource_type or "",
                error,
                extra={"event": "oss.upload_failed"},
            )
            return {}
        LOGGER.info(
            "object_key=%s resource_type=%s bytes=%d",
            object_key,
            resource_type or "",
            path.stat().st_size,
            extra={"event": "oss.upload"},
        )
        return {
            "object_key": object_key,
            "oss_url": self.public_url(object_key),
            "resource_type": resource_type or "",
            "mime_type": content_type,
            "file_size": path.stat().st_size,
        }

    def deleteFile(self, object_key):
        if self.enabled() and object_key:
            try:
                self.bucket.delete_object(object_key)
                LOGGER.info("object_key=%s", object_key, extra={"event": "oss.delete"})
            except Exception as error:
                LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.delete_failed"})

    def generateSignedUrl(self, object_key, expires=None):
        if not self.enabled() or not object_key:
            return ""
        try:
            signed = self.bucket.sign_url("GET", object_key, int(expires or self.expires), slash_safe=True)
            LOGGER.debug("object_key=%s expires=%s", object_key, int(expires or self.expires), extra={"event": "oss.sign"})
            return signed
        except Exception as error:
            LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.sign_failed"})
            return ""

    def generateUploadUrl(self, object_key, content_type=None, expires=None):
        if not self.enabled() or not object_key:
            return "", {}
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            signed = self.bucket.sign_url(
                "PUT",
                object_key,
                int(expires or OSS_UPLOAD_URL_EXPIRES),
                headers=headers or None,
                slash_safe=True,
            )
            LOGGER.info(
                "object_key=%s expires=%s",
                object_key,
                int(expires or OSS_UPLOAD_URL_EXPIRES),
                extra={"event": "oss.sign_upload"},
            )
            return signed, headers
        except Exception as error:
            LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.sign_upload_failed"})
            return "", {}

    def headObject(self, object_key):
        if not self.enabled() or not object_key:
            return {}
        try:
            result = self.bucket.head_object(object_key)
        except Exception as error:
            LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.head_failed"})
            return {}
        headers = getattr(result, "headers", {}) or {}
        size = int(headers.get("Content-Length") or headers.get("content-length") or 0)
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        etag = (headers.get("ETag") or headers.get("etag") or "").strip('"')
        return {
            "object_key": object_key,
            "oss_url": self.public_url(object_key),
            "resource_type": "",
            "mime_type": content_type,
            "file_size": size,
            "etag": etag,
        }

    def downloadFile(self, object_key, target):
        if not self.enabled() or not object_key:
            return None
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.bucket.get_object_to_file(object_key, str(target))
            LOGGER.info("object_key=%s target=%s", object_key, target.name, extra={"event": "oss.download"})
        except Exception as error:
            LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.download_failed"})
            raise
        return target


OSS_SERVICE = OSSService()


def oss_enabled():
    return OSS_SERVICE.enabled()


def oss_key(*parts):
    clean = [str(item).strip("/") for item in parts if str(item).strip("/")]
    if OSS_PREFIX:
        clean.insert(0, OSS_PREFIX)
    return "/".join(clean)


def oss_signed_url(key):
    return OSS_SERVICE.generateSignedUrl(key)


def oss_upload_path(path, key, content_type=None):
    return OSS_SERVICE.uploadFile(path, key, content_type)


def oss_direct_url(key):
    return OSS_SERVICE.public_url(key) if oss_enabled() and key else ""


def oss_signed_or_empty(key):
    return oss_signed_url(key) if oss_enabled() and key else ""


def safe_mime_type(filename, fallback="application/octet-stream"):
    return mimetypes.guess_type(filename or "")[0] or fallback


def resource_field(prefix, name):
    if not prefix:
        return name
    return "%s%s" % (prefix, name[0].upper() + name[1:])


def apply_resource_metadata(target, metadata, prefix=""):
    if not metadata:
        return
    target[resource_field(prefix, "objectKey")] = metadata.get("object_key", "")
    target[resource_field(prefix, "ossUrl")] = metadata.get("oss_url", "")
    target[resource_field(prefix, "resourceType")] = metadata.get("resource_type", "")
    target[resource_field(prefix, "mimeType")] = metadata.get("mime_type", "")
    target[resource_field(prefix, "fileSize")] = metadata.get("file_size", 0)
    target[resource_field(prefix, "etag")] = metadata.get("etag", "")
    if not prefix:
        target["object_key"] = metadata.get("object_key", "")
        target["oss_url"] = metadata.get("oss_url", "")
        target["resource_type"] = metadata.get("resource_type", "")
        target["mime_type"] = metadata.get("mime_type", "")
        target["file_size"] = metadata.get("file_size", 0)
        target["etag"] = metadata.get("etag", "")
    else:
        snake_prefix = re.sub(r"(?<!^)(?=[A-Z])", "_", prefix).lower()
        target["%s_object_key" % snake_prefix] = metadata.get("object_key", "")
        target["%s_oss_url" % snake_prefix] = metadata.get("oss_url", "")
        target["%s_resource_type" % snake_prefix] = metadata.get("resource_type", "")
        target["%s_mime_type" % snake_prefix] = metadata.get("mime_type", "")
        target["%s_file_size" % snake_prefix] = metadata.get("file_size", 0)
        target["%s_etag" % snake_prefix] = metadata.get("etag", "")


def apply_worker_resource_metadata(photo, resources):
    if not isinstance(resources, dict):
        return
    for prefix in ("preview", "thumb", "face"):
        metadata = resources.get(prefix)
        if not isinstance(metadata, dict):
            continue
        normalized = {
            "object_key": metadata.get("object_key") or metadata.get("objectKey") or "",
            "oss_url": metadata.get("oss_url") or metadata.get("ossUrl") or "",
            "resource_type": metadata.get("resource_type") or metadata.get("resourceType") or prefix,
            "mime_type": metadata.get("mime_type") or metadata.get("mimeType") or "",
            "file_size": metadata.get("file_size") or metadata.get("fileSize") or 0,
        }
        apply_resource_metadata(photo, normalized, prefix)


def photo_object_key(photo, *names):
    for name in names:
        value = photo.get(name)
        if value:
            return value
    return ""


def original_object_key(photo):
    return photo_object_key(photo, "object_key", "objectKey")


def live_video_object_key(photo):
    return photo_object_key(photo, "liveVideo_object_key", "live_video_object_key", "liveVideoObjectKey")


def preview_object_key(photo):
    return photo_object_key(photo, "preview_object_key", "previewObjectKey")


def thumb_object_key(photo):
    return photo_object_key(photo, "thumb_object_key", "thumbObjectKey")


def face_object_key(photo):
    return photo_object_key(photo, "face_object_key", "faceObjectKey")


def migrate_local_resources_to_oss(db):
    if not oss_enabled():
        return False
    changed = False
    for album in db.get("albums", []):
        album_id = album.get("id") or ""
        for photo in album.get("photos", []):
            photo_id = photo.get("id") or str(uuid.uuid4())
            if not photo.get("id"):
                photo["id"] = photo_id
                changed = True
            stored_name = photo.get("storedName") or ""
            source = UPLOADS / album_id / stored_name
            if source.is_file() and not original_object_key(photo):
                key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=source.suffix)
                metadata = OSS_SERVICE.uploadFile(source, key, mimetypes.guess_type(stored_name)[0], "original")
                if metadata:
                    apply_resource_metadata(photo, metadata)
                    changed = True
            video_name = photo.get("liveVideoStoredName") or ""
            video_source = UPLOADS / album_id / video_name
            if video_name and video_source.is_file() and not live_video_object_key(photo):
                key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=video_source.suffix)
                metadata = OSS_SERVICE.uploadFile(video_source, key, mimetypes.guess_type(video_name)[0], "original")
                if metadata:
                    apply_resource_metadata(photo, metadata, "liveVideo")
                    changed = True
            preview_source = PREVIEWS / album_id / ("%s.jpg" % stored_name)
            if preview_source.exists() and not preview_object_key(photo):
                key = OSS_SERVICE.generateObjectKey("preview", album_id=album_id, photo_id=photo_id)
                metadata = OSS_SERVICE.uploadFile(preview_source, key, "image/jpeg", "preview")
                if metadata:
                    apply_resource_metadata(photo, metadata, "preview")
                    changed = True
            thumb_source = THUMBS / album_id / "cover" / ("%s.jpg" % stored_name)
            if thumb_source.exists() and not thumb_object_key(photo):
                tmp = tempfile.NamedTemporaryFile(prefix="picme-migrate-thumb-", suffix=".webp", delete=False)
                tmp.close()
                target = Path(tmp.name)
                try:
                    image = cv2.imread(str(thumb_source), cv2.IMREAD_COLOR)
                    if image is not None:
                        ok, encoded = cv2.imencode(".webp", image, [int(cv2.IMWRITE_WEBP_QUALITY), 78])
                        if ok:
                            target.write_bytes(encoded.tobytes())
                            key = OSS_SERVICE.generateObjectKey("thumb", album_id=album_id, photo_id=photo_id)
                            metadata = OSS_SERVICE.uploadFile(target, key, "image/webp", "thumb")
                            if metadata:
                                apply_resource_metadata(photo, metadata, "thumb")
                                changed = True
                finally:
                    target.unlink(missing_ok=True)
            face_source = THUMBS / album_id / "face" / ("%s.jpg" % stored_name)
            if face_source.exists() and not face_object_key(photo):
                user_id = next((item for item in photo_folder_ids(photo) if item not in {"group-photo", "no-face", "pending"}), album_id)
                key = OSS_SERVICE.generateObjectKey("faces", album_id=album_id, photo_id=photo_id, user_id=user_id)
                metadata = OSS_SERVICE.uploadFile(face_source, key, "image/jpeg", "faces")
                if metadata:
                    apply_resource_metadata(photo, metadata, "face")
                    changed = True
    return changed


def sqlite_enabled():
    return DB_BACKEND in {"sqlite", "sqlite3"}


def sqlite_connect():
    SQLITE_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SQLITE_DB_FILE), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA cache_size = -4096")
    return conn


def sqlite_ensure_legacy_album_members(conn):
    album_rows = conn.execute("SELECT id, data_json FROM albums").fetchall()
    if not album_rows:
        return
    owner_row = conn.execute(
        "SELECT id, username FROM users WHERE lower(username) = ?",
        (LEGACY_ALBUM_OWNER_USERNAME,),
    ).fetchone()
    if not owner_row:
        user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if int(user_count or 0) == 0:
            return
        LOGGER.error(
            "username=%s albums=%d",
            LEGACY_ALBUM_OWNER_USERNAME,
            len(album_rows),
            extra={"event": "album.member_migrate_failed"},
        )
        raise RuntimeError("LEGACY_ALBUM_OWNER_USERNAME=%s 不存在，无法为旧相册建立 owner 权限" % LEGACY_ALBUM_OWNER_USERNAME)

    now = int(time.time())
    migrated = 0
    for album_row in album_rows:
        member_count = conn.execute(
            "SELECT COUNT(*) AS count FROM album_members WHERE album_id = ? AND status = 'active'",
            (album_row["id"],),
        ).fetchone()["count"]
        if int(member_count or 0) > 0:
            continue
        album_owner_row = None
        try:
            album_data = json.loads(album_row["data_json"] or "{}")
        except Exception:
            album_data = {}
        album_owner_id = album_data.get("ownerUserId") or album_data.get("createdByUserId")
        album_owner_username = normalize_username(album_data.get("ownerUsername") or album_data.get("createdByUsername") or "")
        if album_owner_id:
            album_owner_row = conn.execute("SELECT id, username FROM users WHERE id = ?", (album_owner_id,)).fetchone()
        if not album_owner_row and album_owner_username:
            album_owner_row = conn.execute(
                "SELECT id, username FROM users WHERE lower(username) = ?",
                (album_owner_username,),
            ).fetchone()
        target_owner = album_owner_row or owner_row
        conn.execute(
            """
            INSERT OR REPLACE INTO album_members(
                album_id, user_id, role, status, created_at, joined_at, approved_by, permissions_json
            )
            VALUES(?, ?, 'owner', 'active', ?, ?, ?, ?)
            """,
            (album_row["id"], target_owner["id"], now, now, target_owner["id"], permissions_json()),
        )
        migrated += 1
    if migrated:
        LOGGER.info(
            "fallback_owner_username=%s fallback_owner_id=%s albums=%d",
            owner_row["username"],
            owner_row["id"],
            migrated,
            extra={"event": "album.member_migrate"},
        )


def sqlite_init_store():
    with sqlite_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS store_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS albums (
                id TEXT PRIMARY KEY,
                sort_order INTEGER NOT NULL DEFAULT 0,
                name TEXT,
                created_at INTEGER,
                data_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS photos (
                album_id TEXT NOT NULL,
                id TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER,
                status TEXT,
                data_json TEXT NOT NULL,
                PRIMARY KEY (album_id, id),
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_photos_album_created
                ON photos(album_id, created_at);

            CREATE TABLE IF NOT EXISTS folders (
                album_id TEXT NOT NULL,
                id TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                name TEXT,
                data_json TEXT NOT NULL,
                PRIMARY KEY (album_id, id),
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS contributors (
                album_id TEXT NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (album_id, name),
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                nickname TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                avatar_url TEXT,
                avatar_object_key TEXT,
                has_face_profile INTEGER NOT NULL DEFAULT 0,
                data_json TEXT NOT NULL,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS auth_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                device_id TEXT,
                device_name TEXT,
                user_agent TEXT,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                revoked_reason TEXT,
                data_json TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                ON auth_sessions(user_id, revoked_at, expires_at);

            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                replaced_by_token_hash TEXT,
                FOREIGN KEY (session_id) REFERENCES auth_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_session
                ON refresh_tokens(session_id, revoked_at, expires_at);

            CREATE TABLE IF NOT EXISTS album_members (
                album_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL,
                joined_at INTEGER,
                approved_by TEXT,
                permissions_json TEXT,
                PRIMARY KEY (album_id, user_id),
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_album_members_user
                ON album_members(user_id, status);

            CREATE TABLE IF NOT EXISTS album_invites (
                id TEXT PRIMARY KEY,
                album_id TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                token_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_by TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER,
                permissions_json TEXT,
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_album_invites_album
                ON album_invites(album_id, status);

            CREATE TABLE IF NOT EXISTS album_join_requests (
                id TEXT PRIMARY KEY,
                album_id TEXT NOT NULL,
                invite_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                reviewed_by TEXT,
                reviewed_at INTEGER,
                FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
                FOREIGN KEY (invite_id) REFERENCES album_invites(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_join_requests_album
                ON album_join_requests(album_id, status, created_at);

            CREATE INDEX IF NOT EXISTS idx_join_requests_user
                ON album_join_requests(user_id, status, created_at);

            CREATE TABLE IF NOT EXISTS album_activities (
                id TEXT PRIMARY KEY,
                album_id TEXT NOT NULL,
                type TEXT NOT NULL,
                actor_user_id TEXT,
                actor_name TEXT,
                target_type TEXT,
                target_id TEXT,
                message TEXT,
                created_at INTEGER NOT NULL,
                data_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_album_activities_album_created
                ON album_activities(album_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                album_id TEXT,
                photo_id TEXT,
                activity_id TEXT,
                actor_user_id TEXT,
                read_at INTEGER,
                created_at INTEGER NOT NULL,
                data_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created
                ON notifications(user_id, read_at, created_at DESC);

            CREATE TABLE IF NOT EXISTS apns_devices (
                device_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'production',
                device_id TEXT,
                device_name TEXT,
                last_seen_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                data_json TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_apns_devices_user
                ON apns_devices(user_id, last_seen_at DESC);
            """
        )
        auth_columns = {row["name"] for row in conn.execute("PRAGMA table_info(auth_tokens)").fetchall()}
        if "session_id" not in auth_columns:
            conn.execute("ALTER TABLE auth_tokens ADD COLUMN session_id TEXT")
        member_columns = {row["name"] for row in conn.execute("PRAGMA table_info(album_members)").fetchall()}
        if "permissions_json" not in member_columns:
            conn.execute("ALTER TABLE album_members ADD COLUMN permissions_json TEXT")
        invite_columns = {row["name"] for row in conn.execute("PRAGMA table_info(album_invites)").fetchall()}
        if "permissions_json" not in invite_columns:
            conn.execute("ALTER TABLE album_invites ADD COLUMN permissions_json TEXT")
        conn.execute(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES(?, ?)",
            ("schema_version", "5"),
        )
        sqlite_ensure_legacy_album_members(conn)


def sqlite_album_count():
    with sqlite_connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM albums").fetchone()
        return int(row["count"] if row else 0)


def sqlite_dump_db():
    with sqlite_connect() as conn:
        albums = []
        album_rows = conn.execute(
            "SELECT data_json FROM albums ORDER BY sort_order ASC, created_at DESC, id ASC"
        ).fetchall()
        for album_row in album_rows:
            album = json.loads(album_row["data_json"])
            album_id = album.get("id")
            folder_rows = conn.execute(
                "SELECT data_json FROM folders WHERE album_id = ? ORDER BY sort_order ASC, id ASC",
                (album_id,),
            ).fetchall()
            photo_rows = conn.execute(
                "SELECT data_json FROM photos WHERE album_id = ? ORDER BY sort_order ASC, created_at ASC, id ASC",
                (album_id,),
            ).fetchall()
            contributor_rows = conn.execute(
                "SELECT name FROM contributors WHERE album_id = ? ORDER BY sort_order ASC, name ASC",
                (album_id,),
            ).fetchall()
            album["folders"] = [json.loads(row["data_json"]) for row in folder_rows]
            album["photos"] = [json.loads(row["data_json"]) for row in photo_rows]
            album["contributors"] = [row["name"] for row in contributor_rows]
            albums.append(album)
        user_rows = conn.execute(
            """
            SELECT id, username, nickname, password_hash, avatar_url,
                   avatar_object_key, has_face_profile, created_at, data_json
            FROM users
            ORDER BY created_at ASC, username ASC
            """
        ).fetchall()
        users = []
        for row in user_rows:
            user = json.loads(row["data_json"])
            user.update({
                "id": row["id"],
                "username": row["username"],
                "nickname": row["nickname"],
                "passwordHash": row["password_hash"],
                "avatarUrl": row["avatar_url"] or "",
                "avatarObjectKey": row["avatar_object_key"] or "",
                "hasFaceProfile": bool(row["has_face_profile"]),
                "createdAt": row["created_at"] or user.get("createdAt") or 0,
            })
            users.append(user)
    return {"albums": albums, "users": users}


def sqlite_write_db(db):
    sqlite_init_store()
    albums = db.get("albums", [])
    with sqlite_connect() as conn:
        with conn:
            preserved_members = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT album_id, user_id, role, status, created_at, joined_at, approved_by, permissions_json
                    FROM album_members
                    """
                ).fetchall()
            ]
            preserved_invites = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, album_id, code, token_hash, status, created_by, created_at, revoked_at, permissions_json
                    FROM album_invites
                    """
                ).fetchall()
            ]
            preserved_join_requests = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, album_id, invite_id, user_id, status, created_at, reviewed_by, reviewed_at
                    FROM album_join_requests
                    """
                ).fetchall()
            ]
            conn.execute("DELETE FROM contributors")
            conn.execute("DELETE FROM folders")
            conn.execute("DELETE FROM photos")
            conn.execute("DELETE FROM albums")
            for album_index, album in enumerate(albums):
                album_id = album.get("id") or uuid.uuid4().hex[:10]
                album["id"] = album_id
                conn.execute(
                    """
                    INSERT INTO albums(id, sort_order, name, created_at, data_json)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        album_id,
                        album_index,
                        album.get("name"),
                        int(album.get("createdAt") or 0),
                        json.dumps(album, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                for folder_index, folder in enumerate(album.get("folders", [])):
                    folder_id = str(folder.get("id") or uuid.uuid4())
                    folder["id"] = folder_id
                    conn.execute(
                        """
                        INSERT INTO folders(album_id, id, sort_order, name, data_json)
                        VALUES(?, ?, ?, ?, ?)
                        """,
                        (
                            album_id,
                            folder_id,
                            folder_index,
                            folder.get("name"),
                            json.dumps(folder, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                for photo_index, photo in enumerate(album.get("photos", [])):
                    photo_id = str(photo.get("id") or uuid.uuid4())
                    photo["id"] = photo_id
                    conn.execute(
                        """
                        INSERT INTO photos(album_id, id, sort_order, created_at, status, data_json)
                        VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            album_id,
                            photo_id,
                            photo_index,
                            int(photo.get("createdAt") or 0),
                            photo.get("status"),
                            json.dumps(photo, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                for contributor_index, contributor in enumerate(album.get("contributors", [])):
                    name = str(contributor).strip()
                    if not name:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO contributors(album_id, name, sort_order)
                        VALUES(?, ?, ?)
                        """,
                        (album_id, name, contributor_index),
                    )
            for user in db.get("users", []):
                user_id = str(user.get("id") or uuid.uuid4())
                user["id"] = user_id
                username = normalize_username(user.get("username") or "")
                if not username:
                    continue
                user["username"] = username
                user_row = (
                    user_id,
                    username,
                    user.get("nickname") or username,
                    user.get("passwordHash") or user.get("password_hash") or "",
                    user.get("avatarUrl") or user.get("avatar_url") or "",
                    user.get("avatarObjectKey") or user.get("avatar_object_key") or "",
                    1 if user.get("hasFaceProfile") else 0,
                    json.dumps(user, ensure_ascii=False, separators=(",", ":")),
                    int(user.get("createdAt") or 0),
                )
                updated = conn.execute(
                    """
                    UPDATE users
                    SET username = ?,
                        nickname = ?,
                        password_hash = ?,
                        avatar_url = ?,
                        avatar_object_key = ?,
                        has_face_profile = ?,
                        data_json = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    (
                        user_row[1],
                        user_row[2],
                        user_row[3],
                        user_row[4],
                        user_row[5],
                        user_row[6],
                        user_row[7],
                        user_row[8],
                        user_row[0],
                    ),
                )
                if updated.rowcount == 0:
                    conn.execute(
                        """
                        INSERT INTO users(
                            id, username, nickname, password_hash, avatar_url,
                            avatar_object_key, has_face_profile, data_json, created_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        user_row,
                    )
            current_album_ids = {
                row["id"] for row in conn.execute("SELECT id FROM albums").fetchall()
            }
            current_user_ids = {
                row["id"] for row in conn.execute("SELECT id FROM users").fetchall()
            }
            restored_invite_ids = set()
            for member in preserved_members:
                if member["album_id"] not in current_album_ids or member["user_id"] not in current_user_ids:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO album_members(
                        album_id, user_id, role, status, created_at, joined_at, approved_by, permissions_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        member["album_id"],
                        member["user_id"],
                        member["role"],
                        member["status"],
                        int(member["created_at"] or 0),
                        member["joined_at"],
                        member["approved_by"] if member["approved_by"] in current_user_ids else None,
                        member.get("permissions_json") or permissions_json(),
                    ),
                )
            for invite in preserved_invites:
                if invite["album_id"] not in current_album_ids or invite["created_by"] not in current_user_ids:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO album_invites(
                        id, album_id, code, token_hash, status, created_by, created_at, revoked_at, permissions_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invite["id"],
                        invite["album_id"],
                        invite["code"],
                        invite["token_hash"],
                        invite["status"],
                        invite["created_by"],
                        int(invite["created_at"] or 0),
                        invite["revoked_at"],
                        invite.get("permissions_json") or permissions_json(),
                    ),
                )
                restored_invite_ids.add(invite["id"])
            for join_request in preserved_join_requests:
                if (
                    join_request["album_id"] not in current_album_ids
                    or join_request["invite_id"] not in restored_invite_ids
                    or join_request["user_id"] not in current_user_ids
                ):
                    continue
                reviewed_by = join_request["reviewed_by"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO album_join_requests(
                        id, album_id, invite_id, user_id, status, created_at, reviewed_by, reviewed_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        join_request["id"],
                        join_request["album_id"],
                        join_request["invite_id"],
                        join_request["user_id"],
                        join_request["status"],
                        int(join_request["created_at"] or 0),
                        reviewed_by if reviewed_by in current_user_ids else None,
                        join_request["reviewed_at"],
                    ),
                )
            sqlite_ensure_legacy_album_members(conn)


def json_write_db(db):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DB_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=2)
    tmp.replace(DB_FILE)


def migrate_json_to_sqlite_if_needed():
    sqlite_init_store()
    if sqlite_album_count() > 0:
        return
    if DB_FILE.exists():
        with DB_FILE.open("r", encoding="utf-8") as fh:
            db = json.load(fh)
        sqlite_write_db(db)
        LOGGER.info(
            "source=%s target=%s albums=%d",
            DB_FILE,
            SQLITE_DB_FILE,
            len(db.get("albums", [])),
            extra={"event": "db.sqlite_migrate"},
        )
        return
    sqlite_write_db({"albums": []})


def ensure_store():
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    THUMBS.mkdir(exist_ok=True)
    PREVIEWS.mkdir(exist_ok=True)
    if sqlite_enabled():
        migrate_json_to_sqlite_if_needed()
    elif not DB_FILE.exists():
        json_write_db({"albums": [], "users": [], "authTokens": []})


def load_db():
    ensure_store()
    db = sqlite_dump_db() if sqlite_enabled() else json_load_db()
    db.setdefault("albums", [])
    db.setdefault("users", [])
    db.setdefault("albumActivities", [])
    db.setdefault("notifications", [])
    if not sqlite_enabled():
        db.setdefault("authTokens", [])
    if OSS_AUTO_MIGRATE and migrate_local_resources_to_oss(db):
        write_db(db)
    if sync_all_folder_covers(db):
        write_db(db)
    return db


def json_load_db():
    with DB_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_db(db):
    if sqlite_enabled():
        sqlite_write_db(db)
    else:
        json_write_db(db)


def save_db(db):
    for album in db.get("albums", []):
        ensure_album_permissions(album)
    sync_all_folder_covers(db)
    write_db(db)
    LOGGER.info("albums=%d", len(db.get("albums", [])), extra={"event": "db.write"})


def elapsed_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")
PASSWORD_RE = re.compile(r"^[\x21-\x7E]{6,20}$")
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20
ACCESS_TOKEN_TTL_SECONDS = int(os.environ.get("ACCESS_TOKEN_TTL_SECONDS", str(60 * 30)))
REFRESH_TOKEN_TTL_SECONDS = int(os.environ.get("REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 90)))
AUTH_TOKEN_TTL_SECONDS = int(os.environ.get("AUTH_TOKEN_TTL_SECONDS", str(ACCESS_TOKEN_TTL_SECONDS)))


def normalize_username(value):
    return str(value or "").strip().lower()


def validate_username(username):
    return bool(USERNAME_RE.match(username or ""))


def validate_password_format(password):
    return bool(PASSWORD_RE.match(password or ""))


def hash_password(password, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120000)
    return "pbkdf2_sha256$120000$%s$%s" % (salt, digest.hex())


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = str(stored or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        next_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(next_digest, digest)
    except Exception:
        return False


def hash_auth_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user, origin=""):
    if not user:
        return None
    avatar_object_key = user.get("avatarObjectKey") or user.get("avatar_object_key") or ""
    avatar_url = (oss_signed_or_empty(avatar_object_key) if avatar_object_key else "") or user.get("avatarUrl") or user.get("avatar_url") or ""
    if avatar_url and origin and not re.match(r"^https?://", avatar_url):
        avatar_url = urljoin(origin, avatar_url)
    return {
        "id": user.get("id", ""),
        "username": user.get("username", ""),
        "nickname": user.get("nickname", ""),
        "avatarUrl": avatar_url,
        "hasFaceProfile": bool(user.get("hasFaceProfile")),
        "faceProfileStatus": user.get("faceProfileStatus") or ("ready" if user.get("hasFaceProfile") else "missing"),
    }


def find_user_by_username(db, username):
    username = normalize_username(username)
    return next((user for user in db.get("users", []) if normalize_username(user.get("username")) == username), None)


def find_user_by_id(db, user_id):
    return next((user for user in db.get("users", []) if user.get("id") == user_id), None)


def upsert_user(db, user):
    users = db.setdefault("users", [])
    for index, current in enumerate(users):
        if current.get("id") == user.get("id"):
            users[index] = user
            return
    users.append(user)


def active_album_member_row(album_id, user_id):
    if not album_id or not user_id:
        return None
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            return conn.execute(
                """
                SELECT album_id, user_id, role, status, created_at, joined_at, approved_by, permissions_json
                FROM album_members
                WHERE album_id = ? AND user_id = ? AND status = 'active'
                """,
                (album_id, user_id),
            ).fetchone()
    return None


def album_member_role(album_id, user_id):
    row = active_album_member_row(album_id, user_id)
    return row["role"] if row else ""


def user_album_ids(user_id):
    if not user_id:
        return set()
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            rows = conn.execute(
                "SELECT album_id FROM album_members WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchall()
            return {row["album_id"] for row in rows}
    return set()


def album_member_user_ids(album_id):
    if not album_id or not sqlite_enabled():
        return []
    sqlite_init_store()
    with sqlite_connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM album_members WHERE album_id = ? AND status = 'active'",
            (album_id,),
        ).fetchall()
        return [row["user_id"] for row in rows]


def album_admin_user_ids(album_id):
    if not album_id or not sqlite_enabled():
        return []
    sqlite_init_store()
    with sqlite_connect() as conn:
        rows = conn.execute(
            """
            SELECT user_id FROM album_members
            WHERE album_id = ? AND status = 'active' AND role IN ('owner', 'admin')
            """,
            (album_id,),
        ).fetchall()
        return [row["user_id"] for row in rows]


def add_album_member(album_id, user_id, role="member", approved_by="", permissions=None):
    if not album_id or not user_id:
        return
    now = int(time.time())
    permission_payload = permissions_json() if role == "owner" else permissions_json(permissions)
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO album_members(
                        album_id, user_id, role, status, created_at, joined_at, approved_by, permissions_json
                    )
                    VALUES(?, ?, ?, 'active', ?, ?, ?, ?)
                    ON CONFLICT(album_id, user_id) DO UPDATE SET
                        role = excluded.role,
                        status = 'active',
                        joined_at = excluded.joined_at,
                        approved_by = excluded.approved_by,
                        permissions_json = excluded.permissions_json
                    """,
                    (album_id, user_id, role, now, now, approved_by or user_id, permission_payload),
                )


def is_album_owner(album, user_id):
    if not album or not user_id:
        return False
    if album.get("ownerUserId") == user_id or album.get("createdByUserId") == user_id:
        return True
    return album_member_role(album.get("id"), user_id) == "owner"


def effective_album_permissions(album, user):
    if not album or not user:
        return {key: False for key in ALBUM_PERMISSION_KEYS}
    if is_album_owner(album, user.get("id")):
        return normalize_album_permissions()
    album_permissions = ensure_album_permissions(album)
    row = active_album_member_row(album.get("id"), user.get("id"))
    if not row:
        return {key: False for key in ALBUM_PERMISSION_KEYS}
    member_permissions = member_public_permissions(row)
    return {key: bool(album_permissions.get(key)) and bool(member_permissions.get(key)) for key in ALBUM_PERMISSION_KEYS}


def album_member_can(album, user, permission):
    return bool(effective_album_permissions(album, user).get(permission))


def user_can_delete_photo(album, user, photo):
    if not album or not user or not photo:
        return False
    if is_album_owner(album, user.get("id")):
        return True
    if album_member_can(album, user, "delete"):
        return True
    if photo.get("uploaderUserId") == user.get("id"):
        return True
    return bool(photo.get("uploader") and photo.get("uploader") == actor_display_name(user, ""))


def update_album_member_permissions(album_id, user_id, permissions):
    if not album_id or not user_id or not sqlite_enabled():
        return False
    sqlite_init_store()
    with sqlite_connect() as conn:
        with conn:
            updated = conn.execute(
                """
                UPDATE album_members
                SET permissions_json = ?
                WHERE album_id = ? AND user_id = ? AND status = 'active' AND role != 'owner'
                """,
                (permissions_json(permissions), album_id, user_id),
            )
            return updated.rowcount > 0


def remove_album_member(album_id, user_id):
    if not album_id or not user_id or not sqlite_enabled():
        return False
    sqlite_init_store()
    now = int(time.time())
    with sqlite_connect() as conn:
        with conn:
            updated = conn.execute(
                """
                UPDATE album_members
                SET status = 'removed'
                WHERE album_id = ? AND user_id = ? AND status = 'active' AND role != 'owner'
                """,
                (album_id, user_id),
            )
            if updated.rowcount > 0:
                conn.execute(
                    """
                    UPDATE album_join_requests
                    SET status = 'removed', reviewed_at = COALESCE(reviewed_at, ?)
                    WHERE album_id = ? AND user_id = ? AND status = 'approved'
                    """,
                    (now, album_id, user_id),
                )
            return updated.rowcount > 0


def actor_display_name(user, fallback="系统"):
    if not user:
        return fallback
    return (user.get("nickname") or user.get("username") or fallback).strip()[:80]


def album_display_name(album, fallback="共享相册"):
    return ((album or {}).get("name") or fallback).strip()[:120]


def photo_display_name(photo, fallback="照片"):
    return ((photo or {}).get("originalName") or (photo or {}).get("storedName") or fallback).strip()[:160]


def public_album_activity(activity):
    if isinstance(activity, sqlite3.Row):
        data = json.loads(activity["data_json"] or "{}")
        data.update({
            "id": activity["id"],
            "albumId": activity["album_id"],
            "type": activity["type"],
            "actorUserId": activity["actor_user_id"] or "",
            "actorName": activity["actor_name"] or "",
            "targetType": activity["target_type"] or "",
            "targetId": activity["target_id"] or "",
            "message": activity["message"] or "",
            "createdAt": activity["created_at"],
        })
        if not data.get("title"):
            data["title"] = {
                "photo.upload": "上传照片",
                "photo.delete": "删除照片",
                "join_request.approved": "批准加入申请",
                "join_request.rejected": "拒绝加入申请",
            }.get(data.get("type"), "协作动态")
        return data
    data = dict(activity or {})
    if not data.get("title"):
        data["title"] = {
            "photo.upload": "上传照片",
            "photo.delete": "删除照片",
            "join_request.approved": "批准加入申请",
            "join_request.rejected": "拒绝加入申请",
        }.get(data.get("type"), "协作动态")
    return data


def record_album_activity(album_id, activity_type, actor=None, actor_name="", target_type="", target_id="", message="", data=None, db=None):
    if not album_id or not activity_type:
        return None
    now = int(time.time())
    activity = {
        "id": uuid.uuid4().hex,
        "albumId": album_id,
        "type": activity_type,
        "actorUserId": (actor or {}).get("id", ""),
        "actorName": actor_display_name(actor, actor_name or "系统"),
        "targetType": target_type or "",
        "targetId": target_id or "",
        "message": message or "",
        "createdAt": now,
        "data": data or {},
    }
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO album_activities(
                        id, album_id, type, actor_user_id, actor_name,
                        target_type, target_id, message, created_at, data_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity["id"],
                        album_id,
                        activity_type,
                        activity["actorUserId"],
                        activity["actorName"],
                        activity["targetType"],
                        activity["targetId"],
                        activity["message"],
                        now,
                        json.dumps(activity, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
        LOGGER.info(
            "album_id=%s activity_id=%s type=%s target=%s/%s",
            album_id,
            activity["id"],
            activity_type,
            activity["targetType"],
            activity["targetId"],
            extra={"event": "album.activity"},
        )
        return activity

    target_db = db
    if target_db is None:
        target_db = load_db()
    target_db.setdefault("albumActivities", []).append(activity)
    if db is None:
        write_db(target_db)
    LOGGER.info(
        "album_id=%s activity_id=%s type=%s target=%s/%s",
        album_id,
        activity["id"],
        activity_type,
        activity["targetType"],
        activity["targetId"],
        extra={"event": "album.activity"},
    )
    return activity


def list_album_activities(album_id, limit=50, before=0):
    limit = max(1, min(int(limit or 50), 200))
    if sqlite_enabled():
        sqlite_init_store()
        params = [album_id]
        where = "album_id = ?"
        if before:
            where += " AND created_at < ?"
            params.append(int(before))
        params.append(limit)
        with sqlite_connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM album_activities
                WHERE %s
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """ % where,
                params,
            ).fetchall()
        return [public_album_activity(row) for row in rows]
    db = load_db()
    items = [item for item in db.get("albumActivities", []) if item.get("albumId") == album_id]
    if before:
        items = [item for item in items if int(item.get("createdAt") or 0) < int(before)]
    items.sort(key=lambda item: (int(item.get("createdAt") or 0), item.get("id", "")), reverse=True)
    return items[:limit]


def public_notification(notification):
    if isinstance(notification, sqlite3.Row):
        data = json.loads(notification["data_json"] or "{}")
        data.update({
            "id": notification["id"],
            "userId": notification["user_id"],
            "type": notification["type"],
            "title": notification["title"],
            "body": notification["body"] or "",
            "albumId": notification["album_id"] or "",
            "photoId": notification["photo_id"] or "",
            "activityId": notification["activity_id"] or "",
            "actorUserId": notification["actor_user_id"] or "",
            "readAt": notification["read_at"] or 0,
            "createdAt": notification["created_at"],
        })
        data["isRead"] = bool(data.get("readAt"))
        return data
    data = dict(notification or {})
    data["isRead"] = bool(data.get("readAt"))
    return data


APNS_TOKEN_LOCK = threading.Lock()
APNS_TOKEN_CACHE = {"token": "", "issued_at": 0}


def apns_enabled():
    return bool(APNS_TEAM_ID and APNS_KEY_ID and (APNS_AUTH_KEY or APNS_AUTH_KEY_PATH) and httpx and serialization and ec)


def normalize_apns_device_token(token):
    return re.sub(r"[^0-9a-fA-F]", "", token or "").lower()


def apns_private_key_text():
    if APNS_AUTH_KEY:
        return APNS_AUTH_KEY.replace("\\n", "\n")
    if APNS_AUTH_KEY_PATH:
        try:
            return Path(APNS_AUTH_KEY_PATH).read_text(encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("path=%s error=%s", APNS_AUTH_KEY_PATH, exc, extra={"event": "apns.key_read_failed"})
    return ""


def base64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def apns_auth_token():
    now = int(time.time())
    with APNS_TOKEN_LOCK:
        if APNS_TOKEN_CACHE["token"] and now - int(APNS_TOKEN_CACHE["issued_at"] or 0) < 45 * 60:
            return APNS_TOKEN_CACHE["token"]
        key_text = apns_private_key_text()
        if not key_text:
            return ""
        private_key = serialization.load_pem_private_key(key_text.encode("utf-8"), password=None)
        header = {"alg": "ES256", "kid": APNS_KEY_ID}
        claims = {"iss": APNS_TEAM_ID, "iat": now}
        signing_input = ("%s.%s" % (
            base64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            base64url(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
        )).encode("ascii")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_ecdsa_der_signature(der_signature)
        raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        token = signing_input.decode("ascii") + "." + base64url(raw_signature)
        APNS_TOKEN_CACHE.update({"token": token, "issued_at": now})
        return token


def decode_ecdsa_der_signature(signature):
    if len(signature) < 8 or signature[0] != 0x30:
        raise ValueError("Invalid ECDSA signature")
    idx = 2
    if signature[idx] != 0x02:
        raise ValueError("Invalid ECDSA signature")
    r_len = signature[idx + 1]
    idx += 2
    r = int.from_bytes(signature[idx:idx + r_len], "big")
    idx += r_len
    if signature[idx] != 0x02:
        raise ValueError("Invalid ECDSA signature")
    s_len = signature[idx + 1]
    idx += 2
    s = int.from_bytes(signature[idx:idx + s_len], "big")
    return r, s


def register_apns_device(user_id, device_token, environment="production", device_id="", device_name=""):
    token = normalize_apns_device_token(device_token)
    if len(token) < 32:
        return False
    env = (environment or APNS_ENVIRONMENT or "production").lower()
    if env not in {"development", "sandbox", "production"}:
        env = "production"
    if env == "sandbox":
        env = "development"
    now = int(time.time())
    sqlite_init_store()
    with sqlite_connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO apns_devices(device_token, user_id, environment, device_id, device_name, last_seen_at, created_at, data_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_token) DO UPDATE SET
                    user_id = excluded.user_id,
                    environment = excluded.environment,
                    device_id = excluded.device_id,
                    device_name = excluded.device_name,
                    last_seen_at = excluded.last_seen_at,
                    data_json = excluded.data_json
                """,
                (
                    token,
                    user_id,
                    env,
                    device_id or "",
                    device_name or "",
                    now,
                    now,
                    json.dumps({"deviceId": device_id or "", "deviceName": device_name or ""}, ensure_ascii=False, separators=(",", ":")),
                ),
            )
    LOGGER.info("user_id=%s environment=%s", user_id, env, extra={"event": "apns.device_registered"})
    return True


def user_apns_devices(user_id):
    if not sqlite_enabled():
        return []
    sqlite_init_store()
    with sqlite_connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT device_token, environment FROM apns_devices WHERE user_id = ? ORDER BY last_seen_at DESC",
                (user_id,),
            ).fetchall()
        ]


def apns_payload_for_notification(notification):
    public = public_notification(notification)
    payload = {
        "aps": {
            "alert": {
                "title": public.get("title") or "PicMe",
                "body": public.get("body") or "",
            },
            "sound": "default",
        },
        "notificationId": public.get("id") or "",
        "type": public.get("type") or "",
        "albumId": public.get("albumId") or "",
        "photoId": public.get("photoId") or "",
        "activityId": public.get("activityId") or "",
    }
    data = public.get("data") if isinstance(public.get("data"), dict) else {}
    payload.update({
        "requestId": data.get("requestId") or "",
        "folderId": data.get("folderId") or "",
        "destination": notification_destination(public.get("type") or ""),
    })
    return payload


def notification_destination(notification_type):
    if notification_type == "album.join_request":
        return "join_requests"
    if notification_type in {"face.my_photos_matched", "album.join_approved"}:
        return "my_photos"
    return "messages"


def dispatch_push_notification(notification):
    if not sqlite_enabled():
        return
    devices = user_apns_devices(notification.get("userId") or notification.get("user_id"))
    if not devices:
        return
    thread = threading.Thread(target=send_push_notification_to_devices, args=(notification, devices), daemon=True)
    thread.start()


def send_push_notification_to_devices(notification, devices):
    if not apns_enabled():
        LOGGER.info("devices=%d reason=apns_not_configured", len(devices), extra={"event": "apns.skip"})
        return
    payload = apns_payload_for_notification(notification)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        token = apns_auth_token()
    except Exception as exc:
        LOGGER.warning("error=%s", exc, extra={"event": "apns.token_failed"})
        return
    if not token:
        return
    for device in devices:
        env = device.get("environment") or APNS_ENVIRONMENT
        host = "https://api.sandbox.push.apple.com" if env == "development" else "https://api.push.apple.com"
        url = "%s/3/device/%s" % (host, device["device_token"])
        headers = {
            "authorization": "bearer %s" % token,
            "apns-topic": APNS_TOPIC,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        try:
            with httpx.Client(http2=True, timeout=8) as client:
                response = client.post(url, headers=headers, content=body)
            if response.status_code == 200:
                LOGGER.info("notification_id=%s environment=%s", notification.get("id"), env, extra={"event": "apns.sent"})
            else:
                LOGGER.warning(
                    "notification_id=%s status=%s body=%s",
                    notification.get("id"),
                    response.status_code,
                    response.text[:200],
                    extra={"event": "apns.failed"},
                )
        except Exception as exc:
            LOGGER.warning("notification_id=%s error=%s", notification.get("id"), exc, extra={"event": "apns.failed"})


def create_notification(user_id, notification_type, title, body="", album_id="", photo_id="", activity_id="", actor=None, data=None, db=None):
    if not user_id or not notification_type or not title:
        return None
    now = int(time.time())
    notification = {
        "id": uuid.uuid4().hex,
        "userId": user_id,
        "type": notification_type,
        "title": title,
        "body": body or "",
        "albumId": album_id or "",
        "photoId": photo_id or "",
        "activityId": activity_id or "",
        "actorUserId": (actor or {}).get("id", ""),
        "readAt": 0,
        "createdAt": now,
        "data": data or {},
    }
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO notifications(
                        id, user_id, type, title, body, album_id, photo_id,
                        activity_id, actor_user_id, read_at, created_at, data_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        notification["id"],
                        user_id,
                        notification_type,
                        title,
                        notification["body"],
                        notification["albumId"],
                        notification["photoId"],
                        notification["activityId"],
                        notification["actorUserId"],
                        now,
                        json.dumps(notification, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
        LOGGER.info(
            "user_id=%s notification_id=%s type=%s album_id=%s photo_id=%s",
            user_id,
            notification["id"],
            notification_type,
            notification["albumId"],
            notification["photoId"],
            extra={"event": "notification.create"},
        )
        dispatch_push_notification(notification)
        return notification

    target_db = db
    if target_db is None:
        target_db = load_db()
    target_db.setdefault("notifications", []).append(notification)
    if db is None:
        write_db(target_db)
    LOGGER.info(
        "user_id=%s notification_id=%s type=%s album_id=%s photo_id=%s",
        user_id,
        notification["id"],
        notification_type,
        notification["albumId"],
        notification["photoId"],
        extra={"event": "notification.create"},
    )
    dispatch_push_notification(notification)
    return notification


def list_user_notifications(user_id, unread_only=False, limit=50, before=0):
    limit = max(1, min(int(limit or 50), 200))
    if sqlite_enabled():
        sqlite_init_store()
        params = [user_id]
        where = "user_id = ?"
        if unread_only:
            where += " AND read_at IS NULL"
        if before:
            where += " AND created_at < ?"
            params.append(int(before))
        params.append(limit)
        with sqlite_connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM notifications
                WHERE %s
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """ % where,
                params,
            ).fetchall()
            unread = conn.execute(
                "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND read_at IS NULL",
                (user_id,),
            ).fetchone()
        return [public_notification(row) for row in rows], int(unread["count"] if unread else 0)
    db = load_db()
    items = [item for item in db.get("notifications", []) if item.get("userId") == user_id]
    unread_count = len([item for item in items if not item.get("readAt")])
    if unread_only:
        items = [item for item in items if not item.get("readAt")]
    if before:
        items = [item for item in items if int(item.get("createdAt") or 0) < int(before)]
    items.sort(key=lambda item: (int(item.get("createdAt") or 0), item.get("id", "")), reverse=True)
    return [public_notification(item) for item in items[:limit]], unread_count


def mark_user_notifications_read(user_id, notification_ids=None, mark_all=False):
    now = int(time.time())
    ids = [str(item) for item in (notification_ids or []) if item]
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                if mark_all:
                    updated = conn.execute(
                        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
                        (now, user_id),
                    ).rowcount
                elif ids:
                    placeholders = ",".join("?" for _ in ids)
                    updated = conn.execute(
                        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL AND id IN (%s)" % placeholders,
                        [now, user_id, *ids],
                    ).rowcount
                else:
                    updated = 0
        LOGGER.info("user_id=%s updated=%d all=%s", user_id, updated, mark_all, extra={"event": "notification.read"})
        return updated
    db = load_db()
    updated = 0
    for item in db.get("notifications", []):
        if item.get("userId") != user_id or item.get("readAt"):
            continue
        if mark_all or item.get("id") in ids:
            item["readAt"] = now
            updated += 1
    if updated:
        write_db(db)
    LOGGER.info("user_id=%s updated=%d all=%s", user_id, updated, mark_all, extra={"event": "notification.read"})
    return updated


def generate_invite_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def invite_public_payload(row, origin, album=None, current_user=None):
    if not row:
        return None
    code = row["code"] if isinstance(row, sqlite3.Row) else row.get("code")
    album_id = row["album_id"] if isinstance(row, sqlite3.Row) else row.get("albumId") or row.get("album_id")
    payload = {
        "id": row["id"] if isinstance(row, sqlite3.Row) else row.get("id"),
        "albumId": album_id,
        "code": code,
        "status": row["status"] if isinstance(row, sqlite3.Row) else row.get("status", "active"),
        "shareUrl": urljoin(origin, "/join/%s" % quote(code)),
        "qrUrl": urljoin(origin, "/api/invites/%s/qr.svg" % quote(code)),
        "createdAt": row["created_at"] if isinstance(row, sqlite3.Row) else row.get("createdAt") or row.get("created_at"),
    }
    try:
        raw_permissions = row["permissions_json"] if isinstance(row, sqlite3.Row) else row.get("permissionsJson") or row.get("permissions_json")
    except (KeyError, IndexError):
        raw_permissions = ""
    try:
        payload["permissions"] = normalize_album_permissions(json.loads(raw_permissions or "{}"))
    except (TypeError, json.JSONDecodeError):
        payload["permissions"] = normalize_album_permissions()
    if album:
        payload["albumName"] = album.get("name", "")
        payload["photoCount"] = len(album.get("photos", []))
    if current_user:
        payload["currentUserRole"] = album_member_role(album_id, current_user.get("id"))
    return payload


def active_invite_for_album(album_id, created_by, origin, album=None, current_user=None, permissions=None):
    if not sqlite_enabled():
        return None
    sqlite_init_store()
    with sqlite_connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM album_invites
            WHERE album_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (album_id,),
        ).fetchone()
        if row:
            if permissions is not None:
                with conn:
                    conn.execute(
                        "UPDATE album_invites SET permissions_json = ? WHERE id = ?",
                        (permissions_json(permissions), row["id"]),
                    )
                row = conn.execute("SELECT * FROM album_invites WHERE id = ?", (row["id"],)).fetchone()
            return invite_public_payload(row, origin, album, current_user)

        now = int(time.time())
        invite_permissions = permissions_json(permissions)
        for _ in range(20):
            code = generate_invite_code()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO album_invites(
                            id, album_id, code, token_hash, status, created_by, created_at, revoked_at, permissions_json
                        )
                        VALUES(?, ?, ?, ?, 'active', ?, ?, NULL, ?)
                        """,
                        (uuid.uuid4().hex, album_id, code, hash_auth_token("%s:%s" % (code, uuid.uuid4().hex)), created_by, now, invite_permissions),
                    )
                break
            except sqlite3.IntegrityError:
                continue
        row = conn.execute("SELECT * FROM album_invites WHERE album_id = ? AND status = 'active'", (album_id,)).fetchone()
        return invite_public_payload(row, origin, album, current_user)


def invite_by_code(code):
    if not sqlite_enabled():
        return None
    sqlite_init_store()
    with sqlite_connect() as conn:
        return conn.execute(
            "SELECT * FROM album_invites WHERE upper(code) = ? AND status = 'active'",
            (str(code or "").strip().upper(),),
        ).fetchone()


def latest_join_request(album_id, user_id):
    if not sqlite_enabled():
        return None
    sqlite_init_store()
    with sqlite_connect() as conn:
        return conn.execute(
            """
            SELECT * FROM album_join_requests
            WHERE album_id = ? AND user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (album_id, user_id),
        ).fetchone()


def new_token():
    return secrets.token_urlsafe(48)


def create_auth_token(user_id, session_id=None):
    token = new_token()
    token_hash = hash_auth_token(token)
    now = int(time.time())
    expires_at = now + ACCESS_TOKEN_TTL_SECONDS
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM auth_tokens WHERE expires_at < ?",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO auth_tokens(token_hash, user_id, created_at, expires_at, session_id) VALUES(?, ?, ?, ?, ?)",
                    (token_hash, user_id, now, expires_at, session_id),
                )
    else:
        db = load_db()
        db["authTokens"] = [
            item for item in db.get("authTokens", [])
            if int(item.get("expiresAt") or 0) >= now
        ]
        db["authTokens"].append({"tokenHash": token_hash, "userId": user_id, "sessionId": session_id, "createdAt": now, "expiresAt": expires_at})
        write_db(db)
    return token


def create_refresh_token(conn, session_id, user_id, now):
    token = new_token()
    token_hash = hash_auth_token(token)
    conn.execute(
        """
        INSERT INTO refresh_tokens(token_hash, session_id, user_id, created_at, expires_at, revoked_at, replaced_by_token_hash)
        VALUES(?, ?, ?, ?, ?, NULL, NULL)
        """,
        (token_hash, session_id, user_id, now, now + REFRESH_TOKEN_TTL_SECONDS),
    )
    return token


def auth_payload(user, request_handler=None, session_id=None):
    now = int(time.time())
    session_id = session_id or uuid.uuid4().hex
    device_id = request_handler.headers.get("X-Device-Id", "").strip()[:120] if request_handler else ""
    device_name = request_handler.headers.get("X-Device-Name", "").strip()[:120] if request_handler else ""
    user_agent = request_handler.headers.get("User-Agent", "").strip()[:240] if request_handler else ""
    access_token = create_auth_token(user["id"], session_id=session_id)
    refresh_token = ""
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO auth_sessions(
                        id, user_id, device_id, device_name, user_agent,
                        created_at, last_seen_at, expires_at, revoked_at, revoked_reason, data_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        session_id,
                        user["id"],
                        device_id,
                        device_name,
                        user_agent,
                        now,
                        now,
                        now + REFRESH_TOKEN_TTL_SECONDS,
                        json.dumps({"deviceId": device_id, "deviceName": device_name, "userAgent": user_agent}, ensure_ascii=False),
                    ),
                )
                refresh_token = create_refresh_token(conn, session_id, user["id"], now)
    payload = {
        "token": access_token,
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": ACCESS_TOKEN_TTL_SECONDS,
        "refreshExpiresIn": REFRESH_TOKEN_TTL_SECONDS,
        "sessionId": session_id,
    }
    return payload


def refresh_auth_tokens(refresh_token):
    if not refresh_token or not sqlite_enabled():
        return None
    refresh_hash = hash_auth_token(refresh_token)
    now = int(time.time())
    sqlite_init_store()
    with sqlite_connect() as conn:
        row = conn.execute(
            """
            SELECT rt.token_hash, rt.session_id, rt.user_id, rt.expires_at, rt.revoked_at,
                   s.expires_at AS session_expires_at, s.revoked_at AS session_revoked_at
            FROM refresh_tokens rt
            JOIN auth_sessions s ON s.id = rt.session_id
            WHERE rt.token_hash = ?
            """,
            (refresh_hash,),
        ).fetchone()
        if not row:
            return None
        if row["revoked_at"] or row["session_revoked_at"] or int(row["expires_at"]) < now or int(row["session_expires_at"]) < now:
            return None
        user_row = conn.execute("SELECT data_json FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if not user_row:
            return None
        user = json.loads(user_row["data_json"])
        new_access = create_auth_token(row["user_id"], session_id=row["session_id"])
        with conn:
            new_refresh = create_refresh_token(conn, row["session_id"], row["user_id"], now)
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = ?, replaced_by_token_hash = ? WHERE token_hash = ?",
                (now, hash_auth_token(new_refresh), refresh_hash),
            )
            conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, row["session_id"]))
        return {
            "user": user,
            "token": new_access,
            "accessToken": new_access,
            "refreshToken": new_refresh,
            "expiresIn": ACCESS_TOKEN_TTL_SECONDS,
            "refreshExpiresIn": REFRESH_TOKEN_TTL_SECONDS,
            "sessionId": row["session_id"],
        }


def delete_auth_token(token):
    token_hash = hash_auth_token(token)
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
    else:
        db = load_db()
        db["authTokens"] = [item for item in db.get("authTokens", []) if item.get("tokenHash") != token_hash]
        write_db(db)


def revoke_session_for_access_token(token):
    token_hash = hash_auth_token(token)
    now = int(time.time())
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            row = conn.execute("SELECT session_id FROM auth_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
            with conn:
                conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
                if row and row["session_id"]:
                    conn.execute(
                        "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = ? WHERE id = ? AND revoked_at IS NULL",
                        (now, "logout", row["session_id"]),
                    )
                    conn.execute(
                        "UPDATE refresh_tokens SET revoked_at = ? WHERE session_id = ? AND revoked_at IS NULL",
                        (now, row["session_id"]),
                    )
        return
    delete_auth_token(token)


def user_for_token(token):
    if not token:
        return None
    token_hash = hash_auth_token(token)
    now = int(time.time())
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            row = conn.execute(
                """
                SELECT at.user_id, at.expires_at, at.session_id,
                       s.expires_at AS session_expires_at, s.revoked_at AS session_revoked_at
                FROM auth_tokens at
                LEFT JOIN auth_sessions s ON s.id = at.session_id
                WHERE at.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if int(row["expires_at"]) < now:
                with conn:
                    conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
                return None
            if row["session_id"] and (row["session_revoked_at"] or int(row["session_expires_at"] or 0) < now):
                with conn:
                    conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
                return None
            if row["session_id"]:
                with conn:
                    conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, row["session_id"]))
            user_row = conn.execute("SELECT data_json FROM users WHERE id = ?", (row["user_id"],)).fetchone()
            return json.loads(user_row["data_json"]) if user_row else None
    db = load_db()
    token_row = next((item for item in db.get("authTokens", []) if item.get("tokenHash") == token_hash), None)
    if not token_row or int(token_row.get("expiresAt") or 0) < now:
        return None
    return find_user_by_id(db, token_row.get("userId"))


def slugify(value):
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-.")
    return value or "album"


def unique_archive_name(filename, used_names):
    path = Path(filename)
    stem = path.stem or "photo"
    suffix = path.suffix
    candidate = path.name or "photo"
    index = 2
    while candidate in used_names:
        candidate = "%s-%d%s" % (stem, index, suffix)
        index += 1
    used_names.add(candidate)
    return candidate


def oss_read_bytes(object_key):
    if not oss_enabled() or not object_key:
        return None
    try:
        body = OSS_SERVICE.bucket.get_object(object_key).read()
        LOGGER.info("object_key=%s bytes=%d", object_key, len(body), extra={"event": "oss.read"})
        return body
    except Exception as error:
        LOGGER.warning("object_key=%s error=%s", object_key, error, extra={"event": "oss.download_failed"})
        return None


def write_resource_to_archive(archive, album_id, photo, used_names, video=False, folder_name=None):
    if video:
        stored_name = photo.get("liveVideoStoredName")
        original_name = photo.get("liveVideoOriginalName") or stored_name
        object_key = live_video_object_key(photo)
    else:
        stored_name = photo.get("storedName")
        original_name = photo.get("originalName") or stored_name
        object_key = original_object_key(photo)
    if not stored_name:
        return False
    arcname = unique_archive_name(original_name or stored_name, used_names)
    if folder_name:
        arcname = "%s/%s" % (folder_name, arcname)
    source = UPLOADS / album_id / stored_name
    if source.exists():
        archive.write(source, arcname=arcname)
        return True
    body = oss_read_bytes(object_key)
    if body is not None:
        archive.writestr(arcname, body)
        return True
    return False


def resource_download_item(album_id, photo, used_names=None, video=False, folder_name=None):
    if video:
        stored_name = photo.get("liveVideoStoredName")
        original_name = photo.get("liveVideoOriginalName") or stored_name
        object_key = live_video_object_key(photo)
        mime_type = photo.get("liveVideoMimeType") or safe_mime_type(original_name)
    else:
        stored_name = photo.get("storedName")
        original_name = photo.get("originalName") or stored_name
        object_key = original_object_key(photo)
        mime_type = photo.get("mime_type") or photo.get("mimeType") or safe_mime_type(original_name)
    if not stored_name:
        return None
    filename = original_name or stored_name
    if used_names is not None:
        filename = unique_archive_name(filename, used_names)
    if folder_name:
        filename = "%s/%s" % (folder_name, filename)
    url = oss_signed_or_empty(object_key)
    if not url:
        local_source = UPLOADS / album_id / stored_name
        if local_source.exists():
            url = "/uploads/%s/%s" % (album_id, quote(stored_name))
    if not url:
        return None
    return {
        "name": filename,
        "url": url,
        "mimeType": mime_type,
        "objectKey": object_key or "",
        "size": int(photo.get("liveVideoFileSize" if video else "file_size") or 0),
    }


def remove_thumbnails(album_id, stored_name=None):
    album_dir = THUMBS / album_id
    if not album_dir.exists():
        return
    if stored_name is None:
        shutil.rmtree(album_dir)
        return
    for size_dir in album_dir.iterdir():
        target = size_dir / ("%s.jpg" % stored_name)
        if target.exists():
            target.unlink()


def remove_preview(album_id, stored_name=None):
    album_dir = PREVIEWS / album_id
    if not album_dir.exists():
        return
    if stored_name is None:
        shutil.rmtree(album_dir)
        return
    target = album_dir / ("%s.jpg" % stored_name)
    if target.exists():
        target.unlink()


def generate_preview(album_id, stored_name):
    source = UPLOADS / album_id / stored_name
    if not source.exists():
        return None
    target_dir = PREVIEWS / album_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("%s.jpg" % stored_name)
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target

    suffix = source.suffix.lower()
    if suffix in LIVE_IMAGE_EXTS:
        if Image is None:
            return None
        try:
            image = Image.open(source).convert("RGB")
            image.save(target, "JPEG", quality=88)
            return target
        except Exception:
            return None

    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        return None
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        return None
    target.write_bytes(encoded.tobytes())
    return target


def readable_image_path(album_id, stored_name):
    source = UPLOADS / album_id / stored_name
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is not None:
        return source
    return generate_preview(album_id, stored_name)


def generate_thumbnail(album_id, stored_name, size):
    if size not in THUMB_SPECS:
        return None
    source = readable_image_path(album_id, stored_name)
    if not source or not source.exists():
        return None
    max_width, quality = THUMB_SPECS[size]
    target_dir = THUMBS / album_id / size
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("%s.jpg" % stored_name)
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target

    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    scale = min(1.0, max_width / max(width, 1))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    target.write_bytes(encoded.tobytes())
    return target


def generate_all_thumbnails(album_id, stored_name):
    for size in THUMB_SPECS:
        generate_thumbnail(album_id, stored_name, size)


def detect_primary_face_box(image):
    app = get_insightface_app()
    if app:
        faces, _ = filter_subject_faces(app.get(image), image.shape)
        if faces:
            face = max(faces, key=lambda item: bbox_area(item.bbox))
            x1, y1, x2, y2 = [float(value) for value in face.bbox]
            return x1, y1, x2, y2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=5, minSize=(32, 32))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
    return float(x), float(y), float(x + w), float(y + h)


def clamp_square_crop_bounds(width, height, cx, cy, side):
    side = int(round(max(1.0, min(float(side), float(width), float(height)))))
    max_left = max(0, width - side)
    max_top = max(0, height - side)
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    left = min(max(left, 0), max_left)
    top = min(max(top, 0), max_top)
    return left, top, left + side, top + side


def crop_square_around_box(image, box, scale=2.15, y_offset_ratio=-0.08):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    face_w = max(1.0, x2 - x1)
    face_h = max(1.0, y2 - y1)
    side = max(face_w, face_h) * scale
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 + face_h * y_offset_ratio

    left, top, right, bottom = clamp_square_crop_bounds(width, height, cx, cy, side)
    if right <= left or bottom <= top:
        return None
    return image[top:bottom, left:right]


def encode_face_thumbnail(image, box):
    crop = crop_square_around_box(image, box)
    if crop is None:
        return None
    crop = cv2.resize(crop, (420, 420), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    if not ok:
        return None
    return encoded


def generate_face_thumbnail(album_id, stored_name):
    source = readable_image_path(album_id, stored_name)
    if not source or not source.exists():
        return None
    target_dir = THUMBS / album_id / "face"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("%s.jpg" % stored_name)
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target

    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        return None
    box = detect_primary_face_box(image)
    if not box:
        return None

    encoded = encode_face_thumbnail(image, box)
    if encoded is None:
        return None
    target.write_bytes(encoded.tobytes())
    return target


def local_upload_path(album_id, photo):
    stored_name = photo.get("storedName") or ""
    return UPLOADS / album_id / stored_name


def materialize_photo_source(album_id, photo):
    source = local_upload_path(album_id, photo)
    if source.exists():
        return source, lambda: None
    key = original_object_key(photo)
    if not oss_enabled() or not key:
        return None, lambda: None
    suffix = Path(photo.get("storedName") or photo.get("originalName") or "source.jpg").suffix or ".jpg"
    tmp = tempfile.NamedTemporaryFile(prefix="picme-source-", suffix=suffix, delete=False)
    tmp.close()
    target = Path(tmp.name)
    try:
        OSS_SERVICE.downloadFile(key, target)
    except Exception as error:
        LOGGER.warning(
            "album_id=%s photo_id=%s object_key=%s error=%s",
            album_id,
            photo.get("id", ""),
            key,
            error,
            extra={"event": "photo.source_download_failed"},
        )
        target.unlink(missing_ok=True)
        return None, lambda: None
    return target, lambda: target.unlink(missing_ok=True)


def materialize_avatar_source(user):
    avatar_object_key = (user or {}).get("avatarObjectKey") or (user or {}).get("avatar_object_key") or ""
    if avatar_object_key and oss_enabled():
        tmp = tempfile.NamedTemporaryFile(prefix="picme-avatar-source-", suffix=".jpg", delete=False)
        tmp.close()
        target = Path(tmp.name)
        try:
            OSS_SERVICE.downloadFile(avatar_object_key, target)
        except Exception as error:
            LOGGER.warning(
                "user_id=%s object_key=%s error=%s",
                (user or {}).get("id", ""),
                avatar_object_key,
                error,
                extra={"event": "avatar.source_download_failed"},
            )
            target.unlink(missing_ok=True)
            return None, lambda: None
        return target, lambda: target.unlink(missing_ok=True)
    avatar_url = (user or {}).get("avatarUrl") or (user or {}).get("avatar_url") or ""
    if avatar_url and not re.match(r"^https?://", avatar_url):
        source = DATA / avatar_url.lstrip("/")
        if source.exists():
            return source, lambda: None
    local = AVATARS / ("%s.jpg" % ((user or {}).get("id") or ""))
    if local.exists():
        return local, lambda: None
    return None, lambda: None


def readable_source_for_path(source):
    source = Path(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is not None:
        return source, lambda: None
    if source.suffix.lower() in LIVE_IMAGE_EXTS and Image is not None:
        tmp = tempfile.NamedTemporaryFile(prefix="picme-readable-", suffix=".jpg", delete=False)
        tmp.close()
        target = Path(tmp.name)
        try:
            Image.open(source).convert("RGB").save(target, "JPEG", quality=90)
            return target, lambda: target.unlink(missing_ok=True)
        except Exception:
            target.unlink(missing_ok=True)
    return None, lambda: None


def generate_preview_for_photo(album_id, photo, source):
    if not oss_enabled():
        return generate_preview(album_id, photo.get("storedName", ""))
    readable, cleanup = readable_source_for_path(source)
    if not readable:
        return None
    tmp = tempfile.NamedTemporaryFile(prefix="picme-preview-", suffix=".jpg", delete=False)
    tmp.close()
    target = Path(tmp.name)
    try:
        image = cv2.imread(str(readable), cv2.IMREAD_COLOR)
        if image is None:
            return None
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return None
        target.write_bytes(encoded.tobytes())
        key = OSS_SERVICE.generateObjectKey("preview", album_id=album_id, photo_id=photo["id"])
        metadata = OSS_SERVICE.uploadFile(target, key, "image/jpeg", "preview")
        if metadata:
            apply_resource_metadata(photo, metadata, "preview")
        return target
    finally:
        cleanup()
        target.unlink(missing_ok=True)


def generate_thumbnail_for_photo(album_id, photo, source):
    if not oss_enabled():
        generate_all_thumbnails(album_id, photo.get("storedName", ""))
        return None
    readable, cleanup = readable_source_for_path(source)
    if not readable:
        return None
    tmp = tempfile.NamedTemporaryFile(prefix="picme-thumb-", suffix=".webp", delete=False)
    tmp.close()
    target = Path(tmp.name)
    try:
        image = cv2.imread(str(readable), cv2.IMREAD_COLOR)
        if image is None:
            return None
        height, width = image.shape[:2]
        max_width = 900
        scale = min(1.0, max_width / max(width, 1))
        if scale < 1.0:
            image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".webp", image, [int(cv2.IMWRITE_WEBP_QUALITY), 78])
        if not ok:
            return None
        target.write_bytes(encoded.tobytes())
        key = OSS_SERVICE.generateObjectKey("thumb", album_id=album_id, photo_id=photo["id"])
        metadata = OSS_SERVICE.uploadFile(target, key, "image/webp", "thumb")
        if metadata:
            apply_resource_metadata(photo, metadata, "thumb")
        return target
    finally:
        cleanup()
        target.unlink(missing_ok=True)


def generate_face_thumbnail_for_photo(album_id, photo, source, user_id=None):
    if not oss_enabled():
        return generate_face_thumbnail(album_id, photo.get("storedName", ""))
    readable, cleanup = readable_source_for_path(source)
    if not readable:
        return None
    tmp = tempfile.NamedTemporaryFile(prefix="picme-face-", suffix=".jpg", delete=False)
    tmp.close()
    target = Path(tmp.name)
    try:
        image = cv2.imread(str(readable), cv2.IMREAD_COLOR)
        if image is None:
            return None
        box = detect_primary_face_box(image)
        if not box:
            return None
        encoded = encode_face_thumbnail(image, box)
        if encoded is None:
            return None
        target.write_bytes(encoded.tobytes())
        key = OSS_SERVICE.generateObjectKey("faces", album_id=album_id, photo_id=photo["id"], user_id=user_id or album_id)
        metadata = OSS_SERVICE.uploadFile(target, key, "image/jpeg", "faces")
        apply_resource_metadata(photo, metadata, "face")
        return target
    finally:
        cleanup()
        target.unlink(missing_ok=True)


def find_album(db, album_id):
    for album in db["albums"]:
        if album["id"] == album_id:
            return album
    return None


def thumb_url(photo, size):
    if oss_enabled():
        signed = oss_signed_or_empty(thumb_object_key(photo)) or oss_signed_or_empty(preview_object_key(photo)) or oss_signed_or_empty(original_object_key(photo))
        if signed:
            return signed
    return "/thumbs/%s/%s/%s" % (photo.get("albumId", ""), size, quote(photo.get("storedName", "")))


def preview_url(photo):
    if oss_enabled():
        signed = oss_signed_or_empty(preview_object_key(photo)) or oss_signed_or_empty(original_object_key(photo))
        if signed:
            return signed
    return "/previews/%s/%s" % (photo.get("albumId", ""), quote(photo.get("storedName", "")))


def photo_public_urls(album_id, photo):
    item = dict(photo)
    item["albumId"] = album_id
    item["tinyUrl"] = thumb_url(item, "tiny")
    item["cardUrl"] = thumb_url(item, "card")
    item["coverUrl"] = thumb_url(item, "cover")
    item["previewUrl"] = preview_url(item)
    item["thumbnailUrl"] = item["cardUrl"]
    default_image = "/uploads/%s/%s" % (album_id, item.get("storedName", ""))
    item["imageUrl"] = item.get("url") or default_image
    if oss_enabled():
        signed = oss_signed_or_empty(original_object_key(item))
        if signed:
            item["imageUrl"] = signed
        video_signed = oss_signed_or_empty(live_video_object_key(item))
        if video_signed:
            item["videoUrl"] = video_signed
    item["faceUrl"] = (oss_signed_or_empty(face_object_key(item)) if oss_enabled() else "") or ("/face-thumbs/%s/%s" % (album_id, quote(item.get("storedName", ""))))
    return item


def folder_uses_scene_cover(folder):
    return folder.get("id") in {"group-photo", "no-face"}


def choose_folder_cover_photo(folder, photos):
    if not photos:
        return None
    if folder_uses_scene_cover(folder):
        return photos[0]
    return next((photo for photo in photos if len(photo_folder_ids(photo)) == 1), None) or photos[0]


def folder_cover_url(album_id, folder, photo):
    if not photo:
        return ""
    item = photo_public_urls(album_id, photo)
    return item.get("coverUrl") or item.get("cardUrl") or item.get("imageUrl") or item.get("faceUrl") or ""


def folder_cover_object_key(folder, photo):
    if not photo or not oss_enabled():
        return ""
    return thumb_object_key(photo) or preview_object_key(photo) or original_object_key(photo) or face_object_key(photo)


def sync_folder_covers(album):
    folders = album.get("folders", [])
    if not folders:
        return False
    changed = False
    for folder in folders:
        before = {
            "photoIds": folder.get("photoIds"),
            "photoCount": folder.get("photoCount"),
            "updatedAt": folder.get("updatedAt"),
            "coverPhotoId": folder.get("coverPhotoId"),
            "coverUrl": folder.get("coverUrl"),
            "cover_url": folder.get("cover_url"),
            "coverObjectKey": folder.get("coverObjectKey"),
        }
        folder_photos = [
            photo for photo in album.get("photos", [])
            if folder.get("id") in photo_folder_ids(photo)
        ]
        folder_photos.sort(key=lambda item: item.get("createdAt", 0), reverse=True)
        cover_photo = choose_folder_cover_photo(folder, folder_photos)
        folder["photoIds"] = [photo["id"] for photo in folder_photos]
        folder["photoCount"] = len(folder_photos)
        folder["updatedAt"] = folder_photos[0].get("createdAt", folder.get("updatedAt")) if folder_photos else folder.get("updatedAt")
        if cover_photo:
            folder["coverPhotoId"] = cover_photo["id"]
            cover_key = folder_cover_object_key(folder, cover_photo)
            if cover_key:
                folder["coverObjectKey"] = cover_key
                folder["coverUrl"] = oss_direct_url(cover_key)
            else:
                folder.pop("coverObjectKey", None)
                folder["coverUrl"] = folder_cover_url(album["id"], folder, cover_photo)
            folder["cover_url"] = folder["coverUrl"]
        else:
            folder.pop("coverPhotoId", None)
            folder.pop("coverUrl", None)
            folder.pop("cover_url", None)
            folder.pop("coverObjectKey", None)
        after = {
            "photoIds": folder.get("photoIds"),
            "photoCount": folder.get("photoCount"),
            "updatedAt": folder.get("updatedAt"),
            "coverPhotoId": folder.get("coverPhotoId"),
            "coverUrl": folder.get("coverUrl"),
            "cover_url": folder.get("cover_url"),
            "coverObjectKey": folder.get("coverObjectKey"),
        }
        changed = changed or before != after
    return changed


def sync_all_folder_covers(db):
    changed = False
    for album in db.get("albums", []):
        changed = sync_folder_covers(album) or changed
    return changed


def public_album(album, current_user=None):
    sync_folder_covers(album)
    album_permissions = ensure_album_permissions(album)
    visible = dict(album)
    role = album_member_role(album.get("id"), current_user.get("id")) if current_user else ""
    current_permissions = effective_album_permissions(album, current_user) if current_user else {key: False for key in ALBUM_PERMISSION_KEYS}
    visible["currentUserRole"] = role
    visible["canManage"] = role in {"owner", "admin", "member"}
    visible["canAdmin"] = role in {"owner", "admin"}
    visible["isOwner"] = is_album_owner(album, current_user.get("id")) if current_user else False
    visible["permissions"] = album_permissions
    visible["currentUserPermissions"] = current_permissions
    visible["folders"] = []
    for folder in album.get("folders", []):
        if folder.get("id") == "pending":
            continue
        item = {key: value for key, value in folder.items() if key not in {"embedding", "embeddingCount", "embeddingEngine"}}
        if oss_enabled() and item.get("coverObjectKey"):
            item["coverUrl"] = oss_signed_or_empty(item["coverObjectKey"])
            item["cover_url"] = item["coverUrl"]
        if item.get("id") == "no-face" or item.get("name") == "未识别人脸":
            item["name"] = "其他"
        visible["folders"].append(item)
    folder_names = {folder["id"]: folder["name"] for folder in visible["folders"]}
    visible["photos"] = []
    for photo in album.get("photos", []):
        item = dict(photo)
        item["albumId"] = album["id"]
        item["type"] = item.get("type") or "photo"
        item["tinyUrl"] = thumb_url(item, "tiny")
        item["cardUrl"] = thumb_url(item, "card")
        item["coverUrl"] = thumb_url(item, "cover")
        item["previewUrl"] = preview_url(item)
        item["thumbnailUrl"] = item["cardUrl"]
        item["imageUrl"] = item.get("url") or "/uploads/%s/%s" % (album["id"], item.get("storedName", ""))
        if oss_enabled():
            signed = oss_signed_or_empty(original_object_key(item))
            if signed:
                item["imageUrl"] = signed
        item["image_url"] = item["imageUrl"]
        item["preview_url"] = item["previewUrl"]
        item["thumbnail_url"] = item["thumbnailUrl"]
        if item.get("liveVideoStoredName"):
            item["videoUrl"] = "/uploads/%s/%s" % (album["id"], item["liveVideoStoredName"])
            if oss_enabled():
                signed = oss_signed_or_empty(live_video_object_key(item))
                if signed:
                    item["videoUrl"] = signed
            item["video_url"] = item["videoUrl"]
            item["downloadLiveUrl"] = "/api/albums/%s/photos/%s/download-live" % (album["id"], item["id"])
        item["downloadImageUrl"] = "/api/albums/%s/photos/%s/download-image" % (album["id"], item["id"])
        item["faceUrl"] = (oss_signed_or_empty(face_object_key(item)) if oss_enabled() else "") or "/face-thumbs/%s/%s" % (album["id"], quote(item.get("storedName", "")))
        ids = photo_folder_ids(item)
        if ids:
            original_names = item.get("folderNames", [])
            item["folderNames"] = [
                folder_names.get(folder_id, original_names[index] if index < len(original_names) else "")
                for index, folder_id in enumerate(ids)
            ]
            if item.get("folderId") in folder_names:
                item["folderName"] = folder_names[item["folderId"]]
        visible["photos"].append(item)
    apply_my_photo_recommendation(visible, album, current_user)
    return visible


def apply_my_photo_recommendation(visible, album, current_user):
    match = resolve_user_album_match(album, current_user, allow_compute=False)
    if not match or not match.get("matched") or not match.get("folderId"):
        visible["myPhotoIds"] = []
        visible["myPhotoCount"] = 0
        visible["myCoverUrl"] = ""
        return
    folder_id = match["folderId"]
    best_folder = next((folder for folder in album.get("folders", []) if folder.get("id") == folder_id), None)
    if not best_folder:
        visible["myPhotoIds"] = []
        visible["myPhotoCount"] = 0
        visible["myCoverUrl"] = ""
        return
    my_photo_ids = [
        photo.get("id") for photo in album.get("photos", [])
        if folder_id in photo_folder_ids(photo)
    ]
    my_photo_ids = [photo_id for photo_id in my_photo_ids if photo_id]
    visible["myPhotoIds"] = my_photo_ids
    visible["myPhotoCount"] = len(my_photo_ids)
    visible["myMatchedFolderId"] = folder_id
    visible["myMatchedFolderName"] = best_folder.get("name") or "我的照片"
    public_photos_by_id = {photo.get("id"): photo for photo in visible.get("photos", [])}
    cover_photo = next((public_photos_by_id.get(photo_id) for photo_id in my_photo_ids if public_photos_by_id.get(photo_id)), None)
    visible["myCoverUrl"] = (cover_photo or {}).get("faceUrl") or (cover_photo or {}).get("coverUrl") or (cover_photo or {}).get("cardUrl") or ""


def user_avatar_match_key(user):
    embedding = (user or {}).get("avatarEmbedding")
    engine = (user or {}).get("avatarEmbeddingEngine") or ""
    updated_at = int((user or {}).get("avatarProfileUpdatedAt") or 0)
    digest = hashlib.sha256(json.dumps(embedding or [], separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return "%s:%s:%s:%s" % (MY_PHOTOS_MATCH_ALGORITHM_VERSION, engine, updated_at, digest)


def album_folder_fingerprint(album):
    parts = []
    for folder in album.get("folders", []):
        if folder.get("id") in {"pending", "group-photo", "no-face"}:
            continue
        if not folder.get("embedding") or not folder.get("embeddingEngine"):
            continue
        parts.append(
            "%s:%s:%s:%s" % (
                folder.get("id", ""),
                folder.get("embeddingEngine", ""),
                int(folder.get("embeddingCount") or 0),
                int(folder.get("embeddingUpdatedAt") or folder.get("createdAt") or 0),
            )
        )
    return "|".join(sorted(parts))


def compute_user_album_match(album, current_user):
    started_at = time.perf_counter()
    user_embedding = (current_user or {}).get("avatarEmbedding")
    user_engine = (current_user or {}).get("avatarEmbeddingEngine")
    base = {
        "albumId": album.get("id", ""),
        "matched": False,
        "folderId": "",
        "distance": None,
        "avatarMatchKey": user_avatar_match_key(current_user),
        "folderFingerprint": album_folder_fingerprint(album),
        "updatedAt": int(time.time()),
    }
    if not user_embedding or not user_engine:
        LOGGER.info(
            "相册关联匹配跳过：缺少头像特征 album_id=%s user_id=%s 耗时=%sms",
            album.get("id", ""),
            (current_user or {}).get("id", ""),
            elapsed_ms(started_at),
            extra={"event": "my_photos.match_skip"},
        )
        return base
    best_folder = None
    best_distance = 999.0
    candidate_engines = set()
    for folder in album.get("folders", []):
        if folder.get("id") in {"pending", "group-photo", "no-face"}:
            continue
        if folder.get("embeddingEngine"):
            candidate_engines.add(folder.get("embeddingEngine"))
        if folder.get("embeddingEngine") != user_engine or not folder.get("embedding"):
            continue
        candidates = [folder.get("embedding")]
        samples = folder.get("embeddingSamples")
        if isinstance(samples, list):
            candidates.extend(sample for sample in samples if sample)
        folder_distance = min(cosine_distance(user_embedding, candidate) for candidate in candidates)
        if folder_distance < best_distance:
            best_distance = folder_distance
            best_folder = folder
    threshold = INSIGHTFACE_MATCH_THRESHOLD if user_engine == "insightface" else OPENCV_MATCH_THRESHOLD
    if not best_folder or best_distance > threshold:
        LOGGER.info(
            "相册关联匹配未命中：album_id=%s user_id=%s engine=%s best_folder_id=%s distance=%s threshold=%s candidate_engines=%s 耗时=%sms",
            album.get("id", ""),
            (current_user or {}).get("id", ""),
            user_engine,
            (best_folder or {}).get("id", ""),
            "" if best_distance == 999.0 else round(float(best_distance), 6),
            threshold,
            ",".join(sorted(candidate_engines)),
            elapsed_ms(started_at),
            extra={"event": "my_photos.match_miss"},
        )
        return base
    LOGGER.info(
        "相册关联匹配命中：album_id=%s user_id=%s engine=%s folder_id=%s distance=%s threshold=%s 耗时=%sms",
        album.get("id", ""),
        (current_user or {}).get("id", ""),
        user_engine,
        best_folder.get("id", ""),
        round(float(best_distance), 6),
        threshold,
        elapsed_ms(started_at),
        extra={"event": "my_photos.match_hit"},
    )
    base.update(
        {
            "matched": True,
            "folderId": best_folder.get("id", ""),
            "folderName": best_folder.get("name") or "我的照片",
            "distance": round(float(best_distance), 6),
            "engine": user_engine,
            "threshold": threshold,
        }
    )
    return base


def stored_user_album_match(album, current_user):
    matches = (current_user or {}).get("avatarAlbumMatches") or {}
    if not isinstance(matches, dict):
        return None
    match = matches.get(album.get("id", ""))
    if not isinstance(match, dict):
        return None
    if match.get("avatarMatchKey") != user_avatar_match_key(current_user):
        return None
    if match.get("folderFingerprint") != album_folder_fingerprint(album):
        return None
    if match.get("matched"):
        folder_id = match.get("folderId")
        folder = next((item for item in album.get("folders", []) if item.get("id") == folder_id), None)
        if not folder or folder.get("id") in {"pending", "group-photo", "no-face"}:
            return None
    return match


def album_match_photo_ids(album, folder_id):
    if not folder_id:
        return []
    return [
        photo.get("id") for photo in album.get("photos", [])
        if photo.get("id") and folder_id in photo_folder_ids(photo)
    ]


def enrich_album_match_photo_state(album, match):
    if not isinstance(match, dict) or not match.get("matched"):
        return match
    photo_ids = album_match_photo_ids(album, match.get("folderId") or "")
    match["photoIds"] = photo_ids
    match["photoCount"] = len(photo_ids)
    return match


def resolve_user_album_match(album, current_user, allow_compute=True):
    stored = stored_user_album_match(album, current_user)
    if stored or not allow_compute:
        return stored
    return enrich_album_match_photo_state(album, compute_user_album_match(album, current_user))


def ensure_user_album_match(db, album, current_user):
    if not current_user or not current_user.get("id"):
        return False
    user = find_user_by_id(db, current_user.get("id"))
    if not user:
        return False
    next_match = resolve_user_album_match(album, user)
    matches = user.setdefault("avatarAlbumMatches", {})
    album_id = album.get("id", "")
    if matches.get(album_id) == next_match:
        return False
    matches[album_id] = next_match
    upsert_user(db, user)
    if current_user is not user:
        current_user["avatarAlbumMatches"] = user.get("avatarAlbumMatches", {})
    return True


def notify_user_album_match_if_needed(user, album, previous_match, next_match):
    if not user or not album or not next_match or not next_match.get("matched"):
        return
    previous_match = previous_match if isinstance(previous_match, dict) else {}
    folder_id = next_match.get("folderId") or ""
    photo_ids = album_match_photo_ids(album, folder_id)
    previous_photo_ids = set(previous_match.get("photoIds") or [])
    new_photo_ids = [item for item in photo_ids if item not in previous_photo_ids]
    if previous_match.get("matched") and previous_match.get("folderId") == folder_id and not new_photo_ids:
        return
    album_name = album_display_name(album)
    is_same_folder = previous_match.get("matched") and previous_match.get("folderId") == folder_id
    title = "有新的你的照片" if is_same_folder else "匹配到你的照片"
    count = len(new_photo_ids) if is_same_folder else len(photo_ids)
    body = "在「%s」中新增 %d 张可能属于你的照片" % (album_name, count) if is_same_folder else "在「%s」中找到了 %d 张可能属于你的照片" % (album_name, len(photo_ids))
    create_notification(
        user.get("id"),
        "face.my_photos_matched",
        title,
        body,
        album_id=album.get("id", ""),
        data={
            "albumName": album_name,
            "folderId": folder_id,
            "folderName": next_match.get("folderName") or "我的照片",
            "photoIds": photo_ids,
            "newPhotoIds": new_photo_ids if is_same_folder else photo_ids,
            "photoCount": len(photo_ids),
            "distance": next_match.get("distance"),
        },
    )


def save_avatar_profile(user, source_path):
    readable, cleanup_readable = readable_source_for_path(source_path)
    if not readable:
        return "头像无法读取，暂不能推荐我的照片"
    warning = ""
    try:
        embedding, note, meta = extract_face_embedding(readable)
        if embedding:
            user["avatarEmbedding"] = embedding
            user["avatarEmbeddingEngine"] = meta.get("engine") or "opencv"
            user["avatarProfileUpdatedAt"] = int(time.time())
            user["avatarAlbumMatches"] = {}
            user["hasFaceProfile"] = True
        else:
            user["hasFaceProfile"] = False
            user["avatarProfileUpdatedAt"] = int(time.time())
            user["avatarAlbumMatches"] = {}
            warning = note or "头像未识别人脸，暂不能推荐我的照片"
        avatar_target = tempfile.NamedTemporaryFile(prefix="picme-avatar-", suffix=".jpg", delete=False)
        avatar_target.close()
        avatar_path = Path(avatar_target.name)
        image = cv2.imread(str(readable), cv2.IMREAD_COLOR)
        if image is None:
            warning = warning or "头像无法生成预览，暂不能展示头像"
            return warning
        height, width = image.shape[:2]
        side = min(width, height)
        left = max(0, (width - side) // 2)
        top = max(0, (height - side) // 2)
        crop = cv2.resize(image[top:top + side, left:left + side], (420, 420), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            warning = warning or "头像无法生成预览，暂不能展示头像"
            return warning
        avatar_path.write_bytes(encoded.tobytes())
        if oss_enabled():
            key = OSS_SERVICE.generateObjectKey("avatars", user_id=user["id"])
            metadata = OSS_SERVICE.uploadFile(avatar_path, key, "image/jpeg", "avatars")
            if metadata:
                user["avatarObjectKey"] = metadata.get("object_key", "")
                user["avatarUrl"] = oss_signed_or_empty(user["avatarObjectKey"]) or metadata.get("oss_url", "")
        else:
            user["avatarObjectKey"] = ""
            user["avatarUrl"] = ""
            warning = warning or "OSS 未配置，头像不会保存，但已用于本地人脸推荐"
        return warning
    finally:
        cleanup_readable()
        if "avatar_path" in locals() and avatar_path:
            avatar_path.unlink(missing_ok=True)


def save_avatar_image(user, source_path):
    readable, cleanup_readable = readable_source_for_path(source_path)
    if not readable:
        return "头像无法读取，暂不能推荐我的照片"
    warning = ""
    try:
        avatar_target = tempfile.NamedTemporaryFile(prefix="picme-avatar-", suffix=".jpg", delete=False)
        avatar_target.close()
        avatar_path = Path(avatar_target.name)
        image = cv2.imread(str(readable), cv2.IMREAD_COLOR)
        if image is None:
            user["faceProfileStatus"] = "failed"
            user["hasFaceProfile"] = False
            user["avatarAlbumMatches"] = {}
            return "头像无法生成预览，暂不能展示头像"
        height, width = image.shape[:2]
        side = min(width, height)
        left = max(0, (width - side) // 2)
        top = max(0, (height - side) // 2)
        crop = cv2.resize(image[top:top + side, left:left + side], (420, 420), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            user["faceProfileStatus"] = "failed"
            user["hasFaceProfile"] = False
            user["avatarAlbumMatches"] = {}
            return "头像无法生成预览，暂不能展示头像"
        avatar_path.write_bytes(encoded.tobytes())
        if oss_enabled():
            key = OSS_SERVICE.generateObjectKey("avatars", user_id=user["id"])
            metadata = OSS_SERVICE.uploadFile(avatar_path, key, "image/jpeg", "avatars")
            if metadata:
                user["avatarObjectKey"] = metadata.get("object_key", "")
                user["avatarUrl"] = oss_signed_or_empty(user["avatarObjectKey"]) or metadata.get("oss_url", "")
        else:
            AVATARS.mkdir(parents=True, exist_ok=True)
            local_avatar = AVATARS / ("%s.jpg" % user["id"])
            shutil.copyfile(avatar_path, local_avatar)
            user["avatarObjectKey"] = ""
            user["avatarUrl"] = "/avatars/%s.jpg" % user["id"]
            warning = "OSS 未配置，头像已保存到本地并进入人脸推荐队列"
        user["hasFaceProfile"] = False
        user["faceProfileStatus"] = "queued"
        user["avatarProfileUpdatedAt"] = int(time.time())
        user["avatarAlbumMatches"] = {}
        return warning
    finally:
        cleanup_readable()
        if "avatar_path" in locals() and avatar_path:
            avatar_path.unlink(missing_ok=True)


FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
OPENCV_MATCH_THRESHOLD = 0.46
INSIGHTFACE_MATCH_THRESHOLD = 0.55
INSIGHTFACE_MIN_DET_SCORE = 0.42
FACE_FOLDER_SAMPLE_LIMIT = 12
MY_PHOTOS_MATCH_ALGORITHM_VERSION = "samples-v1"
# Keep comparable faces for real group photos; remove only tiny, weak, off-edge background detections.
FACE_FILTER_MIN_AREA_RATIO = 0.004
FACE_FILTER_SMALL_AREA_RATIO = 0.008
FACE_FILTER_GROUP_AREA_RATIO = 0.018
FACE_FILTER_MIN_RELATIVE_AREA = 0.28
FACE_FILTER_GROUP_RELATIVE_AREA = 0.45
FACE_FILTER_EDGE_MARGIN = 0.10
FACE_FILTER_OFFCENTER_DISTANCE = 0.35
FACE_FILTER_LOW_SCORE = 0.55
FACE_FILTER_OFFCENTER_SCORE = 0.72
INSIGHTFACE_APP = None
INSIGHTFACE_READY = False
ALBUM_PERMISSION_KEYS = ("upload", "delete", "download", "share")
DEFAULT_ALBUM_PERMISSIONS = {key: True for key in ALBUM_PERMISSION_KEYS}


def normalize_album_permissions(value=None):
    source = value if isinstance(value, dict) else {}
    return {key: bool(source.get(key, True)) for key in ALBUM_PERMISSION_KEYS}


def permissions_json(value=None):
    return json.dumps(normalize_album_permissions(value), ensure_ascii=False, separators=(",", ":"))


def ensure_album_permissions(album):
    if not isinstance(album, dict):
        return dict(DEFAULT_ALBUM_PERMISSIONS)
    permissions = normalize_album_permissions(album.get("permissions"))
    album["permissions"] = permissions
    return permissions


def sqlite_row_permissions(row):
    if not row:
        return normalize_album_permissions()
    try:
        raw = row["permissions_json"]
    except (KeyError, IndexError):
        raw = ""
    try:
        return normalize_album_permissions(json.loads(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return normalize_album_permissions()


def member_public_permissions(row):
    role = row["role"] if row else ""
    if role == "owner":
        return normalize_album_permissions()
    return sqlite_row_permissions(row)


def log_startup_config(service="server"):
    LOGGER.info(
        (
            "service=%s data_dir=%s log_dir=%s face_worker_mode=%s redis=%s "
            "queue=%s oss=%s worker_api=%s worker_token=%s"
        ),
        service,
        DATA,
        LOG_DIR,
        FACE_WORKER_MODE,
        "enabled" if REDIS_CLIENT is not None else "disabled",
        FACE_QUEUE_NAME,
        "enabled" if oss_enabled() else "disabled",
        "configured" if WORKER_API_URL else "disabled",
        "configured" if WORKER_TOKEN else "disabled",
        extra={"event": "startup.config"},
    )


def get_insightface_app():
    global INSIGHTFACE_APP, INSIGHTFACE_READY
    if INSIGHTFACE_READY:
        return INSIGHTFACE_APP
    INSIGHTFACE_READY = True
    if FaceAnalysis is None:
        return None
    try:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(960, 960))
        INSIGHTFACE_APP = app
    except Exception as error:
        LOGGER.warning("error=%s", error, extra={"event": "face.insightface_unavailable"})
        INSIGHTFACE_APP = None
    return INSIGHTFACE_APP


def cosine_distance(a, b):
    left = np.asarray(a, dtype=np.float32)
    right = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return 1.0
    return 1.0 - float(np.dot(left, right) / denom)


def extract_insightface_embedding(image_path):
    app = get_insightface_app()
    if not app:
        return None, "InsightFace 模型不可用", {}
    image = cv2.imread(str(image_path))
    if image is None:
        return None, "图片无法读取", {}
    faces, filter_stats = filter_subject_faces(app.get(image), image.shape)
    if not faces:
        return None, "未检测到人脸", {"engine": "insightface"}

    # Pick the most confident primary face. This demo still assigns one photo
    # to one folder; production can duplicate group photos into multiple people.
    face = max(faces, key=lambda item: (float(getattr(item, "det_score", 0.0)), bbox_area(item.bbox)))
    score = float(getattr(face, "det_score", 0.0))
    if score < INSIGHTFACE_MIN_DET_SCORE:
        return None, "人脸置信度过低", {"engine": "insightface", "score": score}
    embedding = np.asarray(face.normed_embedding, dtype=np.float32)
    norm = float(np.linalg.norm(embedding)) + 1e-6
    return (embedding / norm).round(6).tolist(), "", {
        "engine": "insightface",
        "score": round(score, 4),
        "faces": len(faces),
        "rawFaces": filter_stats.get("raw", len(faces)),
        "filteredFaces": filter_stats.get("filtered", 0),
    }


def bbox_area(bbox):
    return max(0.0, float(bbox[2] - bbox[0])) * max(0.0, float(bbox[3] - bbox[1]))


def face_filter_metrics(face, image_shape, max_area):
    height, width = image_shape[:2]
    x1, y1, x2, y2 = [float(value) for value in face.bbox]
    area = bbox_area(face.bbox)
    image_area = max(float(width * height), 1.0)
    cx = ((x1 + x2) / 2.0) / max(float(width), 1.0)
    cy = ((y1 + y2) / 2.0) / max(float(height), 1.0)
    edge_margin = min(cx, cy, 1.0 - cx, 1.0 - cy)
    center_distance = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
    return {
        "score": float(getattr(face, "det_score", 0.0)),
        "area": area,
        "area_ratio": area / image_area,
        "relative_area": area / max(max_area, 1.0),
        "edge_margin": edge_margin,
        "center_distance": center_distance,
    }


def filter_subject_faces(faces, image_shape):
    faces = [face for face in faces if float(getattr(face, "det_score", 0.0)) >= INSIGHTFACE_MIN_DET_SCORE]
    if not faces:
        return [], {"raw": 0, "kept": 0, "filtered": 0}
    faces = sorted(faces, key=lambda face: bbox_area(face.bbox), reverse=True)
    max_area = bbox_area(faces[0].bbox)
    kept = []
    filtered = []
    for index, face in enumerate(faces):
        metrics = face_filter_metrics(face, image_shape, max_area)
        keep = index == 0
        if not keep:
            group_sized = (
                metrics["area_ratio"] >= FACE_FILTER_GROUP_AREA_RATIO
                or metrics["relative_area"] >= FACE_FILTER_GROUP_RELATIVE_AREA
            )
            tiny_background = (
                metrics["area_ratio"] < FACE_FILTER_MIN_AREA_RATIO
                and metrics["relative_area"] < FACE_FILTER_MIN_RELATIVE_AREA
            )
            small_edge = (
                metrics["area_ratio"] < FACE_FILTER_SMALL_AREA_RATIO
                and metrics["relative_area"] < FACE_FILTER_GROUP_RELATIVE_AREA
                and metrics["edge_margin"] < FACE_FILTER_EDGE_MARGIN
            )
            small_offcenter_low = (
                metrics["area_ratio"] < FACE_FILTER_SMALL_AREA_RATIO
                and metrics["relative_area"] < FACE_FILTER_MIN_RELATIVE_AREA
                and metrics["center_distance"] > FACE_FILTER_OFFCENTER_DISTANCE
                and metrics["score"] < FACE_FILTER_OFFCENTER_SCORE
            )
            low_score_small = (
                metrics["score"] < FACE_FILTER_LOW_SCORE
                and metrics["area_ratio"] < FACE_FILTER_GROUP_AREA_RATIO
                and metrics["relative_area"] < FACE_FILTER_GROUP_RELATIVE_AREA
            )
            keep = group_sized or not (tiny_background or small_edge or small_offcenter_low or low_score_small)
        (kept if keep else filtered).append((face, metrics))
    if filtered:
        LOGGER.info(
            "raw=%d kept=%d filtered=%d",
            len(faces),
            len(kept),
            len(filtered),
            extra={"event": "face.filter"},
        )
    return [item[0] for item in kept], {"raw": len(faces), "kept": len(kept), "filtered": len(filtered)}


def extract_opencv_embedding(image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        return None, "图片无法读取", {}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scan = gray
    max_side = max(gray.shape)
    scale = 1.0
    if max_side > 1200:
        scale = 1200.0 / max_side
        scan = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    faces = FACE_CASCADE.detectMultiScale(
        scan,
        scaleFactor=1.05,
        minNeighbors=5,
        minSize=(32, 32),
    )
    if len(faces) == 0:
        return None, "未检测到人脸", {"engine": "opencv"}

    candidates = []
    image_area = scan.shape[0] * scan.shape[1]
    for sx, sy, sw, sh in faces:
        face_ratio = (sw * sh) / max(image_area, 1)
        if face_ratio < 0.0018:
            continue
        face_region = scan[sy : sy + sh, sx : sx + sw]
        upper_face = face_region[: int(sh * 0.72), :]
        eyes = EYE_CASCADE.detectMultiScale(
            upper_face,
            scaleFactor=1.06,
            minNeighbors=3,
            minSize=(6, 6),
        )
        # Distant faces often expose only one eye reliably. Large face boxes are
        # accepted with a lighter check, while small boxes still need eye support.
        if len(eyes) >= 1 or face_ratio >= 0.018:
            x = int(round(sx / scale))
            y = int(round(sy / scale))
            w = int(round(sw / scale))
            h = int(round(sh / scale))
            candidates.append((x, y, w, h, len(eyes), face_ratio))

    if not candidates:
        return None, "未通过人脸五官校验", {"engine": "opencv"}

    x, y, w, h, _, _ = max(candidates, key=lambda item: (item[4], item[2] * item[3]))
    pad = int(max(w, h) * 0.18)
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(gray.shape[1], x + w + pad)
    bottom = min(gray.shape[0], y + h + pad)
    face = gray[top:bottom, left:right]
    face = cv2.resize(face, (48, 48), interpolation=cv2.INTER_AREA)
    face = cv2.equalizeHist(face)
    vector = face.astype(np.float32).reshape(-1)
    vector = (vector - float(vector.mean())) / (float(vector.std()) + 1e-6)
    norm = float(np.linalg.norm(vector)) + 1e-6
    return (vector / norm).round(6).tolist(), "", {"engine": "opencv"}


def extract_face_embedding(image_path):
    embedding, note, meta = extract_insightface_embedding(image_path)
    if embedding:
        return embedding, note, meta
    fallback_embedding, fallback_note, fallback_meta = extract_opencv_embedding(image_path)
    if fallback_embedding:
        return fallback_embedding, fallback_note, fallback_meta
    return embedding, note, meta


def choose_face_folder(album, embedding, engine):
    if not embedding:
        return None

    best_folder = None
    best_distance = 999.0
    for folder in album.get("folders", []):
        centroid = folder.get("embedding")
        if not centroid or folder.get("embeddingEngine") != engine:
            continue
        distance = cosine_distance(embedding, centroid)
        if distance < best_distance:
            best_distance = distance
            best_folder = folder

    threshold = INSIGHTFACE_MATCH_THRESHOLD if engine == "insightface" else OPENCV_MATCH_THRESHOLD
    if best_folder and best_distance <= threshold:
        return best_folder
    return None


def update_folder_embedding(folder, embedding, engine):
    samples = folder.get("embeddingSamples")
    if not isinstance(samples, list):
        samples = []
    samples.append(embedding)
    folder["embeddingSamples"] = samples[-FACE_FOLDER_SAMPLE_LIMIT:]

    current = folder.get("embedding")
    count = int(folder.get("embeddingCount") or 0)
    if not current or count <= 0:
        folder["embedding"] = embedding
        folder["embeddingEngine"] = engine
        folder["embeddingCount"] = 1
        folder["embeddingUpdatedAt"] = int(time.time())
        return
    updated = ((np.asarray(current, dtype=np.float32) * count) + np.asarray(embedding, dtype=np.float32)) / (count + 1)
    norm = float(np.linalg.norm(updated)) + 1e-6
    folder["embedding"] = (updated / norm).round(6).tolist()
    folder["embeddingEngine"] = engine
    folder["embeddingCount"] = count + 1
    folder["embeddingUpdatedAt"] = int(time.time())


def create_folder(album, name, embedding=None, folder_id=None, engine=None):
    folders = album.setdefault("folders", [])
    folder = {
        "id": folder_id or slugify(name),
        "name": name,
        "createdAt": int(time.time()),
    }
    if embedding:
        folder["embedding"] = embedding
        folder["embeddingEngine"] = engine or "opencv"
        folder["embeddingCount"] = 1
        folder["embeddingSamples"] = [embedding]
        folder["embeddingUpdatedAt"] = int(time.time())
    existing = {item["id"] for item in folders}
    base = folder["id"]
    index = 2
    while folder["id"] in existing:
        folder["id"] = "%s-%d" % (base, index)
        index += 1
    folders.append(folder)
    LOGGER.info(
        "album_id=%s folder_id=%s name=%s engine=%s",
        album.get("id", ""),
        folder["id"],
        folder["name"],
        engine or "",
        extra={"event": "folder.create"},
    )
    return folder


def get_no_face_folder(album):
    folder = next((item for item in album.get("folders", []) if item["id"] == "no-face" or item["name"] in {"未识别人脸", "其他"}), None)
    if folder:
        folder["name"] = "其他"
        return folder
    return create_folder(album, "其他", folder_id="no-face")


def get_group_folder(album):
    folder = next((item for item in album.get("folders", []) if item["id"] == "group-photo" or item["name"] == "合照"), None)
    return folder or create_folder(album, "合照", folder_id="group-photo")


def get_pending_folder(album):
    folder = next((item for item in album.get("folders", []) if item["id"] == "pending"), None)
    return folder or create_folder(album, "等待识别", folder_id="pending")


def photo_folder_ids(photo):
    ids = photo.get("folderIds")
    if isinstance(ids, list) and ids:
        return ids
    folder_id = photo.get("folderId")
    return [folder_id] if folder_id else []


def apply_photo_folders(photo, folders, classification):
    previous = ",".join(photo_folder_ids(photo))
    unique = []
    seen = set()
    for folder in folders:
        if folder["id"] in seen:
            continue
        seen.add(folder["id"])
        unique.append(folder)
    photo["folderIds"] = [folder["id"] for folder in unique]
    photo["folderNames"] = [folder["name"] for folder in unique]
    primary = unique[0] if unique else None
    photo["folderId"] = primary["id"] if primary else ""
    photo["folderName"] = primary["name"] if primary else ""
    photo["classification"] = classification
    current = ",".join(photo_folder_ids(photo))
    if previous != current:
        LOGGER.info(
            "photo_id=%s from=%s to=%s classification=%s",
            photo.get("id", ""),
            previous,
            current,
            classification,
            extra={"event": "photo.classification_change"},
        )


def sync_photo_folder_names(album):
    folders_by_id = {folder["id"]: folder for folder in album.get("folders", [])}
    for photo in album.get("photos", []):
        folders = [folders_by_id[folder_id] for folder_id in photo_folder_ids(photo) if folder_id in folders_by_id]
        if not folders and photo.get("folderId") in folders_by_id:
            folders = [folders_by_id[photo["folderId"]]]
        classification = photo.get("classification") or ""
        apply_photo_folders(photo, folders, classification)


def rename_folder(album, folder_id, name):
    new_name = (name or "").strip()[:40]
    if not new_name:
        return None, "名称不能为空"
    folder = next((item for item in album.get("folders", []) if item["id"] == folder_id), None)
    if not folder:
        return None, "文件夹不存在"
    folder["name"] = new_name
    sync_photo_folder_names(album)
    return folder, ""


def rename_album(album, name):
    new_name = (name or "").strip()[:80]
    if not new_name:
        return "名称不能为空"
    album["name"] = new_name
    return ""


def prune_empty_folders(album):
    used = set()
    for photo in album.get("photos", []):
        used.update(photo_folder_ids(photo))
    album["folders"] = [folder for folder in album.get("folders", []) if folder["id"] in used]
    sync_photo_folder_names(album)


def delete_oss_photo_resources(photo):
    keys = {
        original_object_key(photo),
        live_video_object_key(photo),
        preview_object_key(photo),
        thumb_object_key(photo),
        face_object_key(photo),
    }
    for key in keys:
        if key:
            OSS_SERVICE.deleteFile(key)


def remove_photo(album, photo_id):
    photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
    if not photo:
        return None, "照片不存在"
    album["photos"] = [item for item in album.get("photos", []) if item["id"] != photo_id]
    still_used = any(item.get("storedName") == photo.get("storedName") for item in album.get("photos", []))
    if not still_used:
        delete_oss_photo_resources(photo)
        source = UPLOADS / album["id"] / photo["storedName"]
        if source.exists():
            source.unlink()
        remove_thumbnails(album["id"], photo["storedName"])
        remove_preview(album["id"], photo["storedName"])
    video_name = photo.get("liveVideoStoredName")
    if video_name and not any(item.get("liveVideoStoredName") == video_name for item in album.get("photos", [])):
        OSS_SERVICE.deleteFile(live_video_object_key(photo))
        video_source = UPLOADS / album["id"] / video_name
        if video_source.exists():
            video_source.unlink()
    prune_empty_folders(album)
    LOGGER.info("album_id=%s photo_id=%s", album.get("id", ""), photo_id, extra={"event": "photo.delete"})
    return photo, ""


def remove_folder(album, folder_id):
    folder = next((item for item in album.get("folders", []) if item["id"] == folder_id), None)
    if not folder:
        return None, "文件夹不存在"

    folders_by_id = {item["id"]: item for item in album.get("folders", [])}
    removed_photos = []
    kept_photos = []
    deleted_count = 0
    unlinked_count = 0
    logical_removed_count = 0

    for photo in album.get("photos", []):
        ids = photo_folder_ids(photo)
        if folder_id not in ids:
            kept_photos.append(photo)
            continue

        remaining_ids = [item for item in ids if item != folder_id]
        remaining_folders = [folders_by_id[item] for item in remaining_ids if item in folders_by_id]
        if remaining_folders:
            apply_photo_folders(photo, remaining_folders, "已从“%s”移除" % folder["name"])
            kept_photos.append(photo)
            logical_removed_count += 1
            continue

        removed_photos.append(photo)
        deleted_count += 1

    album["photos"] = kept_photos
    for photo in removed_photos:
        still_used = any(item.get("storedName") == photo.get("storedName") for item in album.get("photos", []))
        if still_used:
            continue
        delete_oss_photo_resources(photo)
        source = UPLOADS / album["id"] / photo["storedName"]
        if source.exists():
            source.unlink()
            unlinked_count += 1
        remove_thumbnails(album["id"], photo["storedName"])
        remove_preview(album["id"], photo["storedName"])
        video_name = photo.get("liveVideoStoredName")
        if video_name:
            video_source = UPLOADS / album["id"] / video_name
            if video_source.exists():
                video_source.unlink()

    album["folders"] = [item for item in album.get("folders", []) if item["id"] != folder_id]
    prune_empty_folders(album)
    LOGGER.info(
        "album_id=%s folder_id=%s deleted_photos=%d logical_removed=%d",
        album.get("id", ""),
        folder_id,
        deleted_count,
        logical_removed_count,
        extra={"event": "folder.delete"},
    )
    return {
        "folder": folder,
        "deletedPhotos": deleted_count,
        "deletedFiles": unlinked_count,
        "logicalRemovedPhotos": logical_removed_count,
    }, ""


def remove_album_files(album_id, album=None):
    if album:
        for photo in album.get("photos", []):
            delete_oss_photo_resources(photo)
    album_dir = UPLOADS / album_id
    if album_dir.exists():
        shutil.rmtree(album_dir)
    remove_thumbnails(album_id)
    remove_preview(album_id)
    for zip_path in DATA.glob("%s-*.zip" % album_id):
        if zip_path.exists():
            zip_path.unlink()


def merge_embeddings(target, source):
    if target["id"] == "no-face":
        target.pop("embedding", None)
        target.pop("embeddingCount", None)
        target.pop("embeddingEngine", None)
        target.pop("embeddingUpdatedAt", None)
        return
    source_embedding = source.get("embedding")
    if not source_embedding or target.get("embeddingEngine") != source.get("embeddingEngine"):
        return
    target_embedding = target.get("embedding")
    source_count = int(source.get("embeddingCount") or 1)
    target_count = int(target.get("embeddingCount") or 0)
    if not target_embedding or target_count <= 0:
        target["embedding"] = source_embedding
        target["embeddingCount"] = source_count
        target["embeddingEngine"] = source.get("embeddingEngine")
        target["embeddingUpdatedAt"] = int(time.time())
        return
    merged = (
        (np.asarray(target_embedding, dtype=np.float32) * target_count)
        + (np.asarray(source_embedding, dtype=np.float32) * source_count)
    ) / (target_count + source_count)
    norm = float(np.linalg.norm(merged)) + 1e-6
    target["embedding"] = (merged / norm).round(6).tolist()
    target["embeddingCount"] = target_count + source_count
    target["embeddingUpdatedAt"] = int(time.time())


def merge_folder(album, source_id, target_id):
    if source_id == target_id:
        return None, "请选择不同的目标文件夹"
    all_folders = album.get("folders", [])
    source = next((item for item in all_folders if item["id"] == source_id), None)
    target = next((item for item in all_folders if item["id"] == target_id), None)
    if not source:
        return None, "源文件夹不存在"
    if not target:
        return None, "目标文件夹不存在"

    for photo in album.get("photos", []):
        ids = photo_folder_ids(photo)
        if source["id"] in ids:
            next_folders = []
            for folder_id in ids:
                if folder_id == source["id"]:
                    if target["id"] not in [item["id"] for item in next_folders]:
                        next_folders.append(target)
                else:
                    folder = next((item for item in next_folders if item["id"] == folder_id), None)
                    if not folder:
                        folder = next((item for item in album.get("folders", []) if item["id"] == folder_id), None)
                    if folder:
                        next_folders.append(folder)
            apply_photo_folders(photo, next_folders, "人工纠错")
    merge_embeddings(target, source)
    album["folders"] = [item for item in all_folders if item["id"] != source["id"]]
    return target, ""


def move_photo(album, photo_id, target_id):
    photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
    if not photo:
        return None, "照片不存在"
    if target_id == "no-face":
        target = get_no_face_folder(album)
    else:
        target = next((item for item in album.get("folders", []) if item["id"] == target_id), None)
    if not target:
        return None, "目标文件夹不存在"
    apply_photo_folders(photo, [target], "人工移动")
    return photo, ""


def reclassify_photo(album, photo_id):
    photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
    if not photo:
        return None, "照片不存在"
    image_path, cleanup = materialize_photo_source(album["id"], photo)
    if not image_path:
        return None, "源文件不存在"
    try:
        readable, cleanup_readable = readable_source_for_path(image_path)
        if not readable:
            return None, "图片无法读取"
        try:
            folders, note = classify_photo(album, readable)
        finally:
            cleanup_readable()
    finally:
        cleanup()
    apply_photo_folders(photo, folders, "重新识别：%s" % note)
    return photo, ""


def reanalyze_album(album):
    previous_names = {folder["id"]: folder.get("name") for folder in album.get("folders", [])}
    photos = sorted(album.get("photos", []), key=lambda item: item.get("createdAt", 0))
    album["folders"] = []
    for photo in photos:
        image_path, cleanup = materialize_photo_source(album["id"], photo)
        readable, cleanup_readable = readable_source_for_path(image_path) if image_path else (None, lambda: None)
        if readable:
            try:
                folders, note = classify_photo(album, readable)
            finally:
                cleanup_readable()
        else:
            folders, note = [get_no_face_folder(album)], "源文件不存在"
        cleanup()
        apply_photo_folders(photo, folders, "全量重分析：%s" % note)
    for folder in album.get("folders", []):
        previous_name = previous_names.get(folder["id"])
        if previous_name:
            folder["name"] = previous_name
    sync_photo_folder_names(album)
    return album


def use_redis_queue():
    return REDIS_CLIENT is not None and FACE_WORKER_MODE == "redis"


def use_remote_worker():
    return FACE_WORKER_MODE == "remote"


def face_job_key(job):
    if isinstance(job, tuple):
        return "%s:%s:%s" % (FACE_JOB_PHOTO_ANALYZE, job[0], job[1])
    job_type = job.get("type") or job.get("taskType") or FACE_JOB_PHOTO_ANALYZE
    if job_type == FACE_JOB_PHOTO_ANALYZE:
        return "%s:%s:%s" % (job_type, job.get("albumId", ""), job.get("photoId", ""))
    if job_type == FACE_JOB_AVATAR_ANALYZE:
        return "%s:%s" % (job_type, job.get("userId", ""))
    if job_type == FACE_JOB_ALBUM_MATCH:
        return "%s:%s:%s" % (job_type, job.get("albumId", ""), job.get("userId", ""))
    return "%s:%s" % (job_type, job.get("taskId") or uuid.uuid4().hex)


def push_face_job(album_id, photo_id):
    push_face_task({"type": FACE_JOB_PHOTO_ANALYZE, "albumId": album_id, "photoId": photo_id})


def push_face_task(job):
    payload = json.dumps(job, ensure_ascii=False)
    if use_redis_queue():
        REDIS_CLIENT.lpush(FACE_QUEUE_NAME, payload)
        LOGGER.info("job=%s queue=%s", face_job_key(job), FACE_QUEUE_NAME, extra={"event": "redis.enqueue"})
    else:
        JOB_QUEUE.put(job)
        LOGGER.info("job=%s", face_job_key(job), extra={"event": "queue.enqueue"})


def pop_face_job(timeout=3):
    if use_redis_queue():
        item = REDIS_CLIENT.brpop(FACE_QUEUE_NAME, timeout=max(int(timeout), 1))
        if not item:
            return None
        try:
            payload = json.loads(item[1])
            LOGGER.info(
                "album_id=%s photo_id=%s queue=%s",
                payload.get("albumId"),
                payload.get("photoId"),
                FACE_QUEUE_NAME,
                extra={"event": "redis.dequeue"},
            )
            if "type" not in payload and "taskType" not in payload:
                payload["type"] = FACE_JOB_PHOTO_ANALYZE
            return payload
        except Exception as error:
            LOGGER.warning("error=%s", error, extra={"event": "redis.dequeue_invalid"})
            return None
    try:
        job = JOB_QUEUE.get(timeout=max(float(timeout), 0.1))
        LOGGER.info("job=%s", face_job_key(job), extra={"event": "queue.dequeue"})
        return job
    except queue.Empty:
        return None


def enqueue_photo_job(album_id, photo_id):
    if use_remote_worker():
        return
    enqueue_face_task({"type": FACE_JOB_PHOTO_ANALYZE, "albumId": album_id, "photoId": photo_id})


def enqueue_face_task(job):
    if use_remote_worker():
        return
    key = face_job_key(job)
    if use_redis_queue():
        added = REDIS_CLIENT.sadd(FACE_QUEUE_SET_NAME, key)
        if not added:
            LOGGER.info("job=%s", key, extra={"event": "queue.duplicate"})
            return
    else:
        with LOCK:
            if key in QUEUED_FACE_JOBS:
                LOGGER.info("job=%s", key, extra={"event": "queue.duplicate"})
                return
            QUEUED_FACE_JOBS.add(key)
    push_face_task(job)


def enqueue_avatar_job(user_id):
    enqueue_face_task({"type": FACE_JOB_AVATAR_ANALYZE, "userId": user_id})


def enqueue_album_match_job(album_id, user_id):
    enqueue_face_task({"type": FACE_JOB_ALBUM_MATCH, "albumId": album_id, "userId": user_id})


def enqueue_album_match_jobs_for_album(album_id):
    for user_id in album_member_user_ids(album_id):
        enqueue_album_match_job(album_id, user_id)


def enqueue_album_match_jobs_for_user(user_id):
    for album_id in user_album_ids(user_id):
        enqueue_album_match_job(album_id, user_id)


def enqueue_pending_jobs():
    pending = []
    with LOCK:
        db = load_db()
        for album in db.get("albums", []):
            for photo in album.get("photos", []):
                if photo.get("status") in {"queued", "preparing", "processing"}:
                    photo["status"] = "queued"
                    pending.append((album["id"], photo["id"]))
        save_db(db)
    for album_id, photo_id in pending:
        enqueue_photo_job(album_id, photo_id)


def process_photo_job(album_id, photo_id):
    job_started_at = time.perf_counter()
    LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.process_start"})
    cleanup_source = lambda: None
    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            cleanup_source()
            LOGGER.warning("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.album_missing"})
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            cleanup_source()
            LOGGER.warning("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.photo_missing"})
            return
        photo["status"] = "preparing"
        photo["classification"] = "正在生成预览图"
        sync_photo_folder_names(album)
        save_db(db)

    source, cleanup_source = materialize_photo_source(album_id, photo)
    derivative_updates = {}
    try:
        derivative_started_at = time.perf_counter()
        if not source:
            raise ValueError("图片源文件不存在")
        generate_preview_for_photo(album_id, photo, source)
        generate_thumbnail_for_photo(album_id, photo, source)
        derivative_updates = {
            key: value for key, value in photo.items()
            if key.startswith(("preview", "thumb")) or key.startswith(("preview_", "thumb_"))
        }
        LOGGER.info(
            "照片预览与缩略图生成完成：album_id=%s photo_id=%s 耗时=%sms",
            album_id,
            photo_id,
            elapsed_ms(derivative_started_at),
            extra={"event": "derivatives.complete"},
        )
    except Exception as error:
        LOGGER.warning("album_id=%s photo_id=%s error=%s", album_id, photo_id, error, extra={"event": "derivatives.failed"})
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if album:
                target = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
                if target:
                    target["classification"] = "预览图生成失败：%s" % error
                    save_db(db)

    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            cleanup_source()
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            cleanup_source()
            return
        photo["status"] = "processing"
        photo["classification"] = "正在识别人脸"
        photo.update(derivative_updates)
        sync_photo_folder_names(album)
        save_db(db)

    try:
        analysis_started_at = time.perf_counter()
        readable, cleanup_readable = readable_source_for_path(source) if source else (None, lambda: None)
        if not readable:
            raise ValueError("图片无法生成预览图")
        try:
            analysis = analyze_photo_faces(readable)
        finally:
            cleanup_readable()
        LOGGER.info(
            "照片识别人脸阶段完成：album_id=%s photo_id=%s status=%s 耗时=%sms",
            album_id,
            photo_id,
            analysis.get("status"),
            elapsed_ms(analysis_started_at),
            extra={"event": "face.analysis_stage_complete"},
        )
    except Exception as error:
        analysis = {"status": "failed", "note": str(error)}
        LOGGER.exception("album_id=%s photo_id=%s error=%s", album_id, photo_id, error, extra={"event": "face.analysis_failed"})

    with LOCK:
        classify_started_at = time.perf_counter()
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            cleanup_source()
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            cleanup_source()
            return
        apply_face_analysis(album, photo, analysis)
        face_user_id = next((item for item in photo_folder_ids(photo) if item not in {"group-photo", "no-face", "pending"}), album_id)
        try:
            if source:
                generate_face_thumbnail_for_photo(album_id, photo, source, face_user_id)
        except Exception as error:
            LOGGER.warning("album_id=%s photo_id=%s error=%s", album_id, photo_id, error, extra={"event": "face.thumb_failed"})
        prune_empty_folders(album)
        save_db(db)
        LOGGER.info(
            "照片分类入库完成：album_id=%s photo_id=%s status=%s folders=%s 耗时=%sms",
            album_id,
            photo_id,
            photo.get("status"),
            ",".join(photo_folder_ids(photo)),
            elapsed_ms(classify_started_at),
            extra={"event": "face.classify_complete"},
        )
    cleanup_source()
    LOGGER.info(
        "照片后台处理完成：album_id=%s photo_id=%s status=%s 总耗时=%sms",
        album_id,
        photo_id,
        analysis.get("status"),
        elapsed_ms(job_started_at),
        extra={"event": "worker.process_complete"},
    )
    enqueue_album_match_jobs_for_album(album_id)


def process_avatar_job(user_id):
    started_at = time.perf_counter()
    LOGGER.info("user_id=%s", user_id, extra={"event": "worker.avatar_start"})
    with LOCK:
        db = load_db()
        user = find_user_by_id(db, user_id)
        if not user:
            LOGGER.warning("user_id=%s", user_id, extra={"event": "worker.avatar_user_missing"})
            return
        user["faceProfileStatus"] = "processing"
        upsert_user(db, user)
        save_db(db)
    source, cleanup_source = materialize_avatar_source(user)
    try:
        if not source:
            result = {"status": "failed", "note": "头像源文件不存在"}
        else:
            readable, cleanup_readable = readable_source_for_path(source)
            try:
                if not readable:
                    result = {"status": "failed", "note": "头像无法读取"}
                else:
                    analysis_started_at = time.perf_counter()
                    embedding, note, meta = extract_face_embedding(readable)
                    LOGGER.info(
                        "头像人脸识别完成：user_id=%s status=%s engine=%s 耗时=%sms",
                        user_id,
                        "ready" if embedding else "failed",
                        meta.get("engine") if meta else "",
                        elapsed_ms(analysis_started_at),
                        extra={"event": "worker.avatar_analysis_complete"},
                    )
                    result = {
                        "status": "ready" if embedding else "failed",
                        "embedding": embedding,
                        "engine": meta.get("engine") if meta else "",
                        "note": note or "",
                    }
            finally:
                cleanup_readable()
    finally:
        cleanup_source()
    complete_avatar_analysis(user_id, result)
    LOGGER.info(
        "头像后台识别完成：user_id=%s status=%s engine=%s 总耗时=%sms",
        user_id,
        result.get("status"),
        result.get("engine", ""),
        elapsed_ms(started_at),
        extra={"event": "worker.avatar_complete"},
    )


def complete_avatar_analysis(user_id, result):
    started_at = time.perf_counter()
    now = int(time.time())
    status = result.get("status")
    with LOCK:
        db = load_db()
        user = find_user_by_id(db, user_id)
        if not user:
            return False
        embedding = result.get("embedding")
        if result.get("status") == "ready" and embedding:
            user["avatarEmbedding"] = embedding
            user["avatarEmbeddingEngine"] = result.get("engine") or "opencv"
            user["avatarProfileUpdatedAt"] = now
            user["avatarAlbumMatches"] = {}
            user["hasFaceProfile"] = True
            user["faceProfileStatus"] = "ready"
            user.pop("faceProfileError", None)
        else:
            user["hasFaceProfile"] = False
            user["avatarProfileUpdatedAt"] = now
            user["avatarAlbumMatches"] = {}
            user["faceProfileStatus"] = "failed"
            user["faceProfileError"] = result.get("note") or "头像未识别人脸，暂不能推荐我的照片"
        upsert_user(db, user)
        save_db(db)
    create_notification(
        user_id,
        "face.avatar_%s" % ("ready" if status == "ready" and result.get("embedding") else "failed"),
        "头像识别%s" % ("完成" if status == "ready" and result.get("embedding") else "失败"),
        "头像已可用于查找我的照片" if status == "ready" and result.get("embedding") else user.get("faceProfileError", "头像未识别人脸，暂不能推荐我的照片"),
        data={"status": user.get("faceProfileStatus"), "hasFaceProfile": bool(user.get("hasFaceProfile"))},
    )
    LOGGER.info(
        "头像识别结果已入库：user_id=%s status=%s has_face=%s 耗时=%sms",
        user_id,
        result.get("status"),
        bool(result.get("embedding")),
        elapsed_ms(started_at),
        extra={"event": "worker.avatar_saved"},
    )
    enqueue_album_match_jobs_for_user(user_id)
    return True


def process_album_match_job(album_id, user_id):
    started_at = time.perf_counter()
    LOGGER.info("album_id=%s user_id=%s", album_id, user_id, extra={"event": "worker.match_start"})
    previous_match = None
    match = None
    album = None
    user = None
    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        user = find_user_by_id(db, user_id)
        if not album or not user:
            LOGGER.warning("album_id=%s user_id=%s", album_id, user_id, extra={"event": "worker.match_missing"})
            return
        match = compute_user_album_match(album, user)
        matches = user.setdefault("avatarAlbumMatches", {})
        previous_match = matches.get(album_id)
        matches[album_id] = match
        upsert_user(db, user)
        save_db(db)
    notify_user_album_match_if_needed(user, album, previous_match, match)
    LOGGER.info(
        "头像与相册关联匹配完成：album_id=%s user_id=%s matched=%s folder_id=%s 耗时=%sms",
        album_id,
        user_id,
        match.get("matched"),
        match.get("folderId", ""),
        elapsed_ms(started_at),
        extra={"event": "worker.match_complete"},
    )


def process_face_task(job):
    if isinstance(job, tuple):
        job = {"type": FACE_JOB_PHOTO_ANALYZE, "albumId": job[0], "photoId": job[1]}
    job_type = job.get("type") or job.get("taskType") or FACE_JOB_PHOTO_ANALYZE
    if job_type == FACE_JOB_PHOTO_ANALYZE:
        return process_photo_job(job.get("albumId"), job.get("photoId"))
    if job_type == FACE_JOB_AVATAR_ANALYZE:
        return process_avatar_job(job.get("userId"))
    if job_type == FACE_JOB_ALBUM_MATCH:
        return process_album_match_job(job.get("albumId"), job.get("userId"))
    LOGGER.warning("job=%s", job, extra={"event": "worker.unknown_job"})


def photo_worker():
    while True:
        job = pop_face_job(timeout=3)
        if not job:
            continue
        key = face_job_key(job)
        try:
            process_face_task(job)
        finally:
            if use_redis_queue():
                REDIS_CLIENT.srem(FACE_QUEUE_SET_NAME, key)
                LOGGER.info("job=%s", key, extra={"event": "redis.complete"})
            else:
                with LOCK:
                    QUEUED_FACE_JOBS.discard(key)
                JOB_QUEUE.task_done()
                LOGGER.info("job=%s", key, extra={"event": "queue.complete"})


def assign_face_folder(album, embedding, engine):
    folder = choose_face_folder(album, embedding, engine)
    if folder:
        update_folder_embedding(folder, embedding, engine)
        return folder, "匹配到已有人物（%s）" % engine

    person_index = 1 + len([item for item in album.get("folders", []) if item["id"] not in {"no-face", "group-photo"}])
    folder = create_folder(album, "人物 %d" % person_index, embedding, engine=engine)
    return folder, "创建新人物（%s）" % engine


def classify_photo(album, image_path):
    app = get_insightface_app()
    if app:
        image = cv2.imread(str(image_path))
        if image is None:
            return [get_no_face_folder(album)], "图片无法读取"
        faces, filter_stats = filter_subject_faces(app.get(image), image.shape)
        if not faces:
            return [get_no_face_folder(album)], "未检测到人脸"

        faces = sorted(faces, key=lambda face: bbox_area(face.bbox), reverse=True)
        person_folders = []
        notes = []
        for face in faces:
            embedding = np.asarray(face.normed_embedding, dtype=np.float32)
            norm = float(np.linalg.norm(embedding)) + 1e-6
            folder, note = assign_face_folder(album, (embedding / norm).round(6).tolist(), "insightface")
            if folder["id"] not in [item["id"] for item in person_folders]:
                person_folders.append(folder)
            notes.append(note)
        if len(faces) > 1:
            return [get_group_folder(album)] + person_folders, "合照：识别到 %d 张人脸，%d 个人物文件夹" % (len(faces), len(person_folders))
        if filter_stats.get("filtered"):
            return person_folders, "已过滤背景人脸，%s" % (notes[0] if notes else "匹配到已有人物（insightface）")
        return person_folders, notes[0] if notes else "匹配到已有人物（insightface）"

    embedding, note, meta = extract_opencv_embedding(image_path)
    if not embedding:
        return [get_no_face_folder(album)], note
    folder, folder_note = assign_face_folder(album, embedding, meta.get("engine") or "opencv")
    return [folder], folder_note


def analyze_photo_faces(image_path):
    started_at = time.perf_counter()
    app = get_insightface_app()
    if app:
        image = cv2.imread(str(image_path))
        if image is None:
            return {"status": "failed", "note": "图片无法读取"}
        faces, filter_stats = filter_subject_faces(app.get(image), image.shape)
        if not faces:
            LOGGER.info(
                "照片人脸识别完成：path=%s status=no_face raw_faces=%s filtered_faces=%s 耗时=%sms",
                Path(image_path).name,
                filter_stats.get("raw", 0),
                filter_stats.get("filtered", 0),
                elapsed_ms(started_at),
                extra={"event": "face.analysis_result"},
            )
            return {"status": "no_face", "note": "未检测到人脸", "engine": "insightface", "faces": []}
        faces = sorted(faces, key=lambda face: bbox_area(face.bbox), reverse=True)
        embeddings = []
        for face in faces:
            embedding = np.asarray(face.normed_embedding, dtype=np.float32)
            norm = float(np.linalg.norm(embedding)) + 1e-6
            embeddings.append((embedding / norm).round(6).tolist())
        result = {
            "status": "ready",
            "engine": "insightface",
            "faceCount": len(embeddings),
            "rawFaceCount": filter_stats.get("raw", len(embeddings)),
            "filteredFaceCount": filter_stats.get("filtered", 0),
            "embeddings": embeddings,
            "note": "",
        }
        LOGGER.info(
            "照片人脸识别完成：path=%s status=ready face_count=%d raw_faces=%s filtered_faces=%s 耗时=%sms",
            Path(image_path).name,
            result["faceCount"],
            result["rawFaceCount"],
            result["filteredFaceCount"],
            elapsed_ms(started_at),
            extra={"event": "face.analysis_result"},
        )
        return result

    embedding, note, meta = extract_opencv_embedding(image_path)
    if not embedding:
        LOGGER.info(
            "照片人脸识别完成：path=%s status=no_face note=%s 耗时=%sms",
            Path(image_path).name,
            note,
            elapsed_ms(started_at),
            extra={"event": "face.analysis_result"},
        )
        return {"status": "no_face", "note": note, "engine": meta.get("engine") or "opencv", "faces": []}
    result = {
        "status": "ready",
        "engine": meta.get("engine") or "opencv",
        "faceCount": 1,
        "embeddings": [embedding],
        "note": "",
    }
    LOGGER.info(
        "照片人脸识别完成：path=%s status=ready engine=%s face_count=1 耗时=%sms",
        Path(image_path).name,
        result["engine"],
        elapsed_ms(started_at),
        extra={"event": "face.analysis_result"},
    )
    return result


def apply_face_analysis(album, photo, analysis):
    status = analysis.get("status")
    if status == "failed":
        photo["status"] = "failed"
        apply_photo_folders(photo, [get_no_face_folder(album)], "识别失败：%s" % (analysis.get("note") or "未知错误"))
        return
    if status == "no_face":
        photo["status"] = "ready"
        apply_photo_folders(photo, [get_no_face_folder(album)], analysis.get("note") or "未检测到人脸")
        return

    embeddings = analysis.get("embeddings") or []
    engine = analysis.get("engine") or "opencv"
    if not embeddings:
        photo["status"] = "ready"
        apply_photo_folders(photo, [get_no_face_folder(album)], analysis.get("note") or "未检测到人脸")
        return

    person_folders = []
    notes = []
    for embedding in embeddings:
        folder, note = assign_face_folder(album, embedding, engine)
        if folder["id"] not in [item["id"] for item in person_folders]:
            person_folders.append(folder)
        notes.append(note)
    photo["status"] = "ready"
    if len(embeddings) > 1:
        folders = [get_group_folder(album)] + person_folders
        apply_photo_folders(photo, folders, "合照：识别到 %d 张人脸，%d 个人物文件夹" % (len(embeddings), len(person_folders)))
    else:
        note = notes[0] if notes else "匹配到已有人物（%s）" % engine
        if int(analysis.get("filteredFaceCount") or 0) > 0:
            note = "已过滤背景人脸，%s" % note
        apply_photo_folders(photo, person_folders, note)
    LOGGER.info(
        "album_id=%s photo_id=%s status=%s engine=%s faces=%d raw_faces=%s filtered_faces=%s folders=%s",
        album.get("id", ""),
        photo.get("id", ""),
        photo.get("status", ""),
        engine,
        len(embeddings),
        analysis.get("rawFaceCount", len(embeddings)),
        analysis.get("filteredFaceCount", 0),
        ",".join(photo_folder_ids(photo)),
        extra={"event": "face.apply_result"},
    )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SharedAlbumDemo/0.1"

    def log_message(self, fmt, *args):
        LOGGER.info(
            "client=%s %s",
            self.address_string(),
            fmt % args,
            extra={"event": "http.access"},
        )

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status)

    def bearer_token(self):
        value = self.headers.get("Authorization") or ""
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return ""

    def current_user(self):
        if hasattr(self, "_current_user"):
            return self._current_user
        self._current_user = user_for_token(self.bearer_token())
        return self._current_user

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_error_json("请先登录", 401)
            return None
        return user

    def require_album_member(self, album_id):
        user = self.require_user()
        if not user:
            return None
        if not album_member_role(album_id, user.get("id")):
            self.send_error_json("你还没有加入这个相册", 403)
            return None
        return user

    def require_album_admin(self, album_id):
        user = self.require_album_member(album_id)
        if not user:
            return None
        role = album_member_role(album_id, user.get("id"))
        if role not in {"owner", "admin"}:
            self.send_error_json("只有相册管理员可以执行这个操作", 403)
            return None
        return user

    def require_album_owner(self, album_id):
        user = self.require_album_member(album_id)
        if not user:
            return None
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            self.send_error_json("Album not found", 404)
            return None
        if not is_album_owner(album, user.get("id")):
            self.send_error_json("只有相册创建人可以执行这个操作", 403)
            return None
        return user

    def require_album_permission(self, album_id, permission):
        user = self.require_album_member(album_id)
        if not user:
            return None
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            self.send_error_json("Album not found", 404)
            return None
        if not album_member_can(album, user, permission):
            labels = {"upload": "上传", "delete": "删除", "download": "下载", "share": "分享"}
            self.send_error_json("你没有%s这个相册的权限" % labels.get(permission, "操作"), 403)
            return None
        return user

    def request_origin(self):
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost:%s" % os.environ.get("PORT", "8000")
        return "%s://%s" % (proto, host)

    def absolute_url(self, value):
        if not value:
            return ""
        if re.match(r"^https?://", value):
            return value
        return urljoin(self.request_origin(), value)

    def worker_authorized(self):
        if WORKER_TOKEN and self.headers.get("X-Worker-Token") != WORKER_TOKEN:
            self.send_error_json("Unauthorized worker", 401)
            return False
        return True

    def worker_avatar_job(self, user_id):
        if not self.worker_authorized():
            return
        with LOCK:
            db = load_db()
            user = find_user_by_id(db, user_id)
            if not user:
                return self.send_error_json("User not found", 404)
            user["faceProfileStatus"] = "processing"
            upsert_user(db, user)
            save_db(db)
            source_url = public_user(user, self.request_origin()).get("avatarUrl") or ""
        if not source_url:
            return self.send_error_json("Avatar source not found", 404)
        return self.send_json({"job": {"type": FACE_JOB_AVATAR_ANALYZE, "userId": user_id, "sourceUrl": source_url}})

    def complete_avatar_job(self, user_id):
        started_at = time.perf_counter()
        if not self.worker_authorized():
            return
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        result = payload.get("analysis") or payload.get("result") or payload
        if not complete_avatar_analysis(user_id, result):
            return self.send_error_json("User not found", 404)
        LOGGER.info(
            "Worker头像结果回写完成：user_id=%s status=%s 耗时=%sms",
            user_id,
            result.get("status"),
            elapsed_ms(started_at),
            extra={"event": "worker.avatar_complete_http"},
        )
        return self.send_json({"ok": True})

    def worker_match_job(self, album_id, user_id):
        if not self.worker_authorized():
            return
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            user = find_user_by_id(db, user_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if not user:
                return self.send_error_json("User not found", 404)
        return self.send_json({"job": {"type": FACE_JOB_ALBUM_MATCH, "albumId": album_id, "userId": user_id, "album": album, "user": user}})

    def complete_match_job(self, album_id, user_id):
        started_at = time.perf_counter()
        if not self.worker_authorized():
            return
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        match = payload.get("match") or payload.get("result") or payload
        previous_match = None
        album = None
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            user = find_user_by_id(db, user_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if not user:
                return self.send_error_json("User not found", 404)
            match = enrich_album_match_photo_state(album, match)
            matches = user.setdefault("avatarAlbumMatches", {})
            previous_match = matches.get(album_id)
            matches[album_id] = match
            upsert_user(db, user)
            save_db(db)
        notify_user_album_match_if_needed(user, album, previous_match, match)
        LOGGER.info(
            "Worker相册关联结果已保存：album_id=%s user_id=%s matched=%s folder_id=%s 耗时=%sms",
            album_id,
            user_id,
            match.get("matched"),
            match.get("folderId", ""),
            elapsed_ms(started_at),
            extra={"event": "worker.match_saved"},
        )
        return self.send_json({"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            LOGGER.info("method=GET path=%s", path, extra={"event": "api.request"})
        if path == "/":
            return self.serve_file(PUBLIC / "index.html")
        if path == "/.well-known/apple-app-site-association":
            return self.serve_apple_app_site_association()
        if path == "/.well-known/assetlinks.json":
            return self.serve_android_assetlinks()
        match = re.match(r"^/join/([A-Za-z0-9_-]+)$", path)
        if match:
            return self.serve_join_landing(match.group(1))
        if path.startswith("/assets/"):
            return self.serve_file(PUBLIC / path.removeprefix("/assets/"))
        match = re.match(r"^/thumbs/([^/]+)/(tiny|card|cover)/([^/]+)$", path)
        if match:
            return self.serve_thumbnail(match.group(1), match.group(2), match.group(3))
        match = re.match(r"^/previews/([^/]+)/([^/]+)$", path)
        if match:
            return self.serve_preview(match.group(1), match.group(2))
        match = re.match(r"^/face-thumbs/([^/]+)/([^/]+)$", path)
        if match:
            return self.serve_face_thumbnail(match.group(1), match.group(2))
        if path.startswith("/uploads/"):
            return self.serve_file(UPLOADS / path.removeprefix("/uploads/"))
        if path.startswith("/avatars/"):
            return self.serve_file(AVATARS / path.removeprefix("/avatars/"))
        if path == "/api/me":
            user = self.require_user()
            if not user:
                return
            return self.send_json({"user": public_user(user, self.request_origin())})
        if path == "/api/notifications":
            current_user = self.require_user()
            if not current_user:
                return
            return self.list_notifications_request(current_user, parsed.query)
        if path == "/api/messages":
            current_user = self.require_user()
            if not current_user:
                return
            return self.list_messages_request(current_user, parsed.query)
        if path == "/api/messages/unread-count":
            current_user = self.require_user()
            if not current_user:
                return
            return self.unread_message_count_request(current_user)
        if path == "/api/albums":
            current_user = self.require_user()
            if not current_user:
                return
            with LOCK:
                db = load_db()
                allowed_ids = user_album_ids(current_user.get("id"))
                for album in db["albums"]:
                    if album.get("id") not in allowed_ids:
                        continue
                    if not stored_user_album_match(album, current_user):
                        enqueue_album_match_job(album.get("id"), current_user.get("id"))
            return self.send_json({"albums": [public_album(album, current_user) for album in db["albums"] if album.get("id") in allowed_ids]})
        match = re.match(r"^/api/invites/([A-Za-z0-9_-]+)/qr\.svg$", path)
        if match:
            return self.serve_invite_qr(match.group(1))
        match = re.match(r"^/api/invites/([A-Za-z0-9_-]+)$", path)
        if match:
            if not self.require_user():
                return
            return self.get_invite_request(match.group(1))
        match = re.match(r"^/api/worker/jobs/([^/]+)/([^/]+)$", path)
        if match:
            return self.get_worker_job(match.group(1), match.group(2))
        match = re.match(r"^/api/worker/avatar-jobs/([^/]+)$", path)
        if match:
            return self.worker_avatar_job(match.group(1))
        match = re.match(r"^/api/worker/match-jobs/([^/]+)/([^/]+)$", path)
        if match:
            return self.worker_match_job(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)$", path)
        if match:
            current_user = self.require_album_member(match.group(1))
            if not current_user:
                return
            with LOCK:
                db = load_db()
                album = find_album(db, match.group(1))
                if album and not stored_user_album_match(album, current_user):
                    enqueue_album_match_job(album.get("id"), current_user.get("id"))
            if not album:
                return self.send_error_json("Album not found", 404)
            return self.send_json({"album": public_album(album, current_user)})
        match = re.match(r"^/api/albums/([^/]+)/activities$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.list_album_activities_request(match.group(1), parsed.query)
        match = re.match(r"^/api/albums/([^/]+)/collaboration-records$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.list_album_collaboration_records_request(match.group(1), parsed.query)
        match = re.match(r"^/api/albums/([^/]+)/members$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.list_album_members(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/download$", path)
        if match:
            if not self.require_album_permission(match.group(1), "download"):
                return
            return self.download_folder(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-image$", path)
        if match:
            if not self.require_album_permission(match.group(1), "download"):
                return
            return self.download_photo_image(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-live$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.download_live_photo(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/join-requests$", path)
        if match:
            if not self.require_album_admin(match.group(1)):
                return
            return self.list_join_requests(match.group(1))
        return self.send_error_json("Not found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            LOGGER.info("method=POST path=%s", path, extra={"event": "api.request"})
        if path == "/api/auth/register":
            return self.register_user_request()
        if path == "/api/auth/login":
            return self.login_user_request()
        if path == "/api/auth/refresh":
            return self.refresh_auth_request()
        if path == "/api/auth/logout":
            return self.logout_user_request()
        if path == "/api/worker/jobs/claim":
            return self.claim_worker_job()
        match = re.match(r"^/api/worker/jobs/([^/]+)/([^/]+)/complete$", path)
        if match:
            return self.complete_worker_job(match.group(1), match.group(2))
        match = re.match(r"^/api/worker/avatar-jobs/([^/]+)/complete$", path)
        if match:
            return self.complete_avatar_job(match.group(1))
        match = re.match(r"^/api/worker/match-jobs/([^/]+)/([^/]+)/complete$", path)
        if match:
            return self.complete_match_job(match.group(1), match.group(2))
        match = re.match(r"^/api/invites/([A-Za-z0-9_-]+)/request$", path)
        if match:
            current_user = self.require_user()
            if not current_user:
                return
            return self.create_join_request(match.group(1), current_user)
        current_user = self.require_user()
        if not current_user:
            return
        if path == "/api/me/profile":
            return self.update_profile_request(current_user)
        if path == "/api/me/avatar":
            return self.update_avatar_request(current_user)
        if path == "/api/devices/apns":
            return self.register_apns_device_request(current_user)
        if path == "/api/notifications/read":
            return self.mark_notifications_read_request(current_user)
        match = re.match(r"^/api/notifications/([^/]+)/read$", path)
        if match:
            return self.mark_notification_read_request(match.group(1), current_user)
        if path == "/api/messages/mark-read":
            return self.mark_all_messages_read_request(current_user)
        match = re.match(r"^/api/messages/([^/]+)/read$", path)
        if match:
            return self.mark_message_read_request(match.group(1), current_user)
        if path == "/api/albums":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self.send_error_json("Invalid JSON")
            name = (payload.get("name") or "共享相册").strip()[:80]
            album = {
                "id": uuid.uuid4().hex[:10],
                "name": name,
                "createdAt": int(time.time()),
                "ownerUserId": current_user["id"],
                "ownerUsername": current_user.get("username", ""),
                "permissions": normalize_album_permissions(payload.get("permissions")),
                "folders": [],
                "photos": [],
                "contributors": [],
            }
            with LOCK:
                db = load_db()
                db["albums"].insert(0, album)
                save_db(db)
            add_album_member(album["id"], current_user["id"], "owner", current_user["id"])
            LOGGER.info("album_id=%s name=%s", album["id"], album["name"], extra={"event": "album.create"})
            (UPLOADS / album["id"]).mkdir(parents=True, exist_ok=True)
            return self.send_json({"album": public_album(album, current_user)}, 201)

        match = re.match(r"^/api/albums/([^/]+)/upload$", path)
        if match:
            if not self.require_album_permission(match.group(1), "upload"):
                return
            return self.upload_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/uploads/init$", path)
        if match:
            if not self.require_album_permission(match.group(1), "upload"):
                return
            return self.init_direct_uploads(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/uploads/complete$", path)
        if match:
            if not self.require_album_permission(match.group(1), "upload"):
                return
            return self.complete_direct_uploads(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/invite$", path)
        if match:
            if not self.require_album_permission(match.group(1), "share"):
                return
            return self.get_or_create_album_invite(match.group(1), current_user)
        match = re.match(r"^/api/albums/([^/]+)/invite/reset$", path)
        if match:
            if not self.require_album_permission(match.group(1), "share"):
                return
            return self.reset_album_invite(match.group(1), current_user)
        match = re.match(r"^/api/albums/([^/]+)/join-requests/([^/]+)/(approve|reject)$", path)
        if match:
            if not self.require_album_admin(match.group(1)):
                return
            return self.review_join_request(match.group(1), match.group(2), match.group(3), current_user)
        match = re.match(r"^/api/albums/([^/]+)/rename$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.rename_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/permissions$", path)
        if match:
            owner = self.require_album_owner(match.group(1))
            if not owner:
                return
            return self.update_album_permissions_request(match.group(1), owner)
        match = re.match(r"^/api/albums/([^/]+)/reanalyze$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.reanalyze_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/photos/download-selected$", path)
        if match:
            if not self.require_album_permission(match.group(1), "download"):
                return
            return self.download_selected_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/photos/delete-selected$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.delete_selected_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/members/([^/]+)/permissions$", path)
        if match:
            owner = self.require_album_owner(match.group(1))
            if not owner:
                return
            return self.update_album_member_permissions_request(match.group(1), match.group(2), owner)
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/merge$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.merge_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/rename$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.rename_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/mark-no-face$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.mark_no_face_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/move$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.move_photo_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/reclassify$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.reclassify_photo_request(match.group(1), match.group(2))
        return self.send_error_json("Not found", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            LOGGER.info("method=DELETE path=%s", path, extra={"event": "api.request"})
        if not self.require_user():
            return
        match = re.match(r"^/api/albums/([^/]+)$", path)
        if match:
            if not self.require_album_owner(match.group(1)):
                return
            return self.delete_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/members/([^/]+)$", path)
        if match:
            owner = self.require_album_owner(match.group(1))
            if not owner:
                return
            return self.remove_album_member_request(match.group(1), match.group(2), owner)
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.delete_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)$", path)
        if match:
            if not self.require_album_member(match.group(1)):
                return
            return self.delete_photo_request(match.group(1), match.group(2))
        return self.send_error_json("Not found", 404)

    def register_user_request(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        username = normalize_username(form.getfirst("username") or "")
        nickname = (form.getfirst("nickname") or "").strip()[:40]
        password = form.getfirst("password") or ""
        if not validate_username(username):
            return self.send_error_json("登录账号需为 1-20 位字母、数字或下划线")
        if not nickname:
            return self.send_error_json("昵称不能为空")
        if not validate_password_format(password):
            return self.send_error_json("密码需为 6-20 位，只能使用数字、字母和英文符号")

        with LOCK:
            db = load_db()
            if find_user_by_username(db, username):
                return self.send_error_json("这个登录账号已被使用", 409)
            now = int(time.time())
            user = {
                "id": uuid.uuid4().hex,
                "username": username,
                "nickname": nickname,
                "passwordHash": hash_password(password),
                "avatarUrl": "",
                "avatarObjectKey": "",
                "hasFaceProfile": False,
                "createdAt": now,
            }
            warning = ""
            avatar_item = form["avatar"] if "avatar" in form else None
            if avatar_item is not None and getattr(avatar_item, "filename", None):
                suffix = Path(avatar_item.filename).suffix.lower() or ".jpg"
                tmp = tempfile.NamedTemporaryFile(prefix="picme-register-avatar-", suffix=suffix, delete=False)
                tmp.close()
                avatar_source = Path(tmp.name)
                try:
                    with avatar_source.open("wb") as out:
                        shutil.copyfileobj(avatar_item.file, out)
                    warning = save_avatar_image(user, avatar_source)
                finally:
                    avatar_source.unlink(missing_ok=True)
            upsert_user(db, user)
            save_db(db)
        if avatar_item is not None and getattr(avatar_item, "filename", None):
            enqueue_avatar_job(user["id"])
        auth = auth_payload(user, self)
        LOGGER.info("user_id=%s username=%s face=%s", user["id"], username, user.get("hasFaceProfile"), extra={"event": "auth.register"})
        payload = {"user": public_user(user, self.request_origin()), **auth}
        if warning:
            payload["warning"] = warning
        return self.send_json(payload, 201)

    def login_user_request(self):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        username = normalize_username(payload.get("username") or "")
        password = payload.get("password") or ""
        with LOCK:
            db = load_db()
            user = find_user_by_username(db, username)
        if not user or not verify_password(password, user.get("passwordHash")):
            return self.send_error_json("登录账号或密码不正确", 401)
        auth = auth_payload(user, self)
        LOGGER.info("user_id=%s username=%s", user["id"], username, extra={"event": "auth.login"})
        return self.send_json({"user": public_user(user, self.request_origin()), **auth})

    def refresh_auth_request(self):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        refreshed = refresh_auth_tokens(payload.get("refreshToken") or payload.get("refresh_token") or "")
        if not refreshed:
            return self.send_error_json("登录已失效，请重新登录", 401)
        user = refreshed.pop("user")
        LOGGER.info("user_id=%s session_id=%s", user.get("id"), refreshed.get("sessionId"), extra={"event": "auth.refresh"})
        return self.send_json({"user": public_user(user, self.request_origin()), **refreshed})

    def logout_user_request(self):
        token = self.bearer_token()
        if token:
            revoke_session_for_access_token(token)
        return self.send_json({"ok": True})

    def update_profile_request(self, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        nickname = (payload.get("nickname") or "").strip()[:40]
        if not nickname:
            return self.send_error_json("昵称不能为空")
        with LOCK:
            db = load_db()
            user = find_user_by_id(db, current_user.get("id"))
            if not user:
                return self.send_error_json("请先登录", 401)
            user["nickname"] = nickname
            upsert_user(db, user)
            save_db(db)
        self._current_user = user
        LOGGER.info("user_id=%s nickname=%s", user.get("id"), nickname, extra={"event": "user.profile_update"})
        return self.send_json({"user": public_user(user, self.request_origin())})

    def update_avatar_request(self, current_user):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        avatar_item = form["avatar"] if "avatar" in form else None
        if avatar_item is None or not getattr(avatar_item, "filename", None):
            return self.send_error_json("请选择头像")

        suffix = Path(avatar_item.filename).suffix.lower() or ".jpg"
        tmp = tempfile.NamedTemporaryFile(prefix="picme-update-avatar-", suffix=suffix, delete=False)
        tmp.close()
        avatar_source = Path(tmp.name)
        warning = ""
        try:
            with avatar_source.open("wb") as out:
                shutil.copyfileobj(avatar_item.file, out)
            with LOCK:
                db = load_db()
                user = find_user_by_id(db, current_user.get("id"))
                if not user:
                    return self.send_error_json("请先登录", 401)
                warning = save_avatar_image(user, avatar_source)
                upsert_user(db, user)
                save_db(db)
            self._current_user = user
            enqueue_avatar_job(user["id"])
        finally:
            avatar_source.unlink(missing_ok=True)

        payload = {"user": public_user(user, self.request_origin())}
        if warning:
            payload["warning"] = warning
        return self.send_json(payload)

    def init_direct_uploads(self, album_id):
        if not oss_enabled():
            return self.send_error_json("OSS direct upload is not configured", 409)
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        files = payload.get("files") or []
        if not isinstance(files, list) or not files:
            return self.send_error_json("Missing files")
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)

        grouped = {}
        ignored = 0
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                ignored += 1
                continue
            original = Path(str(item.get("name") or item.get("filename") or "")).name
            suffix = Path(original).suffix.lower()
            if suffix not in IMAGE_EXTS | LIVE_VIDEO_EXTS:
                ignored += 1
                continue
            key = (item.get("clientAssetId") or Path(original).stem or str(index)).lower()
            grouped.setdefault(key, {"images": [], "videos": []})
            normalized = {
                "clientFileId": str(item.get("clientFileId") or "%s-%s" % (key, index)),
                "originalName": original,
                "suffix": suffix,
                "mimeType": item.get("mimeType") or item.get("type") or safe_mime_type(original),
                "fileSize": int(item.get("fileSize") or item.get("size") or 0),
            }
            if suffix in LIVE_VIDEO_EXTS:
                grouped[key]["videos"].append(normalized)
            else:
                grouped[key]["images"].append(normalized)

        uploads = []
        for group in grouped.values():
            image_items = group["images"]
            video_items = group["videos"]
            heic_item = next((item for item in image_items if item["suffix"] in LIVE_IMAGE_EXTS), None)
            image_item = heic_item or (image_items[0] if image_items else None)
            if not image_item:
                ignored += len(video_items)
                continue
            video_item = video_items[0] if heic_item and video_items else None
            photo_id = str(uuid.uuid4())

            def signed_resource(file_item, ext):
                object_key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=ext)
                upload_url, headers = OSS_SERVICE.generateUploadUrl(object_key, file_item["mimeType"])
                if not upload_url:
                    return None
                stored_name = "%s%s" % (photo_id, ext)
                return {
                    "clientFileId": file_item["clientFileId"],
                    "objectKey": object_key,
                    "uploadUrl": upload_url,
                    "headers": headers,
                    "originalName": file_item["originalName"],
                    "storedName": stored_name,
                    "mimeType": file_item["mimeType"],
                    "fileSize": file_item["fileSize"],
                }

            image_resource = signed_resource(image_item, image_item["suffix"])
            if not image_resource:
                return self.send_error_json("Failed to sign upload URL", 502)
            video_resource = signed_resource(video_item, video_item["suffix"]) if video_item else None
            if video_item and not video_resource:
                return self.send_error_json("Failed to sign live video upload URL", 502)
            uploads.append({
                "photoId": photo_id,
                "type": "live_photo" if video_resource else "photo",
                "image": image_resource,
                "video": video_resource,
            })

        LOGGER.info("album_id=%s uploads=%d ignored=%d", album_id, len(uploads), ignored, extra={"event": "direct_upload.init"})
        return self.send_json({"uploads": uploads, "ignored": ignored, "expiresIn": OSS_UPLOAD_URL_EXPIRES})

    def complete_direct_uploads(self, album_id):
        if not oss_enabled():
            return self.send_error_json("OSS direct upload is not configured", 409)
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        uploader = (payload.get("uploader") or "访客").strip()[:40]
        uploads = payload.get("uploads") or []
        if not isinstance(uploads, list) or not uploads:
            return self.send_error_json("Missing uploads")

        created = []
        queued = []
        current_user = self.current_user()
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if uploader not in album["contributors"]:
                album["contributors"].append(uploader)
            pending_folder = get_pending_folder(album)
            existing_ids = {photo.get("id") for photo in album.get("photos", [])}

            for upload in uploads:
                if not isinstance(upload, dict):
                    continue
                photo_id = str(upload.get("photoId") or "")
                image = upload.get("image") or {}
                if not photo_id or not isinstance(image, dict) or not image.get("objectKey"):
                    continue
                image_head = OSS_SERVICE.headObject(image["objectKey"])
                if not image_head:
                    return self.send_error_json("Uploaded image object not found", 400)
                expected_size = int(image.get("fileSize") or 0)
                if expected_size and image_head.get("file_size") and expected_size != image_head["file_size"]:
                    return self.send_error_json("Uploaded image size mismatch", 400)
                image_head["resource_type"] = "original"
                image_head["mime_type"] = image_head.get("mime_type") or image.get("mimeType") or safe_mime_type(image.get("originalName"))

                photo = next((item for item in album.get("photos", []) if item.get("id") == photo_id), None)
                if not photo:
                    photo = {
                        "id": photo_id,
                        "type": upload.get("type") or "photo",
                        "originalName": image.get("originalName") or image.get("storedName") or ("%s%s" % (photo_id, Path(image["objectKey"]).suffix)),
                        "storedName": image.get("storedName") or ("%s%s" % (photo_id, Path(image["objectKey"]).suffix)),
                        "url": "/uploads/%s/%s" % (album_id, image.get("storedName") or photo_id),
                        "uploader": uploader,
                        "uploaderUserId": current_user.get("id") if current_user else "",
                        "createdAt": int(time.time()),
                        "status": "queued",
                    }
                    apply_photo_folders(photo, [pending_folder], "已上传，等待后台识别")
                    album["photos"].append(photo)
                apply_resource_metadata(photo, image_head)

                video = upload.get("video") or None
                if isinstance(video, dict) and video.get("objectKey"):
                    video_head = OSS_SERVICE.headObject(video["objectKey"])
                    if not video_head:
                        return self.send_error_json("Uploaded live video object not found", 400)
                    expected_video_size = int(video.get("fileSize") or 0)
                    if expected_video_size and video_head.get("file_size") and expected_video_size != video_head["file_size"]:
                        return self.send_error_json("Uploaded live video size mismatch", 400)
                    video_head["resource_type"] = "original"
                    video_head["mime_type"] = video_head.get("mime_type") or video.get("mimeType") or safe_mime_type(video.get("originalName"))
                    photo["type"] = "live_photo"
                    photo["liveVideoOriginalName"] = video.get("originalName") or video.get("storedName") or ("%s.mov" % photo_id)
                    photo["liveVideoStoredName"] = video.get("storedName") or ("%s%s" % (photo_id, Path(video["objectKey"]).suffix))
                    apply_resource_metadata(photo, video_head, "liveVideo")

                if photo_id not in existing_ids:
                    created.append(photo)
                    queued.append(photo_id)
                    existing_ids.add(photo_id)
                    record_album_activity(
                        album_id,
                        "photo.upload",
                        actor=current_user,
                        actor_name=uploader,
                        target_type="photo",
                        target_id=photo_id,
                        message="%s 上传了照片 %s" % (actor_display_name(current_user, uploader), photo_display_name(photo)),
                        data={"photoId": photo_id, "photoName": photo_display_name(photo), "uploader": uploader},
                        db=db,
                    )
                else:
                    created.append(photo)
                    if photo.get("status") in {"queued", "preparing", "processing"}:
                        queued.append(photo_id)

            save_db(db)
            response_album = public_album(album, self.current_user())
            response_created = [
                item for item in response_album.get("photos", [])
                if item.get("id") in {photo.get("id") for photo in created}
            ]
        for photo_id in queued:
            enqueue_photo_job(album_id, photo_id)
        LOGGER.info("album_id=%s created=%d queued=%d", album_id, len(created), len(queued), extra={"event": "direct_upload.complete"})
        return self.send_json({"photos": response_created, "album": response_album, "queued": len(queued), "ignored": 0, "photoIds": queued}, 202)

    def upload_photos(self, album_id):
        LOGGER.info("album_id=%s", album_id, extra={"event": "upload.start"})
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        uploader = (form.getfirst("uploader") or "访客").strip()[:40]
        files = form["photos"] if "photos" in form else []
        if not isinstance(files, list):
            files = [files]
        files = [item for item in files if getattr(item, "filename", None)]
        if not files:
            LOGGER.info("album_id=%s", album_id, extra={"event": "upload.empty"})
            return self.send_error_json("No photos uploaded")

        created = []
        current_user = self.current_user()
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if uploader not in album["contributors"]:
                album["contributors"].append(uploader)

            album_dir = UPLOADS / album_id
            if not oss_enabled():
                album_dir.mkdir(parents=True, exist_ok=True)
            pending_folder = get_pending_folder(album)
            queued = []
            grouped = {}
            ignored = 0
            for item in files:
                original = Path(item.filename).name
                path = Path(original)
                suffix = path.suffix.lower()
                if suffix not in IMAGE_EXTS | LIVE_VIDEO_EXTS:
                    ignored += 1
                    continue
                key = path.stem.lower()
                grouped.setdefault(key, {"images": [], "videos": []})
                if suffix in LIVE_VIDEO_EXTS:
                    grouped[key]["videos"].append((item, original, suffix))
                else:
                    grouped[key]["images"].append((item, original, suffix))

            for key, group in grouped.items():
                image_items = group["images"]
                video_items = group["videos"]
                heic_item = next((item for item in image_items if item[2] in LIVE_IMAGE_EXTS), None)
                image_item = heic_item or (image_items[0] if image_items else None)
                if not image_item:
                    ignored += len(video_items)
                    continue

                image_file, original, suffix = image_item
                video_item = video_items[0] if heic_item and video_items else None
                photo_id = str(uuid.uuid4())
                stored_name = "%s%s" % (photo_id, suffix)
                mime_type = mimetypes.guess_type(stored_name)[0] or "application/octet-stream"
                image_source_for_derivatives = None
                if oss_enabled():
                    tmp = tempfile.NamedTemporaryFile(prefix="picme-upload-", suffix=suffix, delete=False)
                    tmp.close()
                    target = Path(tmp.name)
                    try:
                        with target.open("wb") as out:
                            shutil.copyfileobj(image_file.file, out)
                        object_key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=suffix)
                        image_metadata = OSS_SERVICE.uploadFile(target, object_key, mime_type, "original")
                        image_source_for_derivatives = target
                    except Exception:
                        target.unlink(missing_ok=True)
                        raise
                    if not image_metadata:
                        target.unlink(missing_ok=True)
                        return self.send_error_json("OSS upload failed", 502)
                else:
                    target = album_dir / stored_name
                    with target.open("wb") as out:
                        shutil.copyfileobj(image_file.file, out)
                    image_metadata = {
                        "object_key": "",
                        "oss_url": "",
                        "resource_type": "original",
                        "mime_type": mime_type,
                        "file_size": target.stat().st_size,
                    }

                photo = {
                    "id": photo_id,
                    "type": "live_photo" if video_item else "photo",
                    "originalName": original,
                    "storedName": stored_name,
                    "url": "/uploads/%s/%s" % (album_id, stored_name),
                    "uploader": uploader,
                    "uploaderUserId": current_user.get("id") if current_user else "",
                    "createdAt": int(time.time()),
                    "status": "queued",
                }
                apply_resource_metadata(photo, image_metadata)
                if oss_enabled() and image_source_for_derivatives:
                    try:
                        generate_preview_for_photo(album_id, photo, image_source_for_derivatives)
                        generate_thumbnail_for_photo(album_id, photo, image_source_for_derivatives)
                    except Exception as error:
                        LOGGER.warning(
                            "album_id=%s photo_id=%s error=%s",
                            album_id,
                            photo_id,
                            error,
                            extra={"event": "oss.derivative_failed"},
                        )
                    finally:
                        image_source_for_derivatives.unlink(missing_ok=True)

                if video_item:
                    video_file, video_original, video_suffix = video_item
                    video_stored_name = "%s%s" % (photo_id, video_suffix)
                    video_mime_type = mimetypes.guess_type(video_stored_name)[0] or "application/octet-stream"
                    if oss_enabled():
                        tmp = tempfile.NamedTemporaryFile(prefix="picme-live-", suffix=video_suffix, delete=False)
                        tmp.close()
                        video_target = Path(tmp.name)
                        try:
                            with video_target.open("wb") as out:
                                shutil.copyfileobj(video_file.file, out)
                            video_key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=video_suffix)
                            video_metadata = OSS_SERVICE.uploadFile(video_target, video_key, video_mime_type, "original")
                        finally:
                            video_target.unlink(missing_ok=True)
                        if not video_metadata:
                            return self.send_error_json("OSS live video upload failed", 502)
                    else:
                        video_target = album_dir / video_stored_name
                        with video_target.open("wb") as out:
                            shutil.copyfileobj(video_file.file, out)
                        video_metadata = {
                            "object_key": "",
                            "oss_url": "",
                            "resource_type": "original",
                            "mime_type": video_mime_type,
                            "file_size": video_target.stat().st_size,
                        }
                    photo["liveVideoOriginalName"] = video_original
                    photo["liveVideoStoredName"] = video_stored_name
                    apply_resource_metadata(photo, video_metadata, "liveVideo")

                apply_photo_folders(photo, [pending_folder], "已上传，等待后台识别")
                album["photos"].append(photo)
                created.append(photo)
                queued.append(photo["id"])
                record_album_activity(
                    album_id,
                    "photo.upload",
                    actor=current_user,
                    actor_name=uploader,
                    target_type="photo",
                    target_id=photo_id,
                    message="%s 上传了照片 %s" % (actor_display_name(current_user, uploader), photo_display_name(photo)),
                    data={"photoId": photo_id, "photoName": photo_display_name(photo), "uploader": uploader},
                    db=db,
                )
                LOGGER.info(
                    "album_id=%s photo_id=%s original=%s mime=%s live=%s",
                    album_id,
                    photo_id,
                    original,
                    mime_type,
                    bool(video_item),
                    extra={"event": "upload.photo_created"},
                )
            save_db(db)
            response_album = public_album(album, self.current_user())
            response_created = [
                item for item in response_album.get("photos", [])
                if item.get("id") in queued
            ]
        for photo_id in queued:
            enqueue_photo_job(album_id, photo_id)
        LOGGER.info(
            "album_id=%s created=%d ignored=%d",
            album_id,
            len(created),
            ignored,
            extra={"event": "upload.complete"},
        )
        return self.send_json({"photos": response_created, "album": response_album, "queued": len(created), "ignored": ignored, "photoIds": queued}, 202)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}"), ""
        except json.JSONDecodeError:
            return None, "Invalid JSON"

    def list_album_activities_request(self, album_id, query):
        params = parse_qs(query or "")
        limit = params.get("limit", ["50"])[0]
        before = params.get("before", ["0"])[0]
        try:
            activities = list_album_activities(album_id, int(limit or 50), int(before or 0))
        except ValueError:
            return self.send_error_json("Invalid pagination")
        return self.send_json({"activities": activities})

    def list_album_collaboration_records_request(self, album_id, query):
        params = parse_qs(query or "")
        limit = params.get("limit", ["50"])[0]
        before = params.get("before", ["0"])[0]
        try:
            records = list_album_activities(album_id, int(limit or 50), int(before or 0))
        except ValueError:
            return self.send_error_json("Invalid pagination")
        return self.send_json({"records": records})

    def list_notifications_request(self, current_user, query):
        params = parse_qs(query or "")
        unread_value = (params.get("unread", [""])[0] or params.get("status", [""])[0]).lower()
        unread_only = unread_value in {"1", "true", "yes", "unread"}
        limit = params.get("limit", ["50"])[0]
        before = params.get("before", ["0"])[0]
        try:
            notifications, unread_count = list_user_notifications(current_user["id"], unread_only, int(limit or 50), int(before or 0))
        except ValueError:
            return self.send_error_json("Invalid pagination")
        return self.send_json({"notifications": notifications, "unreadCount": unread_count})

    def list_messages_request(self, current_user, query):
        params = parse_qs(query or "")
        unread_value = (params.get("unread", [""])[0] or params.get("status", [""])[0]).lower()
        unread_only = unread_value in {"1", "true", "yes", "unread"}
        limit = params.get("limit", ["50"])[0]
        before = params.get("before", ["0"])[0]
        try:
            messages, unread_count = list_user_notifications(current_user["id"], unread_only, int(limit or 50), int(before or 0))
        except ValueError:
            return self.send_error_json("Invalid pagination")
        return self.send_json({"messages": messages, "unreadCount": unread_count})

    def unread_message_count_request(self, current_user):
        _, unread_count = list_user_notifications(current_user["id"], False, 1, 0)
        return self.send_json({"unreadCount": unread_count})

    def register_apns_device_request(self, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        token = normalize_apns_device_token(payload.get("deviceToken") or payload.get("token") or "")
        if not token:
            return self.send_error_json("Missing device token")
        ok = register_apns_device(
            current_user["id"],
            token,
            payload.get("environment") or APNS_ENVIRONMENT,
            payload.get("deviceId") or "",
            payload.get("deviceName") or "",
        )
        if not ok:
            return self.send_error_json("Invalid device token")
        return self.send_json({"ok": True, "pushEnabled": apns_enabled()})

    def mark_notifications_read_request(self, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        notification_ids = payload.get("ids") or payload.get("notificationIds") or []
        mark_all = bool(payload.get("all") or payload.get("markAll"))
        if not mark_all and not notification_ids:
            return self.send_error_json("Missing notification ids")
        updated = mark_user_notifications_read(current_user["id"], notification_ids, mark_all)
        _, unread_count = list_user_notifications(current_user["id"], False, 1, 0)
        return self.send_json({"updated": updated, "unreadCount": unread_count})

    def mark_notification_read_request(self, notification_id, current_user):
        updated = mark_user_notifications_read(current_user["id"], [notification_id], False)
        _, unread_count = list_user_notifications(current_user["id"], False, 1, 0)
        return self.send_json({"updated": updated, "unreadCount": unread_count})

    def mark_message_read_request(self, message_id, current_user):
        updated = mark_user_notifications_read(current_user["id"], [message_id], False)
        _, unread_count = list_user_notifications(current_user["id"], False, 1, 0)
        return self.send_json({"updated": updated, "unreadCount": unread_count})

    def mark_all_messages_read_request(self, current_user):
        updated = mark_user_notifications_read(current_user["id"], None, True)
        _, unread_count = list_user_notifications(current_user["id"], False, 1, 0)
        return self.send_json({"updated": updated, "unreadCount": unread_count})

    def get_or_create_album_invite(self, album_id, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        requested_permissions = payload.get("permissions") if isinstance(payload, dict) else None
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        invite = active_invite_for_album(
            album_id,
            current_user["id"],
            self.request_origin(),
            album,
            current_user,
            requested_permissions,
        )
        LOGGER.info("album_id=%s code=%s", album_id, invite.get("code") if invite else "", extra={"event": "invite.get"})
        return self.send_json({"invite": invite})

    def reset_album_invite(self, album_id, current_user):
        if not sqlite_enabled():
            return self.send_error_json("相册分享需要 SQLite 存储", 409)
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        now = int(time.time())
        requested_permissions = payload.get("permissions") if isinstance(payload, dict) else None
        with sqlite_connect() as conn:
            previous = conn.execute(
                "SELECT permissions_json FROM album_invites WHERE album_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (album_id,),
            ).fetchone()
            if requested_permissions is None and previous:
                try:
                    requested_permissions = json.loads(previous["permissions_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    requested_permissions = None
            with conn:
                conn.execute(
                    "UPDATE album_invites SET status = 'revoked', revoked_at = ? WHERE album_id = ? AND status = 'active'",
                    (now, album_id),
                )
        invite = active_invite_for_album(
            album_id,
            current_user["id"],
            self.request_origin(),
            album,
            current_user,
            requested_permissions,
        )
        LOGGER.info("album_id=%s code=%s", album_id, invite.get("code") if invite else "", extra={"event": "invite.reset"})
        return self.send_json({"invite": invite})

    def get_invite_request(self, code):
        row = invite_by_code(code)
        if not row:
            return self.send_error_json("相册码无效或已失效", 404)
        current_user = self.current_user()
        with LOCK:
            db = load_db()
            album = find_album(db, row["album_id"])
        if not album:
            return self.send_error_json("Album not found", 404)
        status = "none"
        role = album_member_role(row["album_id"], current_user.get("id"))
        if role:
            status = "member"
        else:
            request = latest_join_request(row["album_id"], current_user.get("id"))
            if request:
                status = request["status"]
        invite = invite_public_payload(row, self.request_origin(), album, current_user)
        return self.send_json({"invite": invite, "joinStatus": status, "currentUserRole": role})

    def create_join_request(self, code, current_user):
        row = invite_by_code(code)
        if not row:
            return self.send_error_json("相册码无效或已失效", 404)
        if album_member_role(row["album_id"], current_user.get("id")):
            return self.send_json({"status": "member", "message": "你已经在这个相册中"})
        existing = latest_join_request(row["album_id"], current_user.get("id"))
        if existing and existing["status"] == "pending":
            return self.send_json({"status": "pending", "requestId": existing["id"], "message": "申请已提交，等待管理员批准"})
        now = int(time.time())
        request_id = uuid.uuid4().hex
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO album_join_requests(id, album_id, invite_id, user_id, status, created_at, reviewed_by, reviewed_at)
                    VALUES(?, ?, ?, ?, 'pending', ?, NULL, NULL)
                    """,
                    (request_id, row["album_id"], row["id"], current_user["id"], now),
                )
        with LOCK:
            db = load_db()
            album = find_album(db, row["album_id"])
        album_name = album_display_name(album)
        applicant_name = actor_display_name(current_user, "新成员")
        notified = 0
        for admin_user_id in album_admin_user_ids(row["album_id"]):
            if admin_user_id == current_user["id"]:
                continue
            create_notification(
                admin_user_id,
                "album.join_request",
                "新的加入申请",
                "%s 申请加入「%s」" % (applicant_name, album_name),
                album_id=row["album_id"],
                actor=current_user,
                data={"requestId": request_id, "applicantUserId": current_user["id"], "albumName": album_name},
            )
            notified += 1
        LOGGER.info("album_id=%s user_id=%s request_id=%s", row["album_id"], current_user["id"], request_id, extra={"event": "invite.request"})
        LOGGER.info("album_id=%s request_id=%s admins=%d", row["album_id"], request_id, notified, extra={"event": "notification.join_request"})
        return self.send_json({"status": "pending", "requestId": request_id, "message": "申请已提交，等待管理员批准"}, 201)

    def list_join_requests(self, album_id):
        if not sqlite_enabled():
            return self.send_json({"requests": []})
        with sqlite_connect() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.album_id, r.invite_id, r.user_id, r.status, r.created_at, r.reviewed_by, r.reviewed_at,
                       u.username, u.nickname, u.avatar_url, u.avatar_object_key, u.has_face_profile, u.data_json
                FROM album_join_requests r
                JOIN users u ON u.id = r.user_id
                WHERE r.album_id = ?
                ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END, r.created_at DESC
                """,
                (album_id,),
            ).fetchall()
        requests = []
        for row in rows:
            user = json.loads(row["data_json"])
            user.update({
                "id": row["user_id"],
                "username": row["username"],
                "nickname": row["nickname"],
                "avatarUrl": row["avatar_url"] or "",
                "avatarObjectKey": row["avatar_object_key"] or "",
                "hasFaceProfile": bool(row["has_face_profile"]),
            })
            requests.append({
                "id": row["id"],
                "albumId": row["album_id"],
                "status": row["status"],
                "createdAt": row["created_at"],
                "reviewedAt": row["reviewed_at"],
                "user": public_user(user, self.request_origin()),
            })
        return self.send_json({"requests": requests})

    def list_album_members(self, album_id):
        if not sqlite_enabled():
            return self.send_json({"members": []})
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        with sqlite_connect() as conn:
            rows = conn.execute(
                """
                SELECT m.album_id, m.user_id, m.role, m.status, m.created_at, m.joined_at,
                       m.approved_by, m.permissions_json,
                       u.username, u.nickname, u.avatar_url, u.avatar_object_key,
                       u.has_face_profile, u.data_json
                FROM album_members m
                JOIN users u ON u.id = m.user_id
                WHERE m.album_id = ? AND m.status = 'active'
                ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
                         m.joined_at ASC, m.created_at ASC
                """,
                (album_id,),
            ).fetchall()
        members = []
        for row in rows:
            user = json.loads(row["data_json"])
            user.update({
                "id": row["user_id"],
                "username": row["username"],
                "nickname": row["nickname"],
                "avatarUrl": row["avatar_url"] or "",
                "avatarObjectKey": row["avatar_object_key"] or "",
                "hasFaceProfile": bool(row["has_face_profile"]),
            })
            member_permissions = member_public_permissions(row)
            effective_permissions = normalize_album_permissions() if row["role"] == "owner" else {
                key: bool(ensure_album_permissions(album).get(key)) and bool(member_permissions.get(key))
                for key in ALBUM_PERMISSION_KEYS
            }
            members.append({
                "albumId": row["album_id"],
                "userId": row["user_id"],
                "role": row["role"],
                "status": row["status"],
                "createdAt": row["created_at"],
                "joinedAt": row["joined_at"],
                "approvedBy": row["approved_by"] or "",
                "permissions": member_permissions,
                "effectivePermissions": effective_permissions,
                "user": public_user(user, self.request_origin()),
            })
        return self.send_json({"members": members})

    def update_album_permissions_request(self, album_id, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if not is_album_owner(album, current_user.get("id")):
                return self.send_error_json("只有相册创建人可以执行这个操作", 403)
            album["permissions"] = normalize_album_permissions(payload.get("permissions") if isinstance(payload, dict) else {})
            save_db(db)
            response = public_album(album, current_user)
        return self.send_json({"album": response})

    def update_album_member_permissions_request(self, album_id, user_id, current_user):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        if not is_album_owner(album, current_user.get("id")):
            return self.send_error_json("只有相册创建人可以执行这个操作", 403)
        if user_id == current_user.get("id") or album_member_role(album_id, user_id) == "owner":
            return self.send_error_json("不能修改相册创建人的权限", 403)
        if not update_album_member_permissions(album_id, user_id, payload.get("permissions") if isinstance(payload, dict) else {}):
            return self.send_error_json("协作用户不存在", 404)
        with LOCK:
            album = find_album(load_db(), album_id)
        return self.send_json({"album": public_album(album, current_user) if album else None})

    def remove_album_member_request(self, album_id, user_id, current_user):
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        if not is_album_owner(album, current_user.get("id")):
            return self.send_error_json("只有相册创建人可以执行这个操作", 403)
        if user_id == current_user.get("id") or album_member_role(album_id, user_id) == "owner":
            return self.send_error_json("不能移除相册创建人", 403)
        if not remove_album_member(album_id, user_id):
            return self.send_error_json("协作用户不存在", 404)
        LOGGER.info("album_id=%s user_id=%s actor=%s", album_id, user_id, current_user["id"], extra={"event": "album.member_remove"})
        with LOCK:
            album = find_album(load_db(), album_id)
        return self.send_json({"album": public_album(album, current_user) if album else None, "removedUserId": user_id})

    def review_join_request(self, album_id, request_id, action, current_user):
        if not sqlite_enabled():
            return self.send_error_json("相册分享需要 SQLite 存储", 409)
        with sqlite_connect() as conn:
            request = conn.execute(
                "SELECT * FROM album_join_requests WHERE id = ? AND album_id = ?",
                (request_id, album_id),
            ).fetchone()
            if not request:
                return self.send_error_json("申请不存在", 404)
            if request["status"] != "pending":
                return self.send_error_json("这个申请已经处理过", 409)
            next_status = "approved" if action == "approve" else "rejected"
            now = int(time.time())
            with conn:
                conn.execute(
                    "UPDATE album_join_requests SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                    (next_status, current_user["id"], now, request_id),
                )
        if action == "approve":
            invite_permissions = None
            with sqlite_connect() as conn:
                invite_row = conn.execute("SELECT permissions_json FROM album_invites WHERE id = ?", (request["invite_id"],)).fetchone()
                if invite_row:
                    try:
                        invite_permissions = json.loads(invite_row["permissions_json"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        invite_permissions = None
            add_album_member(album_id, request["user_id"], "member", current_user["id"], invite_permissions)
            enqueue_album_match_job(album_id, request["user_id"])
        LOGGER.info(
            "album_id=%s request_id=%s action=%s reviewer=%s",
            album_id,
            request_id,
            action,
            current_user["id"],
            extra={"event": "invite.review"},
        )
        with LOCK:
            album = find_album(load_db(), album_id)
        album_name = album_display_name(album)
        activity = record_album_activity(
            album_id,
            "join_request.%s" % next_status,
            actor=current_user,
            target_type="join_request",
            target_id=request_id,
            message="%s %s了加入申请" % (actor_display_name(current_user), "批准" if action == "approve" else "拒绝"),
            data={"requestId": request_id, "requestUserId": request["user_id"], "status": next_status, "albumName": album_name},
        )
        create_notification(
            request["user_id"],
            "album.join_%s" % next_status,
            "加入申请已%s" % ("通过" if action == "approve" else "拒绝"),
            "你加入「%s」的申请已%s" % (album_name, "通过" if action == "approve" else "拒绝"),
            album_id=album_id,
            activity_id=(activity or {}).get("id", ""),
            actor=current_user,
            data={"requestId": request_id, "status": next_status, "albumName": album_name},
        )
        return self.send_json({"status": next_status, "album": public_album(album, current_user) if album else None})

    def claim_worker_job(self):
        if not self.worker_authorized():
            return
        LOGGER.info("mode=remote", extra={"event": "worker.claim"})
        with LOCK:
            db = load_db()
            for album in db.get("albums", []):
                for photo in album.get("photos", []):
                    if photo.get("status") not in {"queued", "preparing", "processing"}:
                        continue
                    photo["status"] = "processing"
                    photo["classification"] = "正在识别人脸"
                    source, cleanup_source = materialize_photo_source(album["id"], photo)
                    if source:
                        try:
                            generate_preview_for_photo(album["id"], photo, source)
                            generate_thumbnail_for_photo(album["id"], photo, source)
                        finally:
                            cleanup_source()
                    sync_photo_folder_names(album)
                    save_db(db)
                    public_photo = photo_public_urls(album["id"], photo)
                    source_url = self.absolute_url(public_photo.get("previewUrl") or public_photo.get("imageUrl"))
                    LOGGER.info(
                        "album_id=%s photo_id=%s",
                        album["id"],
                        photo["id"],
                        extra={"event": "worker.claimed"},
                    )
                    return self.send_json({
                        "job": {
                            "albumId": album["id"],
                            "photoId": photo["id"],
                            "photo": public_photo,
                            "sourceUrl": source_url,
                        }
                    })
        LOGGER.info("mode=remote", extra={"event": "worker.claim_empty"})
        return self.send_json({"job": None})

    def get_worker_job(self, album_id, photo_id):
        if not self.worker_authorized():
            return
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.job_get"})
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
            if not photo:
                return self.send_error_json("Photo not found", 404)
            photo["status"] = "processing"
            photo["classification"] = "正在识别人脸"
            sync_photo_folder_names(album)
            save_db(db)
            public_photo = photo_public_urls(album_id, photo)
            source_url = self.absolute_url(public_photo.get("previewUrl") or public_photo.get("imageUrl"))
            return self.send_json({
                "job": {
                    "albumId": album_id,
                    "photoId": photo_id,
                    "photo": public_photo,
                    "sourceUrl": source_url,
                }
            })

    def complete_worker_job(self, album_id, photo_id):
        if not self.worker_authorized():
            return
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        analysis = payload.get("analysis") or payload
        resources = payload.get("resources") or payload.get("resourceMetadata") or {}
        LOGGER.info(
            "album_id=%s photo_id=%s status=%s engine=%s face_count=%s",
            album_id,
            photo_id,
            analysis.get("status"),
            analysis.get("engine", ""),
            analysis.get("faceCount", ""),
            extra={"event": "worker.complete_received"},
        )
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
            if not photo:
                return self.send_error_json("Photo not found", 404)
            apply_worker_resource_metadata(photo, resources)
            apply_face_analysis(album, photo, analysis)
            if not face_object_key(photo):
                source, cleanup_source = materialize_photo_source(album_id, photo)
                try:
                    if source:
                        face_user_id = next((item for item in photo_folder_ids(photo) if item not in {"group-photo", "no-face", "pending"}), album_id)
                        generate_face_thumbnail_for_photo(album_id, photo, source, face_user_id)
                finally:
                    cleanup_source()
            prune_empty_folders(album)
            save_db(db)
        enqueue_album_match_jobs_for_album(album_id)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.complete_saved"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def reanalyze_album_request(self, album_id):
        queued = []
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            album["folders"] = []
            pending_folder = get_pending_folder(album)
            for photo in album.get("photos", []):
                photo["status"] = "queued"
                apply_photo_folders(photo, [pending_folder], "等待后台重新识别")
                queued.append(photo.get("id"))
            save_db(db)
        for photo_id in queued:
            enqueue_photo_job(album_id, photo_id)
        LOGGER.info("album_id=%s", album_id, extra={"event": "album.reanalyze"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def merge_folder_request(self, album_id, source_folder_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        target_folder_id = (payload.get("targetFolderId") or "").strip()
        if not target_folder_id:
            return self.send_error_json("Missing targetFolderId")

        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            _, merge_error = merge_folder(album, source_folder_id, target_folder_id)
            if merge_error:
                return self.send_error_json(merge_error)
            save_db(db)
        enqueue_album_match_jobs_for_album(album_id)
        LOGGER.info(
            "album_id=%s source_folder_id=%s target_folder_id=%s",
            album_id,
            source_folder_id,
            target_folder_id,
            extra={"event": "folder.merge"},
        )
        return self.send_json({"album": public_album(album, self.current_user())})

    def rename_folder_request(self, album_id, folder_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            _, rename_error = rename_folder(album, folder_id, payload.get("name") or "")
            if rename_error:
                return self.send_error_json(rename_error)
            save_db(db)
        enqueue_album_match_jobs_for_album(album_id)
        LOGGER.info("album_id=%s folder_id=%s", album_id, folder_id, extra={"event": "folder.rename"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def rename_album_request(self, album_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            rename_error = rename_album(album, payload.get("name") or "")
            if rename_error:
                return self.send_error_json(rename_error)
            save_db(db)
        LOGGER.info("album_id=%s", album_id, extra={"event": "album.rename"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def mark_no_face_request(self, album_id, source_folder_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            target = get_no_face_folder(album)
            if source_folder_id == target["id"]:
                return self.send_json({"album": public_album(album, self.current_user())})
            _, merge_error = merge_folder(album, source_folder_id, target["id"])
            if merge_error:
                return self.send_error_json(merge_error)
            save_db(db)
        enqueue_album_match_jobs_for_album(album_id)
        LOGGER.info("album_id=%s source_folder_id=%s", album_id, source_folder_id, extra={"event": "folder.mark_no_face"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def move_photo_request(self, album_id, photo_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        target_folder_id = (payload.get("targetFolderId") or "").strip()
        if not target_folder_id:
            return self.send_error_json("Missing targetFolderId")

        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            _, move_error = move_photo(album, photo_id, target_folder_id)
            if move_error:
                return self.send_error_json(move_error)
            save_db(db)
        enqueue_album_match_jobs_for_album(album_id)
        LOGGER.info(
            "album_id=%s photo_id=%s target_folder_id=%s",
            album_id,
            photo_id,
            target_folder_id,
            extra={"event": "photo.move"},
        )
        return self.send_json({"album": public_album(album, self.current_user())})

    def reclassify_photo_request(self, album_id, photo_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
            if not photo:
                return self.send_error_json("照片不存在", 404)
            photo["status"] = "queued"
            apply_photo_folders(photo, [get_pending_folder(album)], "等待后台重新识别")
            save_db(db)
        enqueue_photo_job(album_id, photo_id)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "photo.reclassify"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def delete_photo_request(self, album_id, photo_id):
        current_user = self.current_user()
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
            if not photo:
                return self.send_error_json("照片不存在", 404)
            if not user_can_delete_photo(album, current_user, photo):
                return self.send_error_json("你没有删除这张照片的权限", 403)
            removed_photo, delete_error = remove_photo(album, photo_id)
            if delete_error:
                return self.send_error_json(delete_error, 404)
            record_album_activity(
                album_id,
                "photo.delete",
                actor=current_user,
                target_type="photo",
                target_id=photo_id,
                message="%s 删除了照片 %s" % (actor_display_name(current_user), photo_display_name(removed_photo)),
                data={"photoId": photo_id, "photoName": photo_display_name(removed_photo)},
                db=db,
            )
            save_db(db)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "photo.delete_request"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def delete_selected_photos(self, album_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        photo_ids = payload.get("photoIds") or []
        if not isinstance(photo_ids, list) or not photo_ids:
            return self.send_error_json("Missing photoIds")
        photo_ids = [str(item) for item in photo_ids if item]

        current_user = self.current_user()
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            deleted = 0
            missing = []
            forbidden = []
            photos_by_id = {photo.get("id"): photo for photo in album.get("photos", [])}
            for photo_id in photo_ids:
                photo = photos_by_id.get(photo_id)
                if not photo:
                    missing.append(photo_id)
                    continue
                if not user_can_delete_photo(album, current_user, photo):
                    forbidden.append(photo_id)
                    continue
                removed_photo, delete_error = remove_photo(album, photo_id)
                if delete_error:
                    missing.append(photo_id)
                else:
                    deleted += 1
                    record_album_activity(
                        album_id,
                        "photo.delete",
                        actor=current_user,
                        target_type="photo",
                        target_id=photo_id,
                        message="%s 删除了照片 %s" % (actor_display_name(current_user), photo_display_name(removed_photo)),
                        data={"photoId": photo_id, "photoName": photo_display_name(removed_photo)},
                        db=db,
                    )
            save_db(db)
        LOGGER.info("album_id=%s deleted=%d missing=%d forbidden=%d", album_id, deleted, len(missing), len(forbidden), extra={"event": "photo.delete_selected"})
        if forbidden and not deleted:
            return self.send_error_json("你没有删除所选照片的权限", 403)
        return self.send_json({"album": public_album(album, self.current_user()), "deleted": deleted, "missing": missing, "forbidden": forbidden})

    def delete_folder_request(self, album_id, folder_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            if not album_member_can(album, self.current_user(), "delete"):
                return self.send_error_json("你没有删除这个小相册的权限", 403)
            result, delete_error = remove_folder(album, folder_id)
            if delete_error:
                return self.send_error_json(delete_error, 404)
            save_db(db)
        LOGGER.info("album_id=%s folder_id=%s", album_id, folder_id, extra={"event": "folder.delete_request"})
        return self.send_json({"album": public_album(album, self.current_user()), "deleted": result})

    def delete_album_request(self, album_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            db["albums"] = [item for item in db["albums"] if item["id"] != album_id]
            if not sqlite_enabled():
                db["albumActivities"] = [item for item in db.get("albumActivities", []) if item.get("albumId") != album_id]
                db["notifications"] = [item for item in db.get("notifications", []) if item.get("albumId") != album_id]
            remove_album_files(album_id, album)
            save_db(db)
        if sqlite_enabled():
            sqlite_init_store()
            with sqlite_connect() as conn:
                with conn:
                    conn.execute("DELETE FROM album_activities WHERE album_id = ?", (album_id,))
                    conn.execute("DELETE FROM notifications WHERE album_id = ?", (album_id,))
        LOGGER.info("album_id=%s", album_id, extra={"event": "album.delete"})
        return self.send_json({"deletedAlbumId": album_id})

    def download_folder(self, album_id, folder_id):
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)
        folder = next((item for item in album["folders"] if item["id"] == folder_id), None)
        if not folder:
            return self.send_error_json("Folder not found", 404)

        photos = [photo for photo in album["photos"] if folder_id in photo_folder_ids(photo)]
        filename = "%s-%s.zip" % (slugify(album["name"]), slugify(folder["name"]))
        used_names = set()
        files = []
        for photo in photos:
            image_item = resource_download_item(album_id, photo, used_names, folder_name=folder["name"])
            if image_item:
                files.append(image_item)
            if photo.get("liveVideoStoredName"):
                video_item = resource_download_item(album_id, photo, used_names, video=True, folder_name=folder["name"])
                if video_item:
                    files.append(video_item)
        LOGGER.info("album_id=%s folder_id=%s files=%d", album_id, folder_id, len(files), extra={"event": "download.manifest"})
        return self.send_json({"type": "folder", "filename": filename, "files": files})

    def download_selected_photos(self, album_id):
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        photo_ids = payload.get("photoIds") or []
        if not isinstance(photo_ids, list) or not photo_ids:
            return self.send_error_json("Missing photoIds")
        photo_ids = [str(item) for item in photo_ids if item]

        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return self.send_error_json("Album not found", 404)

        photos_by_id = {photo["id"]: photo for photo in album.get("photos", [])}
        photos = [photos_by_id[photo_id] for photo_id in photo_ids if photo_id in photos_by_id]
        if not photos:
            return self.send_error_json("No selected photos found", 404)

        filename = "%s-selected-%d.zip" % (slugify(album.get("name") or "photos"), len(photos))
        used_names = set()
        files = []
        for photo in photos:
            image_item = resource_download_item(album_id, photo, used_names)
            if image_item:
                files.append(image_item)
            if photo.get("liveVideoStoredName"):
                video_item = resource_download_item(album_id, photo, used_names, video=True)
                if video_item:
                    files.append(video_item)
        LOGGER.info("album_id=%s selected=%d files=%d", album_id, len(photos), len(files), extra={"event": "download.manifest"})
        return self.send_json({"type": "selection", "filename": filename, "files": files})

    def send_download(self, path, filename, content_type=None):
        if not path.exists() or path.is_dir():
            return self.send_error_json("File not found", 404)
        body = path.read_bytes()
        return self.send_bytes_download(body, filename or path.name, content_type or mimetypes.guess_type(str(path))[0])

    def send_bytes_download(self, body, filename, content_type=None):
        filename = filename or "download"
        ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "download"
        encoded_filename = quote(filename.encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_filename, encoded_filename),
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, content_type, status=200, cache_control="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_apple_app_site_association(self):
        payload = {
            "applinks": {
                "apps": [],
                "details": [
                    {
                        "appIDs": ["%s.%s" % (os.environ.get("APPLE_TEAM_ID", "5FM245WCM5"), IOS_BUNDLE_IDENTIFIER)],
                        "components": [
                            {"/": "/join/*", "comment": "PicMe album invites"}
                        ],
                    }
                ],
            }
        }
        return self.send_bytes(json.dumps(payload, separators=(",", ":")), "application/json")

    def serve_android_assetlinks(self):
        payload = [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": ANDROID_APP_PACKAGE,
                    "sha256_cert_fingerprints": ANDROID_CERT_SHA256,
                },
            }
        ]
        return self.send_bytes(json.dumps(payload, separators=(",", ":")), "application/json")

    def serve_join_landing(self, code):
        clean_code = re.sub(r"[^A-Za-z0-9_-]", "", code).upper()
        row = invite_by_code(clean_code)
        album_name = "PicMe 共享相册"
        photo_count = ""
        if row:
            with LOCK:
                album = find_album(load_db(), row["album_id"])
            if album:
                album_name = album.get("name") or album_name
                photo_count = "%d 张照片" % len(album.get("photos", []))
        share_url = urljoin(self.request_origin(), "/join/%s" % quote(clean_code))
        fallback_url = urljoin(self.request_origin(), "/?invite=%s" % quote(clean_code))
        intent_url = "intent://%s/join/%s#Intent;scheme=https;package=%s;S.browser_fallback_url=%s;end" % (
            APP_ASSOCIATED_DOMAIN,
            quote(clean_code),
            ANDROID_APP_PACKAGE,
            quote(fallback_url, safe=""),
        )
        logo_url = urljoin(self.request_origin(), SHARE_IMAGE_PATH)
        page_title = "加入 PicMe 相册：%s" % album_name
        page_description = photo_count or "好友邀请你加入 PicMe 旅行共享相册"
        download_url = APP_DOWNLOAD_URL or "#"
        body = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>加入%s</title>
  <meta name="description" content="%s" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="PicMe" />
  <meta property="og:title" content="%s" />
  <meta property="og:description" content="%s" />
  <meta property="og:url" content="%s" />
  <meta property="og:image" content="%s" />
  <meta property="og:image:width" content="512" />
  <meta property="og:image:height" content="512" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="%s" />
  <meta name="twitter:description" content="%s" />
  <meta name="twitter:image" content="%s" />
  <link rel="apple-touch-icon" href="%s" />
  <link rel="preload" as="image" href="%s" />
  <link rel="icon" href="/assets/logo.png?v=transparent-1" type="image/png" />
  <link rel="stylesheet" href="/assets/styles.css?v=share-invite-1" />
</head>
<body>
  <main class="join-landing">
    <section class="join-card">
      <img src="/assets/logo.png?v=transparent-1" alt="PicMe" class="join-logo" />
      <p class="eyebrow">PicMe album invite</p>
      <h1>%s</h1>
      <p>%s</p>
      <strong class="join-code">%s</strong>
      <div class="join-actions">
        <a class="join-primary" data-universal-link="%s" data-android-intent="%s" href="%s">打开识我 App</a>
        <a class="join-secondary" href="/?invite=%s">网页登录并申请加入</a>
        <a class="join-secondary" href="%s">%s</a>
      </div>
      <p class="join-hint">如果已经安装 App，点击上方按钮会直接打开对应相册；未安装时请先下载 App，或在网页端登录后提交加入申请。</p>
    </section>
  </main>
  <script>
    (function () {
      var link = document.querySelector(".join-primary");
      if (!link) return;
      if (/Android/i.test(navigator.userAgent)) {
        link.href = link.dataset.androidIntent || link.href;
      } else {
        link.href = link.dataset.universalLink || link.href;
      }
    })();
    window.setTimeout(function () {
      if (!document.hidden) return;
    }, 1200);
  </script>
</body>
</html>""" % (
            html.escape(album_name),
            html.escape(page_description),
            html.escape(page_title),
            html.escape(page_description),
            html.escape(share_url),
            html.escape(logo_url),
            html.escape(page_title),
            html.escape(page_description),
            html.escape(logo_url),
            html.escape(logo_url),
            html.escape(SHARE_IMAGE_PATH),
            html.escape(album_name),
            html.escape(photo_count or "好友邀请你加入这个旅行相册"),
            html.escape(clean_code),
            html.escape(share_url),
            html.escape(intent_url),
            html.escape(share_url),
            quote(clean_code),
            html.escape(download_url),
            "下载识我 App" if APP_DOWNLOAD_URL else "下载链接准备中",
        )
        return self.send_bytes(body, "text/html; charset=utf-8", cache_control="private, max-age=60")

    def serve_invite_qr(self, code):
        clean_code = re.sub(r"[^A-Za-z0-9_-]", "", code).upper()
        if not invite_by_code(clean_code):
            return self.send_error_json("相册码无效或已失效", 404)
        share_url = urljoin(self.request_origin(), "/join/%s" % quote(clean_code))
        if qrcode:
            image = qrcode.make(share_url, image_factory=qrcode.image.svg.SvgImage)
            out = tempfile.NamedTemporaryFile(prefix="picme-qr-", suffix=".svg", delete=False)
            out.close()
            target = Path(out.name)
            try:
                image.save(str(target))
                body = target.read_bytes()
            finally:
                target.unlink(missing_ok=True)
        else:
            body = '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320"><rect width="100%" height="100%" fill="white"/><text x="20" y="160" font-size="22">%s</text></svg>' % html.escape(clean_code)
        return self.send_bytes(body, "image/svg+xml; charset=utf-8", cache_control="private, max-age=300")

    def find_photo_for_download(self, album_id, photo_id):
        with LOCK:
            album = find_album(load_db(), album_id)
        if not album:
            return None, None
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        return album, photo

    def download_photo_image(self, album_id, photo_id):
        _, photo = self.find_photo_for_download(album_id, photo_id)
        if not photo:
            return self.send_error_json("Photo not found", 404)
        item = resource_download_item(album_id, photo)
        if not item:
            return self.send_error_json("File not found", 404)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "download.manifest"})
        return self.send_json({"type": "photo", **item})

    def download_live_photo(self, album_id, photo_id):
        album, photo = self.find_photo_for_download(album_id, photo_id)
        if not album or not photo:
            return self.send_error_json("Photo not found", 404)
        video_name = photo.get("liveVideoStoredName")
        if photo.get("type") != "live_photo" or not video_name:
            return self.send_error_json("不是 Live Photo")
        image_item = resource_download_item(album_id, photo)
        video_item = resource_download_item(album_id, photo, video=True)
        if not image_item or not video_item:
            return self.send_error_json("Live Photo 文件不完整", 404)
        filename = "%s-live.zip" % slugify(Path(photo.get("originalName") or "live-photo").stem)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "download.manifest"})
        return self.send_json({
            "type": "live_photo",
            "filename": filename,
            "image": image_item,
            "video": video_item,
            "files": [image_item, video_item],
        })

    def serve_file(self, path):
        path = path.resolve()
        allowed = [PUBLIC.resolve(), UPLOADS.resolve(), PREVIEWS.resolve(), AVATARS.resolve()]
        if not any(str(path).startswith(str(root)) for root in allowed) or not path.exists() or path.is_dir():
            return self.send_error_json("Not found", 404)
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body = path.read_bytes()
        public_root = PUBLIC.resolve()
        is_public_asset = str(path).startswith(str(public_root)) and path.name != "index.html"
        stat = path.stat()
        etag = '"%s-%s"' % (int(stat.st_mtime), stat.st_size)
        if is_public_asset and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if is_public_asset:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", self.date_time_string(stat.st_mtime))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_preview(self, album_id, stored_name):
        stored_name = Path(stored_name).name
        path = generate_preview(album_id, stored_name)
        if not path:
            path = generate_thumbnail(album_id, stored_name, "cover")
        if not path:
            return self.serve_file(UPLOADS / album_id / stored_name)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_thumbnail(self, album_id, size, stored_name):
        stored_name = Path(stored_name).name
        path = generate_thumbnail(album_id, stored_name, size)
        if not path:
            return self.serve_file(UPLOADS / album_id / stored_name)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_face_thumbnail(self, album_id, stored_name):
        stored_name = Path(stored_name).name
        path = generate_face_thumbnail(album_id, stored_name)
        if not path:
            path = generate_thumbnail(album_id, stored_name, "cover")
        if not path:
            return self.serve_file(UPLOADS / album_id / stored_name)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ensure_store()
    log_startup_config("server")
    if FACE_WORKER_MODE == "redis" and not use_redis_queue():
        raise RuntimeError("FACE_WORKER_MODE=redis 但 Redis 不可用，请检查 REDIS_URL 或改用 inline 模式")
    if FACE_WORKER_MODE not in {"redis", "remote"}:
        threading.Thread(target=photo_worker, daemon=True).start()
    enqueue_pending_jobs()
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    LOGGER.info("url=http://localhost:%d", port, extra={"event": "server.start"})
    httpd.serve_forever()


if __name__ == "__main__":
    main()
