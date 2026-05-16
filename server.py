#!/usr/bin/env python3
import cgi
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

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
QUEUED_PHOTOS = set()
REDIS_HOST = os.environ.get("REDIS_HOST", "redis").strip() or "redis"
REDIS_PORT = os.environ.get("REDIS_PORT", "6379").strip() or "6379"
REDIS_DB = os.environ.get("REDIS_DB", "0").strip() or "0"
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
if not REDIS_URL and REDIS_PASSWORD:
    REDIS_URL = "redis://:%s@%s:%s/%s" % (REDIS_PASSWORD, REDIS_HOST, REDIS_PORT, REDIS_DB)
FACE_QUEUE_NAME = os.environ.get("FACE_QUEUE_NAME", "sharephotos:face:jobs").strip() or "sharephotos:face:jobs"
FACE_QUEUE_SET_NAME = os.environ.get("FACE_QUEUE_SET_NAME", "%s:queued" % FACE_QUEUE_NAME).strip() or "%s:queued" % FACE_QUEUE_NAME
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
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES(?, ?)",
            ("schema_version", "2"),
        )


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
                conn.execute(
                    """
                    INSERT OR REPLACE INTO users(
                        id, username, nickname, password_hash, avatar_url,
                        avatar_object_key, has_face_profile, data_json, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        user.get("nickname") or username,
                        user.get("passwordHash") or user.get("password_hash") or "",
                        user.get("avatarUrl") or user.get("avatar_url") or "",
                        user.get("avatarObjectKey") or user.get("avatar_object_key") or "",
                        1 if user.get("hasFaceProfile") else 0,
                        json.dumps(user, ensure_ascii=False, separators=(",", ":")),
                        int(user.get("createdAt") or 0),
                    ),
                )


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
    sync_all_folder_covers(db)
    write_db(db)
    LOGGER.info("albums=%d", len(db.get("albums", [])), extra={"event": "db.write"})


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")
PASSWORD_RE = re.compile(r"^[\x21-\x7E]{6,20}$")
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20
AUTH_TOKEN_TTL_SECONDS = int(os.environ.get("AUTH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 30)))


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


def create_auth_token(user_id):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    token_hash = hash_auth_token(token)
    now = int(time.time())
    expires_at = now + AUTH_TOKEN_TTL_SECONDS
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            with conn:
                conn.execute(
                    "DELETE FROM auth_tokens WHERE expires_at < ?",
                    (now,),
                )
                conn.execute(
                    "INSERT INTO auth_tokens(token_hash, user_id, created_at, expires_at) VALUES(?, ?, ?, ?)",
                    (token_hash, user_id, now, expires_at),
                )
    else:
        db = load_db()
        db["authTokens"] = [
            item for item in db.get("authTokens", [])
            if int(item.get("expiresAt") or 0) >= now
        ]
        db["authTokens"].append({"tokenHash": token_hash, "userId": user_id, "createdAt": now, "expiresAt": expires_at})
        write_db(db)
    return token


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


def user_for_token(token):
    if not token:
        return None
    token_hash = hash_auth_token(token)
    now = int(time.time())
    if sqlite_enabled():
        sqlite_init_store()
        with sqlite_connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM auth_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            if int(row["expires_at"]) < now:
                with conn:
                    conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
                return None
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

    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    face_w = max(1.0, x2 - x1)
    face_h = max(1.0, y2 - y1)
    size = max(face_w, face_h) * 2.15
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 - face_h * 0.08
    left = int(max(0, round(cx - size / 2)))
    top = int(max(0, round(cy - size / 2)))
    right = int(min(width, round(cx + size / 2)))
    bottom = int(min(height, round(cy + size / 2)))
    if right <= left or bottom <= top:
        return None

    crop = image[top:bottom, left:right]
    crop = cv2.resize(crop, (420, 420), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
    if not ok:
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
        height, width = image.shape[:2]
        x1, y1, x2, y2 = box
        face_w = max(1.0, x2 - x1)
        face_h = max(1.0, y2 - y1)
        size = max(face_w, face_h) * 2.15
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2 - face_h * 0.08
        left = int(max(0, round(cx - size / 2)))
        top = int(max(0, round(cy - size / 2)))
        right = int(min(width, round(cx + size / 2)))
        bottom = int(min(height, round(cy + size / 2)))
        if right <= left or bottom <= top:
            return None
        crop = cv2.resize(image[top:bottom, left:right], (420, 420), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        if not ok:
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
    if folder_uses_scene_cover(folder):
        return item.get("coverUrl") or item.get("cardUrl") or item.get("imageUrl") or ""
    return item.get("faceUrl") or item.get("coverUrl") or item.get("cardUrl") or item.get("imageUrl") or ""


def folder_cover_object_key(folder, photo):
    if not photo or not oss_enabled():
        return ""
    if folder_uses_scene_cover(folder):
        return thumb_object_key(photo) or preview_object_key(photo) or original_object_key(photo)
    return face_object_key(photo) or thumb_object_key(photo) or preview_object_key(photo) or original_object_key(photo)


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
    visible = dict(album)
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
    user_embedding = (current_user or {}).get("avatarEmbedding")
    user_engine = (current_user or {}).get("avatarEmbeddingEngine")
    if not user_embedding or not user_engine:
        visible["myPhotoIds"] = []
        visible["myPhotoCount"] = 0
        visible["myCoverUrl"] = ""
        return
    best_folder = None
    best_distance = 999.0
    for folder in album.get("folders", []):
        if folder.get("id") in {"pending", "group-photo", "no-face"}:
            continue
        if folder.get("embeddingEngine") != user_engine or not folder.get("embedding"):
            continue
        distance = cosine_distance(user_embedding, folder.get("embedding"))
        if distance < best_distance:
            best_distance = distance
            best_folder = folder
    threshold = INSIGHTFACE_MATCH_THRESHOLD if user_engine == "insightface" else OPENCV_MATCH_THRESHOLD
    if not best_folder or best_distance > threshold:
        visible["myPhotoIds"] = []
        visible["myPhotoCount"] = 0
        visible["myCoverUrl"] = ""
        return
    folder_id = best_folder["id"]
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
            user["hasFaceProfile"] = True
        else:
            user["hasFaceProfile"] = False
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


FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
OPENCV_MATCH_THRESHOLD = 0.46
INSIGHTFACE_MATCH_THRESHOLD = 0.55
INSIGHTFACE_MIN_DET_SCORE = 0.42
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
    if meta.get("engine") == "insightface":
        return embedding, note, meta
    return extract_opencv_embedding(image_path)


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
    current = folder.get("embedding")
    count = int(folder.get("embeddingCount") or 0)
    if not current or count <= 0:
        folder["embedding"] = embedding
        folder["embeddingEngine"] = engine
        folder["embeddingCount"] = 1
        return
    updated = ((np.asarray(current, dtype=np.float32) * count) + np.asarray(embedding, dtype=np.float32)) / (count + 1)
    norm = float(np.linalg.norm(updated)) + 1e-6
    folder["embedding"] = (updated / norm).round(6).tolist()
    folder["embeddingEngine"] = engine
    folder["embeddingCount"] = count + 1


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
        return
    merged = (
        (np.asarray(target_embedding, dtype=np.float32) * target_count)
        + (np.asarray(source_embedding, dtype=np.float32) * source_count)
    ) / (target_count + source_count)
    norm = float(np.linalg.norm(merged)) + 1e-6
    target["embedding"] = (merged / norm).round(6).tolist()
    target["embeddingCount"] = target_count + source_count


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


def push_face_job(album_id, photo_id):
    payload = json.dumps({"albumId": album_id, "photoId": photo_id}, ensure_ascii=False)
    if use_redis_queue():
        REDIS_CLIENT.lpush(FACE_QUEUE_NAME, payload)
        LOGGER.info("album_id=%s photo_id=%s queue=%s", album_id, photo_id, FACE_QUEUE_NAME, extra={"event": "redis.enqueue"})
    else:
        JOB_QUEUE.put((album_id, photo_id))
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "queue.enqueue"})


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
            return payload.get("albumId"), payload.get("photoId")
        except Exception as error:
            LOGGER.warning("error=%s", error, extra={"event": "redis.dequeue_invalid"})
            return None
    try:
        job = JOB_QUEUE.get(timeout=max(float(timeout), 0.1))
        LOGGER.info("album_id=%s photo_id=%s", job[0], job[1], extra={"event": "queue.dequeue"})
        return job
    except queue.Empty:
        return None


def enqueue_photo_job(album_id, photo_id):
    if use_remote_worker():
        return
    key = (album_id, photo_id)
    if use_redis_queue():
        added = REDIS_CLIENT.sadd(FACE_QUEUE_SET_NAME, "%s:%s" % key)
        if not added:
            LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "queue.duplicate"})
            return
    else:
        with LOCK:
            if key in QUEUED_PHOTOS:
                LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "queue.duplicate"})
                return
            QUEUED_PHOTOS.add(key)
    push_face_job(album_id, photo_id)


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
        if not source:
            raise ValueError("图片源文件不存在")
        generate_preview_for_photo(album_id, photo, source)
        generate_thumbnail_for_photo(album_id, photo, source)
        derivative_updates = {
            key: value for key, value in photo.items()
            if key.startswith(("preview", "thumb")) or key.startswith(("preview_", "thumb_"))
        }
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
        readable, cleanup_readable = readable_source_for_path(source) if source else (None, lambda: None)
        if not readable:
            raise ValueError("图片无法生成预览图")
        try:
            analysis = analyze_photo_faces(readable)
        finally:
            cleanup_readable()
    except Exception as error:
        analysis = {"status": "failed", "note": str(error)}
        LOGGER.exception("album_id=%s photo_id=%s error=%s", album_id, photo_id, error, extra={"event": "face.analysis_failed"})

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
        apply_face_analysis(album, photo, analysis)
        face_user_id = next((item for item in photo_folder_ids(photo) if item not in {"group-photo", "no-face", "pending"}), album_id)
        try:
            if source:
                generate_face_thumbnail_for_photo(album_id, photo, source, face_user_id)
        except Exception as error:
            LOGGER.warning("album_id=%s photo_id=%s error=%s", album_id, photo_id, error, extra={"event": "face.thumb_failed"})
        prune_empty_folders(album)
        save_db(db)
    cleanup_source()
    LOGGER.info("album_id=%s photo_id=%s status=%s", album_id, photo_id, analysis.get("status"), extra={"event": "worker.process_complete"})


def photo_worker():
    while True:
        job = pop_face_job(timeout=3)
        if not job:
            continue
        album_id, photo_id = job
        if not album_id or not photo_id:
            continue
        try:
            process_photo_job(album_id, photo_id)
        finally:
            if use_redis_queue():
                REDIS_CLIENT.srem(FACE_QUEUE_SET_NAME, "%s:%s" % (album_id, photo_id))
                LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "redis.complete"})
            else:
                with LOCK:
                    QUEUED_PHOTOS.discard((album_id, photo_id))
                JOB_QUEUE.task_done()
                LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "queue.complete"})


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
    app = get_insightface_app()
    if app:
        image = cv2.imread(str(image_path))
        if image is None:
            return {"status": "failed", "note": "图片无法读取"}
        faces, filter_stats = filter_subject_faces(app.get(image), image.shape)
        if not faces:
            LOGGER.info(
                "path=%s raw_faces=%s filtered_faces=%s",
                Path(image_path).name,
                filter_stats.get("raw", 0),
                filter_stats.get("filtered", 0),
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
            "path=%s face_count=%d raw_faces=%s filtered_faces=%s",
            Path(image_path).name,
            result["faceCount"],
            result["rawFaceCount"],
            result["filteredFaceCount"],
            extra={"event": "face.analysis_result"},
        )
        return result

    embedding, note, meta = extract_opencv_embedding(image_path)
    if not embedding:
        LOGGER.info("path=%s note=%s", Path(image_path).name, note, extra={"event": "face.analysis_result"})
        return {"status": "no_face", "note": note, "engine": meta.get("engine") or "opencv", "faces": []}
    result = {
        "status": "ready",
        "engine": meta.get("engine") or "opencv",
        "faceCount": 1,
        "embeddings": [embedding],
        "note": "",
    }
    LOGGER.info("path=%s engine=%s face_count=1", Path(image_path).name, result["engine"], extra={"event": "face.analysis_result"})
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            LOGGER.info("method=GET path=%s", path, extra={"event": "api.request"})
        if path == "/":
            return self.serve_file(PUBLIC / "index.html")
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
        if path == "/api/albums":
            current_user = self.require_user()
            if not current_user:
                return
            with LOCK:
                db = load_db()
            return self.send_json({"albums": [public_album(album, current_user) for album in db["albums"]]})
        match = re.match(r"^/api/worker/jobs/([^/]+)/([^/]+)$", path)
        if match:
            return self.get_worker_job(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)$", path)
        if match:
            current_user = self.require_user()
            if not current_user:
                return
            with LOCK:
                album = find_album(load_db(), match.group(1))
            if not album:
                return self.send_error_json("Album not found", 404)
            return self.send_json({"album": public_album(album, current_user)})
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/download$", path)
        if match:
            if not self.require_user():
                return
            return self.download_folder(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-image$", path)
        if match:
            if not self.require_user():
                return
            return self.download_photo_image(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-live$", path)
        if match:
            if not self.require_user():
                return
            return self.download_live_photo(match.group(1), match.group(2))
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
        if path == "/api/auth/logout":
            return self.logout_user_request()
        if path == "/api/worker/jobs/claim":
            return self.claim_worker_job()
        match = re.match(r"^/api/worker/jobs/([^/]+)/([^/]+)/complete$", path)
        if match:
            return self.complete_worker_job(match.group(1), match.group(2))
        current_user = self.require_user()
        if not current_user:
            return
        if path == "/api/me/avatar":
            return self.update_avatar_request(current_user)
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
                "folders": [],
                "photos": [],
                "contributors": [],
            }
            with LOCK:
                db = load_db()
                db["albums"].insert(0, album)
                save_db(db)
            LOGGER.info("album_id=%s name=%s", album["id"], album["name"], extra={"event": "album.create"})
            (UPLOADS / album["id"]).mkdir(parents=True, exist_ok=True)
            return self.send_json({"album": public_album(album, current_user)}, 201)

        match = re.match(r"^/api/albums/([^/]+)/upload$", path)
        if match:
            return self.upload_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/uploads/init$", path)
        if match:
            return self.init_direct_uploads(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/uploads/complete$", path)
        if match:
            return self.complete_direct_uploads(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/rename$", path)
        if match:
            return self.rename_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/reanalyze$", path)
        if match:
            return self.reanalyze_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/photos/download-selected$", path)
        if match:
            return self.download_selected_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/photos/delete-selected$", path)
        if match:
            return self.delete_selected_photos(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/merge$", path)
        if match:
            return self.merge_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/rename$", path)
        if match:
            return self.rename_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/mark-no-face$", path)
        if match:
            return self.mark_no_face_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/move$", path)
        if match:
            return self.move_photo_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/reclassify$", path)
        if match:
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
            return self.delete_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)$", path)
        if match:
            return self.delete_folder_request(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)$", path)
        if match:
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
                    warning = save_avatar_profile(user, avatar_source)
                finally:
                    avatar_source.unlink(missing_ok=True)
            upsert_user(db, user)
            save_db(db)
        token = create_auth_token(user["id"])
        LOGGER.info("user_id=%s username=%s face=%s", user["id"], username, user.get("hasFaceProfile"), extra={"event": "auth.register"})
        payload = {"user": public_user(user, self.request_origin()), "token": token}
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
        token = create_auth_token(user["id"])
        LOGGER.info("user_id=%s username=%s", user["id"], username, extra={"event": "auth.login"})
        return self.send_json({"user": public_user(user, self.request_origin()), "token": token})

    def logout_user_request(self):
        token = self.bearer_token()
        if token:
            delete_auth_token(token)
        return self.send_json({"ok": True})

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
                warning = save_avatar_profile(user, avatar_source)
                upsert_user(db, user)
                save_db(db)
            self._current_user = user
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
        return self.send_json({"photos": response_created, "album": response_album, "queued": len(queued), "ignored": 0}, 202)

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
        return self.send_json({"photos": response_created, "album": response_album, "queued": len(created), "ignored": ignored}, 202)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}"), ""
        except json.JSONDecodeError:
            return None, "Invalid JSON"

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
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.complete_saved"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def reanalyze_album_request(self, album_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            reanalyze_album(album)
            save_db(db)
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
            _, reclassify_error = reclassify_photo(album, photo_id)
            if reclassify_error:
                return self.send_error_json(reclassify_error)
            save_db(db)
        LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "photo.reclassify"})
        return self.send_json({"album": public_album(album, self.current_user())})

    def delete_photo_request(self, album_id, photo_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            _, delete_error = remove_photo(album, photo_id)
            if delete_error:
                return self.send_error_json(delete_error, 404)
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

        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            deleted = 0
            missing = []
            for photo_id in photo_ids:
                _, delete_error = remove_photo(album, photo_id)
                if delete_error:
                    missing.append(photo_id)
                else:
                    deleted += 1
            save_db(db)
        LOGGER.info("album_id=%s deleted=%d missing=%d", album_id, deleted, len(missing), extra={"event": "photo.delete_selected"})
        return self.send_json({"album": public_album(album, self.current_user()), "deleted": deleted, "missing": missing})

    def delete_folder_request(self, album_id, folder_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
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
            remove_album_files(album_id, album)
            save_db(db)
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
        self.send_response(200)
        self.send_header("Content-Type", content_type)
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
