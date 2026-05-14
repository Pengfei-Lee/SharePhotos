#!/usr/bin/env python3
"""独立人脸识别 Worker。

默认通过 Redis 队列消费本机/容器内任务；设置 WORKER_API_URL 后，会改为
HTTP 远程模式，从生产后端领取任务并回写识别结果。WORKER_API_URL 与
FACE_WORKER_MODE=redis 同时存在时，Worker 从 Redis 消费任务，再通过主服务
API 拉取照片源和回写结果，适合跨服务器部署。
"""

import json
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import server


def request_json(url, payload=None, method=None):
    headers = {"Accept": "application/json"}
    if server.WORKER_TOKEN:
        headers["X-Worker-Token"] = server.WORKER_TOKEN
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method or ("POST" if payload is not None else "GET"))
    with urlopen(request, timeout=60) as response:
        if response.status == 204:
            return {}
        return json.loads(response.read().decode("utf-8") or "{}")


def download_job_image(source_url, target_dir):
    suffix = Path(source_url.split("?", 1)[0]).suffix or ".jpg"
    target = Path(target_dir) / ("worker-source%s" % suffix)
    request = Request(source_url, headers={"User-Agent": "PicMeFaceWorker/1.0"})
    with urlopen(request, timeout=120) as response, target.open("wb") as out:
        out.write(response.read())
    return target


def collect_resource_metadata(photo, prefixes=("preview", "thumb", "face")):
    metadata = {}
    for prefix in prefixes:
        snake = "%s_" % prefix
        camel = "%s%s" % (prefix, "ObjectKey")
        if not photo.get("%sobject_key" % snake) and not photo.get(camel):
            continue
        metadata[prefix] = {
            "object_key": photo.get("%sobject_key" % snake) or photo.get(camel) or "",
            "oss_url": photo.get("%soss_url" % snake) or photo.get("%sOssUrl" % prefix) or "",
            "resource_type": photo.get("%sresource_type" % snake) or photo.get("%sResourceType" % prefix) or prefix,
            "mime_type": photo.get("%smime_type" % snake) or photo.get("%sMimeType" % prefix) or "",
            "file_size": photo.get("%sfile_size" % snake) or photo.get("%sFileSize" % prefix) or 0,
        }
    return metadata


def analyze_and_upload_resources(album_id, photo_id, image_path):
    photo = {"id": photo_id, "albumId": album_id}
    resources = {}
    if server.oss_enabled():
        server.generate_preview_for_photo(album_id, photo, image_path)
        server.generate_thumbnail_for_photo(album_id, photo, image_path)
        resources = collect_resource_metadata(photo, ("preview", "thumb"))
    readable, cleanup = server.readable_source_for_path(image_path)
    try:
        if not readable:
            return {"status": "failed", "note": "图片无法读取"}, resources
        analysis = server.analyze_photo_faces(readable)
        if server.oss_enabled():
            server.generate_face_thumbnail_for_photo(album_id, photo, readable, album_id)
            resources.update(collect_resource_metadata(photo, ("face",)))
    finally:
        cleanup()
    return analysis, resources


def complete_remote_job(base_url, album_id, photo_id, analysis, resources=None):
    request_json(
        "%s/api/worker/jobs/%s/%s/complete" % (base_url, album_id, photo_id),
        {"analysis": analysis, "resources": resources or {}},
    )


def remote_worker():
    base_url = server.WORKER_API_URL
    print("Remote face worker started, API:", base_url)
    while True:
        try:
            payload = request_json("%s/api/worker/jobs/claim" % base_url, {})
            job = payload.get("job") if payload else None
            if not job:
                time.sleep(3)
                continue
            album_id = job["albumId"]
            photo_id = job["photoId"]
            with tempfile.TemporaryDirectory(prefix="picme-worker-") as tmp:
                image_path = download_job_image(job["sourceUrl"], tmp)
                analysis, resources = analyze_and_upload_resources(album_id, photo_id, image_path)
            complete_remote_job(base_url, album_id, photo_id, analysis, resources)
            print(
                "Processed remote photo:",
                album_id,
                photo_id,
                analysis.get("status"),
                analysis.get("engine", ""),
                analysis.get("faceCount", ""),
                analysis.get("note", ""),
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            print("Remote worker error:", error)
            time.sleep(5)


def redis_remote_worker():
    base_url = server.WORKER_API_URL
    print("Remote Redis face worker started, queue:", server.FACE_QUEUE_NAME, "API:", base_url)
    while True:
        job = server.pop_face_job(timeout=3)
        if not job:
            continue
        album_id, photo_id = job
        if not album_id or not photo_id:
            continue
        try:
            payload = request_json("%s/api/worker/jobs/%s/%s" % (base_url, album_id, photo_id))
            remote_job = payload.get("job") if payload else None
            if not remote_job:
                continue
            source_url = remote_job.get("sourceUrl") or (remote_job.get("photo") or {}).get("imageUrl")
            if not source_url:
                raise ValueError("Worker job missing sourceUrl")
            with tempfile.TemporaryDirectory(prefix="picme-worker-") as tmp:
                image_path = download_job_image(source_url, tmp)
                analysis, resources = analyze_and_upload_resources(album_id, photo_id, image_path)
            complete_remote_job(base_url, album_id, photo_id, analysis, resources)
            print(
                "Processed remote Redis photo:",
                album_id,
                photo_id,
                analysis.get("status"),
                analysis.get("engine", ""),
                analysis.get("faceCount", ""),
                analysis.get("note", ""),
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            print("Remote Redis worker error:", album_id, photo_id, error)
            try:
                complete_remote_job(base_url, album_id, photo_id, {"status": "failed", "note": str(error)}, {})
            except Exception as complete_error:
                print("Remote Redis worker complete error:", complete_error)
                time.sleep(5)
        finally:
            if server.REDIS_CLIENT is not None:
                server.REDIS_CLIENT.srem(server.FACE_QUEUE_SET_NAME, "%s:%s" % (album_id, photo_id))


def main():
    if server.WORKER_API_URL and server.FACE_WORKER_MODE == "redis":
        if not server.use_redis_queue():
            raise RuntimeError("远程 Redis Worker 需要设置可用的 REDIS_URL 且 FACE_WORKER_MODE=redis")
        redis_remote_worker()
        return
    if server.WORKER_API_URL:
        remote_worker()
        return
    if not server.use_redis_queue():
        raise RuntimeError("Face worker 需要设置 REDIS_URL 且 FACE_WORKER_MODE=redis")
    server.ensure_store()
    server.enqueue_pending_jobs()
    print("Face worker started, consuming queue:", server.FACE_QUEUE_NAME)
    server.photo_worker()


if __name__ == "__main__":
    main()
