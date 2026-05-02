#!/usr/bin/env python3
import cgi
import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/sharephotos-matplotlib")
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import cv2
import numpy as np

try:
    from insightface.app import FaceAnalysis
except Exception:
    FaceAnalysis = None


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB_FILE = DATA / "db.json"
LOCK = threading.Lock()


def ensure_store():
    DATA.mkdir(exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    if not DB_FILE.exists():
        save_db({"albums": []})


def load_db():
    ensure_store()
    with DB_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_db(db):
    DATA.mkdir(exist_ok=True)
    tmp = DB_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=2)
    tmp.replace(DB_FILE)


def slugify(value):
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-.")
    return value or "album"


def find_album(db, album_id):
    for album in db["albums"]:
        if album["id"] == album_id:
            return album
    return None


def public_album(album):
    visible = dict(album)
    visible["folders"] = []
    for folder in album.get("folders", []):
        item = {key: value for key, value in folder.items() if key not in {"embedding", "embeddingCount", "embeddingEngine"}}
        visible["folders"].append(item)
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
    folder = next((item for item in album.get("folders", []) if item["id"] == "no-face" or item["name"] == "未识别人脸"), None)
    return folder or create_folder(album, "未识别人脸", folder_id="no-face")


def get_group_folder(album):
    folder = next((item for item in album.get("folders", []) if item["id"] == "group-photo" or item["name"] == "合照"), None)
    return folder or create_folder(album, "合照", folder_id="group-photo")


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
    photos = sorted(album.get("photos", []), key=lambda item: item.get("createdAt", 0))
    album["folders"] = []
    for photo in photos:
        image_path = UPLOADS / album["id"] / photo["storedName"]
        folders, note = classify_photo(album, image_path)
        apply_photo_folders(photo, folders, "全量重分析：%s" % note)
    return album


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
        match = re.match(r"^/api/albums/([^/]+)/reanalyze$", path)
        if match:
            return self.reanalyze_album_request(match.group(1))
        match = re.match(r"^/api/albums/([^/]+)/folders/([^/]+)/merge$", path)
        if match:
            return self.merge_folder_request(match.group(1), match.group(2))
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
            for idx, item in enumerate(files):
                original = Path(item.filename).name
                suffix = Path(original).suffix.lower()
                if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}:
                    suffix = ".jpg"
                digest = hashlib.sha1(("%s-%s" % (time.time(), original)).encode("utf-8")).hexdigest()[:12]
                stored_name = "%s%s" % (digest, suffix)
                target = album_dir / stored_name
                with target.open("wb") as out:
                    shutil.copyfileobj(item.file, out)

                photo_folders, classification_note = classify_photo(album, target)
                photo = {
                    "id": uuid.uuid4().hex[:12],
                    "originalName": original,
                    "storedName": stored_name,
                    "url": "/uploads/%s/%s" % (album_id, stored_name),
                    "uploader": uploader,
                    "createdAt": int(time.time()),
                }
                apply_photo_folders(photo, photo_folders, classification_note)
                album["photos"].append(photo)
                created.append(photo)
            save_db(db)
        return self.send_json({"photos": created}, 201)

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

    def serve_file(self, path):
        path = path.resolve()
        allowed = [PUBLIC.resolve(), UPLOADS.resolve()]
        if not any(str(path).startswith(str(root)) for root in allowed) or not path.exists() or path.is_dir():
            return self.send_error_json("Not found", 404)
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ensure_store()
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print("Shared Album Demo running at http://localhost:%d" % port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
