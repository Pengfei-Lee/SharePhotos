#!/usr/bin/env python3
import cgi
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

os.environ.setdefault("MPLCONFIGDIR", "/tmp/sharephotos-matplotlib")
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import cv2
import numpy as np

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
LOCK = threading.Lock()
JOB_QUEUE = queue.Queue()
QUEUED_PHOTOS = set()
THUMB_SPECS = {
    "tiny": (96, 72),
    "card": (420, 78),
    "cover": (900, 82),
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}
LIVE_IMAGE_EXTS = {".heic", ".heif"}
LIVE_VIDEO_EXTS = {".mov", ".mp4"}

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("video/quicktime", ".mov")


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


def find_album(db, album_id):
    for album in db["albums"]:
        if album["id"] == album_id:
            return album
    return None


def thumb_url(photo, size):
    return "/thumbs/%s/%s/%s" % (photo.get("albumId", ""), size, quote(photo.get("storedName", "")))


def preview_url(photo):
    return "/previews/%s/%s" % (photo.get("albumId", ""), quote(photo.get("storedName", "")))


def photo_public_urls(album_id, photo):
    item = dict(photo)
    item["albumId"] = album_id
    item["tinyUrl"] = thumb_url(item, "tiny")
    item["cardUrl"] = thumb_url(item, "card")
    item["coverUrl"] = thumb_url(item, "cover")
    item["previewUrl"] = preview_url(item)
    item["thumbnailUrl"] = item["cardUrl"]
    item["imageUrl"] = item.get("url") or "/uploads/%s/%s" % (album_id, item.get("storedName", ""))
    item["faceUrl"] = "/face-thumbs/%s/%s" % (album_id, quote(item.get("storedName", "")))
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
            folder["coverUrl"] = folder_cover_url(album["id"], folder, cover_photo)
            folder["cover_url"] = folder["coverUrl"]
        else:
            folder.pop("coverPhotoId", None)
            folder.pop("coverUrl", None)
            folder.pop("cover_url", None)
        after = {
            "photoIds": folder.get("photoIds"),
            "photoCount": folder.get("photoCount"),
            "updatedAt": folder.get("updatedAt"),
            "coverPhotoId": folder.get("coverPhotoId"),
            "coverUrl": folder.get("coverUrl"),
            "cover_url": folder.get("cover_url"),
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
        item["image_url"] = item["imageUrl"]
        item["preview_url"] = item["previewUrl"]
        item["thumbnail_url"] = item["thumbnailUrl"]
        if item.get("liveVideoStoredName"):
            item["videoUrl"] = "/uploads/%s/%s" % (album["id"], item["liveVideoStoredName"])
            item["video_url"] = item["videoUrl"]
            item["downloadLiveUrl"] = "/api/albums/%s/photos/%s/download-live" % (album["id"], item["id"])
        item["downloadImageUrl"] = "/api/albums/%s/photos/%s/download-image" % (album["id"], item["id"])
        item["faceUrl"] = "/face-thumbs/%s/%s" % (album["id"], quote(item.get("storedName", "")))
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


def remove_photo(album, photo_id):
    photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
    if not photo:
        return None, "照片不存在"
    album["photos"] = [item for item in album.get("photos", []) if item["id"] != photo_id]
    still_used = any(item.get("storedName") == photo.get("storedName") for item in album.get("photos", []))
    if not still_used:
        source = UPLOADS / album["id"] / photo["storedName"]
        if source.exists():
            source.unlink()
        remove_thumbnails(album["id"], photo["storedName"])
        remove_preview(album["id"], photo["storedName"])
    video_name = photo.get("liveVideoStoredName")
    if video_name and not any(item.get("liveVideoStoredName") == video_name for item in album.get("photos", [])):
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


def remove_album_files(album_id):
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
    image_path = UPLOADS / album["id"] / photo["storedName"]
    folders, note = classify_photo(album, image_path)
    apply_photo_folders(photo, folders, "重新识别：%s" % note)
    return photo, ""


def reanalyze_album(album):
    previous_names = {folder["id"]: folder.get("name") for folder in album.get("folders", [])}
    photos = sorted(album.get("photos", []), key=lambda item: item.get("createdAt", 0))
    album["folders"] = []
    for photo in photos:
        image_path = UPLOADS / album["id"] / photo["storedName"]
        folders, note = classify_photo(album, image_path)
        apply_photo_folders(photo, folders, "全量重分析：%s" % note)
    for folder in album.get("folders", []):
        previous_name = previous_names.get(folder["id"])
        if previous_name:
            folder["name"] = previous_name
    sync_photo_folder_names(album)
    return album


def enqueue_photo_job(album_id, photo_id):
    key = (album_id, photo_id)
    if key in QUEUED_PHOTOS:
        return
    QUEUED_PHOTOS.add(key)
    JOB_QUEUE.put(key)


def enqueue_pending_jobs():
    with LOCK:
        db = load_db()
        for album in db.get("albums", []):
            for photo in album.get("photos", []):
                if photo.get("status") in {"queued", "preparing", "processing"}:
                    photo["status"] = "queued"
                    enqueue_photo_job(album["id"], photo["id"])
        save_db(db)


def process_photo_job(album_id, photo_id):
    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            return
        photo["status"] = "preparing"
        photo["classification"] = "正在生成预览图"
        sync_photo_folder_names(album)
        save_db(db)

    generate_all_thumbnails(album_id, photo["storedName"])

    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            return
        photo["status"] = "processing"
        photo["classification"] = "正在识别人脸"
        sync_photo_folder_names(album)
        save_db(db)

    with LOCK:
        db = load_db()
        album = find_album(db, album_id)
        if not album:
            return
        photo = next((item for item in album.get("photos", []) if item["id"] == photo_id), None)
        if not photo:
            return
        image_path = readable_image_path(album_id, photo["storedName"])
        try:
            if not image_path:
                raise ValueError("图片无法生成预览图")
            photo_folders, classification_note = classify_photo(album, image_path)
            photo["status"] = "ready"
            apply_photo_folders(photo, photo_folders, classification_note)
        except Exception as error:
            photo["status"] = "failed"
            apply_photo_folders(photo, [get_no_face_folder(album)], "识别失败：%s" % error)
        prune_empty_folders(album)
        save_db(db)


def photo_worker():
    while True:
        album_id, photo_id = JOB_QUEUE.get()
        try:
            process_photo_job(album_id, photo_id)
        finally:
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
                digest = hashlib.sha1(("%s-%s-%s" % (time.time(), key, original)).encode("utf-8")).hexdigest()[:12]
                stored_name = "%s%s" % (digest, suffix)
                target = album_dir / stored_name
                with target.open("wb") as out:
                    shutil.copyfileobj(image_file.file, out)

                photo = {
                    "id": uuid.uuid4().hex[:12],
                    "type": "live_photo" if video_item else "photo",
                    "originalName": original,
                    "storedName": stored_name,
                    "url": "/uploads/%s/%s" % (album_id, stored_name),
                    "uploader": uploader,
                    "createdAt": int(time.time()),
                    "status": "queued",
                }

                if video_item:
                    video_file, video_original, video_suffix = video_item
                    video_stored_name = "%s%s" % (digest, video_suffix)
                    with (album_dir / video_stored_name).open("wb") as out:
                        shutil.copyfileobj(video_file.file, out)
                    photo["liveVideoOriginalName"] = video_original
                    photo["liveVideoStoredName"] = video_stored_name

                apply_photo_folders(photo, [pending_folder], "已上传，等待后台识别")
                album["photos"].append(photo)
                created.append(photo)
                queued.append(photo["id"])
            save_db(db)
        for photo_id in queued:
            enqueue_photo_job(album_id, photo_id)
        return self.send_json({"photos": created, "album": public_album(album), "queued": len(created), "ignored": ignored}, 202)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}"), ""
        except json.JSONDecodeError:
            return None, "Invalid JSON"

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
            remove_album_files(album_id)
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
            for photo in photos:
                source = UPLOADS / album_id / photo["storedName"]
                if source.exists():
                    archive.write(source, arcname="%s/%s" % (folder["name"], photo["originalName"]))
                video_name = photo.get("liveVideoStoredName")
                if video_name:
                    video_source = UPLOADS / album_id / video_name
                    if video_source.exists():
                        archive.write(video_source, arcname="%s/%s" % (folder["name"], photo.get("liveVideoOriginalName") or video_name))

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
                source = UPLOADS / album_id / photo["storedName"]
                if source.exists():
                    name = unique_archive_name(photo.get("originalName") or photo["storedName"], used_names)
                    archive.write(source, arcname=name)
                video_name = photo.get("liveVideoStoredName")
                if video_name:
                    video_source = UPLOADS / album_id / video_name
                    if video_source.exists():
                        name = unique_archive_name(photo.get("liveVideoOriginalName") or video_name, used_names)
                        archive.write(video_source, arcname=name)

        filename = "%s-selected-%d.zip" % (slugify(album.get("name") or "photos"), len(photos))
        return self.send_download(zip_path, filename, "application/zip")

    def send_download(self, path, filename, content_type=None):
        if not path.exists() or path.is_dir():
            return self.send_error_json("File not found", 404)
        body = path.read_bytes()
        filename = filename or path.name
        ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or path.name
        encoded_filename = quote(filename.encode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream")
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
        if not image_source.exists() or not video_source.exists():
            return self.send_error_json("Live Photo 文件不完整", 404)
        zip_path = DATA / ("%s-%s-live.zip" % (album_id, photo_id))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(image_source, arcname=photo.get("originalName") or photo["storedName"])
            archive.write(video_source, arcname=photo.get("liveVideoOriginalName") or video_name)
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
    threading.Thread(target=photo_worker, daemon=True).start()
    enqueue_pending_jobs()
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print("Shared Album Demo running at http://localhost:%d" % port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
