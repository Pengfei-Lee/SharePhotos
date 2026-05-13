#!/usr/bin/env python3
import cgi
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
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
DB_FILE = DATA / "db.json"


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
    except Exception:
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
    OSS_SIGNED_URL_EXPIRES = int(os.environ.get("OSS_SIGNED_URL_EXPIRES", "3600") or "3600")
except (TypeError, ValueError):
    print("Invalid OSS_SIGNED_URL_EXPIRES, fallback to 3600")
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
            print("OSS upload failed for %s: %s" % (object_key, error))
            return {}
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
            except Exception:
                pass

    def generateSignedUrl(self, object_key, expires=None):
        if not self.enabled() or not object_key:
            return ""
        return self.bucket.sign_url("GET", object_key, int(expires or self.expires), slash_safe=True)

    def downloadFile(self, object_key, target):
        if not self.enabled() or not object_key:
            return None
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.bucket.get_object_to_file(object_key, str(target))
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
    if not prefix:
        target["object_key"] = metadata.get("object_key", "")
        target["oss_url"] = metadata.get("oss_url", "")
        target["resource_type"] = metadata.get("resource_type", "")
        target["mime_type"] = metadata.get("mime_type", "")
        target["file_size"] = metadata.get("file_size", 0)
    else:
        snake_prefix = re.sub(r"(?<!^)(?=[A-Z])", "_", prefix).lower()
        target["%s_object_key" % snake_prefix] = metadata.get("object_key", "")
        target["%s_oss_url" % snake_prefix] = metadata.get("oss_url", "")
        target["%s_resource_type" % snake_prefix] = metadata.get("resource_type", "")
        target["%s_mime_type" % snake_prefix] = metadata.get("mime_type", "")
        target["%s_file_size" % snake_prefix] = metadata.get("file_size", 0)


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


def ensure_store():
    DATA.mkdir(exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    THUMBS.mkdir(exist_ok=True)
    PREVIEWS.mkdir(exist_ok=True)
    if not DB_FILE.exists():
        save_db({"albums": []})


def load_db():
    ensure_store()
    with DB_FILE.open("r", encoding="utf-8") as fh:
        db = json.load(fh)
    if OSS_AUTO_MIGRATE and migrate_local_resources_to_oss(db):
        write_db(db)
    if sync_all_folder_covers(db):
        write_db(db)
    return db


def write_db(db):
    DATA.mkdir(exist_ok=True)
    tmp = DB_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=2)
    tmp.replace(DB_FILE)


def save_db(db):
    sync_all_folder_covers(db)
    write_db(db)


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
        return OSS_SERVICE.bucket.get_object(object_key).read()
    except Exception:
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
        faces = [face for face in app.get(image) if float(getattr(face, "det_score", 0.0)) >= 0.42]
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
    except Exception:
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


def public_album(album):
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
    return visible


FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
EYE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
OPENCV_MATCH_THRESHOLD = 0.46
INSIGHTFACE_MATCH_THRESHOLD = 0.55
INSIGHTFACE_APP = None
INSIGHTFACE_READY = False


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
        print("InsightFace unavailable, falling back to OpenCV: %s" % error)
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
    faces = app.get(image)
    if not faces:
        return None, "未检测到人脸", {"engine": "insightface"}

    # Pick the most confident primary face. This demo still assigns one photo
    # to one folder; production can duplicate group photos into multiple people.
    face = max(faces, key=lambda item: (float(getattr(item, "det_score", 0.0)), bbox_area(item.bbox)))
    score = float(getattr(face, "det_score", 0.0))
    if score < 0.42:
        return None, "人脸置信度过低", {"engine": "insightface", "score": score}
    embedding = np.asarray(face.normed_embedding, dtype=np.float32)
    norm = float(np.linalg.norm(embedding)) + 1e-6
    return (embedding / norm).round(6).tolist(), "", {
        "engine": "insightface",
        "score": round(score, 4),
        "faces": len(faces),
    }


def bbox_area(bbox):
    return max(0.0, float(bbox[2] - bbox[0])) * max(0.0, float(bbox[3] - bbox[1]))


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
    else:
        JOB_QUEUE.put((album_id, photo_id))


def pop_face_job(timeout=3):
    if use_redis_queue():
        item = REDIS_CLIENT.brpop(FACE_QUEUE_NAME, timeout=max(int(timeout), 1))
        if not item:
            return None
        try:
            payload = json.loads(item[1])
            return payload.get("albumId"), payload.get("photoId")
        except Exception:
            return None
    try:
        return JOB_QUEUE.get(timeout=max(float(timeout), 0.1))
    except queue.Empty:
        return None


def enqueue_photo_job(album_id, photo_id):
    if use_remote_worker():
        return
    key = (album_id, photo_id)
    if use_redis_queue():
        added = REDIS_CLIENT.sadd(FACE_QUEUE_SET_NAME, "%s:%s" % key)
        if not added:
            return
    else:
        with LOCK:
            if key in QUEUED_PHOTOS:
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
        except Exception:
            pass
        prune_empty_folders(album)
        save_db(db)
    cleanup_source()


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
            else:
                with LOCK:
                    QUEUED_PHOTOS.discard((album_id, photo_id))
                JOB_QUEUE.task_done()


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
        faces = [face for face in app.get(image) if float(getattr(face, "det_score", 0.0)) >= 0.42]
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
        faces = [face for face in app.get(image) if float(getattr(face, "det_score", 0.0)) >= 0.42]
        if not faces:
            return {"status": "no_face", "note": "未检测到人脸", "engine": "insightface", "faces": []}
        faces = sorted(faces, key=lambda face: bbox_area(face.bbox), reverse=True)
        embeddings = []
        for face in faces:
            embedding = np.asarray(face.normed_embedding, dtype=np.float32)
            norm = float(np.linalg.norm(embedding)) + 1e-6
            embeddings.append((embedding / norm).round(6).tolist())
        return {
            "status": "ready",
            "engine": "insightface",
            "faceCount": len(embeddings),
            "embeddings": embeddings,
            "note": "",
        }

    embedding, note, meta = extract_opencv_embedding(image_path)
    if not embedding:
        return {"status": "no_face", "note": note, "engine": meta.get("engine") or "opencv", "faces": []}
    return {
        "status": "ready",
        "engine": meta.get("engine") or "opencv",
        "faceCount": 1,
        "embeddings": [embedding],
        "note": "",
    }


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
        apply_photo_folders(photo, person_folders, notes[0] if notes else "匹配到已有人物（%s）" % engine)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SharedAlbumDemo/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status)

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
        if path == "/api/albums":
            with LOCK:
                db = load_db()
            return self.send_json({"albums": [public_album(album) for album in db["albums"]]})
        match = re.match(r"^/api/albums/([^/]+)$", path)
        if match:
            with LOCK:
                album = find_album(load_db(), match.group(1))
            if not album:
                return self.send_error_json("Album not found", 404)
            return self.send_json({"album": public_album(album)})
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/download$", path)
        if match:
            return self.download_folder(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-image$", path)
        if match:
            return self.download_photo_image(match.group(1), match.group(2))
        match = re.match(r"^/api/albums/([^/]+)/photos/([^/]+)/download-live$", path)
        if match:
            return self.download_live_photo(match.group(1), match.group(2))
        return self.send_error_json("Not found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/worker/jobs/claim":
            return self.claim_worker_job()
        match = re.match(r"^/api/worker/jobs/([^/]+)/([^/]+)/complete$", path)
        if match:
            return self.complete_worker_job(match.group(1), match.group(2))
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
            (UPLOADS / album["id"]).mkdir(parents=True, exist_ok=True)
            return self.send_json({"album": public_album(album)}, 201)

        match = re.match(r"^/api/albums/([^/]+)/upload$", path)
        if match:
            return self.upload_photos(match.group(1))
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

    def upload_photos(self, album_id):
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
                if oss_enabled():
                    tmp = tempfile.NamedTemporaryFile(prefix="picme-upload-", suffix=suffix, delete=False)
                    tmp.close()
                    target = Path(tmp.name)
                    try:
                        with target.open("wb") as out:
                            shutil.copyfileobj(image_file.file, out)
                        object_key = OSS_SERVICE.generateObjectKey("original", album_id=album_id, photo_id=photo_id, ext=suffix)
                        image_metadata = OSS_SERVICE.uploadFile(target, object_key, mime_type, "original")
                    finally:
                        target.unlink(missing_ok=True)
                    if not image_metadata:
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
            save_db(db)
            response_album = public_album(album)
            response_created = [
                item for item in response_album.get("photos", [])
                if item.get("id") in queued
            ]
        for photo_id in queued:
            enqueue_photo_job(album_id, photo_id)
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
                    return self.send_json({
                        "job": {
                            "albumId": album["id"],
                            "photoId": photo["id"],
                            "photo": public_photo,
                            "sourceUrl": source_url,
                        }
                    })
        return self.send_json({"job": None})

    def complete_worker_job(self, album_id, photo_id):
        if not self.worker_authorized():
            return
        payload, error = self.read_json_body()
        if error:
            return self.send_error_json(error)
        analysis = payload.get("analysis") or payload
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
            if not photo:
                return self.send_error_json("Photo not found", 404)
            apply_face_analysis(album, photo, analysis)
            source, cleanup_source = materialize_photo_source(album_id, photo)
            if source:
                try:
                    face_user_id = next((item for item in photo_folder_ids(photo) if item not in {"group-photo", "no-face", "pending"}), album_id)
                    generate_face_thumbnail_for_photo(album_id, photo, source, face_user_id)
                finally:
                    cleanup_source()
            prune_empty_folders(album)
            save_db(db)
        return self.send_json({"album": public_album(album)})

    def reanalyze_album_request(self, album_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            reanalyze_album(album)
            save_db(db)
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

    def mark_no_face_request(self, album_id, source_folder_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            target = get_no_face_folder(album)
            if source_folder_id == target["id"]:
                return self.send_json({"album": public_album(album)})
            _, merge_error = merge_folder(album, source_folder_id, target["id"])
            if merge_error:
                return self.send_error_json(merge_error)
            save_db(db)
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album)})

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
        return self.send_json({"album": public_album(album), "deleted": deleted, "missing": missing})

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
        return self.send_json({"album": public_album(album), "deleted": result})

    def delete_album_request(self, album_id):
        with LOCK:
            db = load_db()
            album = find_album(db, album_id)
            if not album:
                return self.send_error_json("Album not found", 404)
            db["albums"] = [item for item in db["albums"] if item["id"] != album_id]
            remove_album_files(album_id, album)
            save_db(db)
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
        zip_path = DATA / ("%s-%s.zip" % (album_id, folder_id))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for photo in photos:
                write_resource_to_archive(archive, album_id, photo, used_names, folder_name=folder["name"])
                if photo.get("liveVideoStoredName"):
                    write_resource_to_archive(archive, album_id, photo, used_names, video=True, folder_name=folder["name"])

        body = zip_path.read_bytes()
        filename = "%s-%s.zip" % (slugify(album["name"]), slugify(folder["name"]))
        ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "photos.zip"
        encoded_filename = quote(filename.encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_filename, encoded_filename),
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

        zip_path = DATA / ("%s-selected-%s.zip" % (album_id, uuid.uuid4().hex[:8]))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for photo in photos:
                write_resource_to_archive(archive, album_id, photo, used_names)
                if photo.get("liveVideoStoredName"):
                    write_resource_to_archive(archive, album_id, photo, used_names, video=True)

        filename = "%s-selected-%d.zip" % (slugify(album.get("name") or "photos"), len(photos))
        return self.send_download(zip_path, filename, "application/zip")

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
        source = UPLOADS / album_id / photo["storedName"]
        if not source.exists() and oss_enabled():
            body = oss_read_bytes(original_object_key(photo))
            if body is not None:
                return self.send_bytes_download(
                    body,
                    photo.get("originalName") or photo["storedName"],
                    photo.get("mime_type") or photo.get("mimeType"),
                )
        return self.send_download(source, photo.get("originalName") or photo["storedName"])

    def download_live_photo(self, album_id, photo_id):
        album, photo = self.find_photo_for_download(album_id, photo_id)
        if not album or not photo:
            return self.send_error_json("Photo not found", 404)
        video_name = photo.get("liveVideoStoredName")
        if photo.get("type") != "live_photo" or not video_name:
            return self.send_error_json("不是 Live Photo")
        image_source = UPLOADS / album_id / photo["storedName"]
        video_source = UPLOADS / album_id / video_name
        image_body = None if image_source.exists() else oss_read_bytes(original_object_key(photo))
        video_body = None if video_source.exists() else oss_read_bytes(live_video_object_key(photo))
        if (not image_source.exists() and image_body is None) or (not video_source.exists() and video_body is None):
            return self.send_error_json("Live Photo 文件不完整", 404)
        zip_path = DATA / ("%s-%s-live.zip" % (album_id, photo_id))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if image_source.exists():
                archive.write(image_source, arcname=photo.get("originalName") or photo["storedName"])
            else:
                archive.writestr(photo.get("originalName") or photo["storedName"], image_body)
            if video_source.exists():
                archive.write(video_source, arcname=photo.get("liveVideoOriginalName") or video_name)
            else:
                archive.writestr(photo.get("liveVideoOriginalName") or video_name, video_body)
        filename = "%s-live.zip" % slugify(Path(photo.get("originalName") or "live-photo").stem)
        return self.send_download(zip_path, filename, "application/zip")

    def serve_file(self, path):
        path = path.resolve()
        allowed = [PUBLIC.resolve(), UPLOADS.resolve(), PREVIEWS.resolve()]
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
    if FACE_WORKER_MODE == "redis" and not use_redis_queue():
        raise RuntimeError("FACE_WORKER_MODE=redis 但 Redis 不可用，请检查 REDIS_URL 或改用 inline 模式")
    if FACE_WORKER_MODE not in {"redis", "remote"}:
        threading.Thread(target=photo_worker, daemon=True).start()
    enqueue_pending_jobs()
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print("Shared Album Demo running at http://localhost:%d" % port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
