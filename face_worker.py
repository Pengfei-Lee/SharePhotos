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

LOGGER = server.LOGGER


def elapsed_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)


def safe_url_label(url):
    return (url or "").split("?", 1)[0]


def request_json(url, payload=None, method=None):
    headers = {"Accept": "application/json"}
    if server.WORKER_TOKEN:
        headers["X-Worker-Token"] = server.WORKER_TOKEN
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method or ("POST" if payload is not None else "GET"))
    LOGGER.info("method=%s url=%s", request.get_method(), safe_url_label(url), extra={"event": "worker.api_request"})
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
    LOGGER.info("source=%s target=%s", safe_url_label(source_url), target.name, extra={"event": "worker.download"})
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
    started_at = time.perf_counter()
    LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.analysis_start"})
    photo = {"id": photo_id, "albumId": album_id}
    resources = {}
    if server.oss_enabled():
        derivative_started_at = time.perf_counter()
        server.generate_preview_for_photo(album_id, photo, image_path)
        server.generate_thumbnail_for_photo(album_id, photo, image_path)
        resources = collect_resource_metadata(photo, ("preview", "thumb"))
        LOGGER.info(
            "Worker照片预览与缩略图生成完成：album_id=%s photo_id=%s 耗时=%sms",
            album_id,
            photo_id,
            elapsed_ms(derivative_started_at),
            extra={"event": "worker.derivatives_complete"},
        )
    readable, cleanup = server.readable_source_for_path(image_path)
    try:
        if not readable:
            LOGGER.warning("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.analysis_unreadable"})
            return {"status": "failed", "note": "图片无法读取"}, resources
        analysis_started_at = time.perf_counter()
        analysis = server.analyze_photo_faces(readable)
        LOGGER.info(
            "Worker照片人脸识别完成：album_id=%s photo_id=%s status=%s engine=%s 耗时=%sms",
            album_id,
            photo_id,
            analysis.get("status"),
            analysis.get("engine", ""),
            elapsed_ms(analysis_started_at),
            extra={"event": "worker.analysis_face_complete"},
        )
        if server.oss_enabled():
            face_thumb_started_at = time.perf_counter()
            server.generate_face_thumbnail_for_photo(album_id, photo, readable, album_id)
            resources.update(collect_resource_metadata(photo, ("face",)))
            LOGGER.info(
                "Worker人脸小图生成完成：album_id=%s photo_id=%s 耗时=%sms",
                album_id,
                photo_id,
                elapsed_ms(face_thumb_started_at),
                extra={"event": "worker.face_thumb_complete"},
            )
    finally:
        cleanup()
    LOGGER.info(
        "Worker照片分析全部完成：album_id=%s photo_id=%s status=%s engine=%s face_count=%s raw_faces=%s filtered_faces=%s 总耗时=%sms",
        album_id,
        photo_id,
        analysis.get("status"),
        analysis.get("engine", ""),
        analysis.get("faceCount", ""),
        analysis.get("rawFaceCount", ""),
        analysis.get("filteredFaceCount", ""),
        elapsed_ms(started_at),
        extra={"event": "worker.analysis_complete"},
    )
    return analysis, resources


def complete_remote_job(base_url, album_id, photo_id, analysis, resources=None):
    request_json(
        "%s/api/worker/jobs/%s/%s/complete" % (base_url, album_id, photo_id),
        {"analysis": analysis, "resources": resources or {}},
    )
    LOGGER.info(
        "album_id=%s photo_id=%s status=%s",
        album_id,
        photo_id,
        analysis.get("status"),
        extra={"event": "worker.complete_posted"},
    )


def analyze_avatar_image(image_path):
    started_at = time.perf_counter()
    readable, cleanup = server.readable_source_for_path(image_path)
    try:
        if not readable:
            return {"status": "failed", "note": "头像无法读取"}
        embedding, note, meta = server.extract_face_embedding(readable)
        LOGGER.info(
            "Worker头像人脸识别完成：status=%s engine=%s 耗时=%sms",
            "ready" if embedding else "failed",
            meta.get("engine") if meta else "",
            elapsed_ms(started_at),
            extra={"event": "worker.avatar_analysis_complete"},
        )
        return {
            "status": "ready" if embedding else "failed",
            "embedding": embedding,
            "engine": meta.get("engine") if meta else "",
            "note": note or "",
        }
    finally:
        cleanup()


def complete_avatar_job(base_url, user_id, analysis):
    request_json("%s/api/worker/avatar-jobs/%s/complete" % (base_url, user_id), {"analysis": analysis})
    LOGGER.info("user_id=%s status=%s", user_id, analysis.get("status"), extra={"event": "worker.avatar_complete_posted"})


def complete_match_job(base_url, album_id, user_id, match):
    request_json("%s/api/worker/match-jobs/%s/%s/complete" % (base_url, album_id, user_id), {"match": match})
    LOGGER.info("album_id=%s user_id=%s matched=%s", album_id, user_id, match.get("matched"), extra={"event": "worker.match_complete_posted"})


def process_remote_task(base_url, job):
    job_type = job.get("type") or job.get("taskType") or server.FACE_JOB_PHOTO_ANALYZE
    if job_type == server.FACE_JOB_PHOTO_ANALYZE:
        album_id = job["albumId"]
        photo_id = job["photoId"]
        payload = request_json("%s/api/worker/jobs/%s/%s" % (base_url, album_id, photo_id))
        remote_job = payload.get("job") if payload else None
        if not remote_job:
            LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.job_missing"})
            return
        source_url = remote_job.get("sourceUrl") or (remote_job.get("photo") or {}).get("imageUrl")
        if not source_url:
            raise ValueError("Worker job missing sourceUrl")
        with tempfile.TemporaryDirectory(prefix="picme-worker-") as tmp:
            image_path = download_job_image(source_url, tmp)
            analysis, resources = analyze_and_upload_resources(album_id, photo_id, image_path)
        complete_remote_job(base_url, album_id, photo_id, analysis, resources)
        LOGGER.info(
            "album_id=%s photo_id=%s status=%s engine=%s face_count=%s note=%s",
            album_id,
            photo_id,
            analysis.get("status"),
            analysis.get("engine", ""),
            analysis.get("faceCount", ""),
            analysis.get("note", ""),
            extra={"event": "worker.job_complete"},
        )
        return
    if job_type == server.FACE_JOB_AVATAR_ANALYZE:
        started_at = time.perf_counter()
        user_id = job["userId"]
        payload = request_json("%s/api/worker/avatar-jobs/%s" % (base_url, user_id))
        remote_job = payload.get("job") if payload else None
        if not remote_job:
            LOGGER.info("user_id=%s", user_id, extra={"event": "worker.avatar_job_missing"})
            return
        source_url = remote_job.get("sourceUrl")
        if not source_url:
            raise ValueError("Avatar worker job missing sourceUrl")
        with tempfile.TemporaryDirectory(prefix="picme-avatar-worker-") as tmp:
            image_path = download_job_image(source_url, tmp)
            analysis = analyze_avatar_image(image_path)
        complete_avatar_job(base_url, user_id, analysis)
        LOGGER.info(
            "Worker头像任务完成：user_id=%s status=%s 总耗时=%sms",
            user_id,
            analysis.get("status"),
            elapsed_ms(started_at),
            extra={"event": "worker.avatar_job_complete"},
        )
        return
    if job_type == server.FACE_JOB_ALBUM_MATCH:
        started_at = time.perf_counter()
        album_id = job["albumId"]
        user_id = job["userId"]
        payload = request_json("%s/api/worker/match-jobs/%s/%s" % (base_url, album_id, user_id))
        remote_job = payload.get("job") if payload else None
        if not remote_job:
            LOGGER.info("album_id=%s user_id=%s", album_id, user_id, extra={"event": "worker.match_job_missing"})
            return
        match_started_at = time.perf_counter()
        match = server.compute_user_album_match(remote_job.get("album") or {}, remote_job.get("user") or {})
        LOGGER.info(
            "Worker相册关联匹配计算完成：album_id=%s user_id=%s matched=%s folder_id=%s 耗时=%sms",
            album_id,
            user_id,
            match.get("matched"),
            match.get("folderId", ""),
            elapsed_ms(match_started_at),
            extra={"event": "worker.match_compute_complete"},
        )
        complete_match_job(base_url, album_id, user_id, match)
        LOGGER.info(
            "Worker相册关联任务完成：album_id=%s user_id=%s matched=%s 总耗时=%sms",
            album_id,
            user_id,
            match.get("matched"),
            elapsed_ms(started_at),
            extra={"event": "worker.match_job_complete"},
        )
        return
    LOGGER.warning("job=%s", job, extra={"event": "worker.unknown_job"})


def remote_worker():
    base_url = server.WORKER_API_URL
    server.log_startup_config("face-worker-remote")
    LOGGER.info("api=%s", base_url, extra={"event": "worker.start"})
    while True:
        try:
            payload = request_json("%s/api/worker/jobs/claim" % base_url, {})
            job = payload.get("job") if payload else None
            if not job:
                time.sleep(3)
                continue
            album_id = job["albumId"]
            photo_id = job["photoId"]
            LOGGER.info("album_id=%s photo_id=%s", album_id, photo_id, extra={"event": "worker.job_claimed"})
            with tempfile.TemporaryDirectory(prefix="picme-worker-") as tmp:
                image_path = download_job_image(job["sourceUrl"], tmp)
                analysis, resources = analyze_and_upload_resources(album_id, photo_id, image_path)
            complete_remote_job(base_url, album_id, photo_id, analysis, resources)
            LOGGER.info(
                "album_id=%s photo_id=%s status=%s engine=%s face_count=%s note=%s",
                album_id,
                photo_id,
                analysis.get("status"),
                analysis.get("engine", ""),
                analysis.get("faceCount", ""),
                analysis.get("note", ""),
                extra={"event": "worker.job_complete"},
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            LOGGER.warning("error=%s", error, extra={"event": "worker.error"})
            time.sleep(5)


def redis_remote_worker():
    base_url = server.WORKER_API_URL
    server.log_startup_config("face-worker-redis-remote")
    LOGGER.info("queue=%s api=%s", server.FACE_QUEUE_NAME, base_url, extra={"event": "worker.start"})
    while True:
        job = server.pop_face_job(timeout=3)
        if not job:
            continue
        if isinstance(job, tuple):
            job = {"type": server.FACE_JOB_PHOTO_ANALYZE, "albumId": job[0], "photoId": job[1]}
        if not job:
            continue
        job_key = server.face_job_key(job)
        LOGGER.info("job=%s", job_key, extra={"event": "worker.job_pulled"})
        try:
            process_remote_task(base_url, job)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            LOGGER.warning("job=%s error=%s", job_key, error, extra={"event": "worker.error"})
            if job.get("type") == server.FACE_JOB_PHOTO_ANALYZE:
                try:
                    complete_remote_job(base_url, job.get("albumId"), job.get("photoId"), {"status": "failed", "note": str(error)}, {})
                except Exception as complete_error:
                    LOGGER.warning("job=%s error=%s", job_key, complete_error, extra={"event": "worker.complete_failed"})
                    time.sleep(5)
        finally:
            if server.REDIS_CLIENT is not None:
                server.REDIS_CLIENT.srem(server.FACE_QUEUE_SET_NAME, job_key)
                LOGGER.info("job=%s", job_key, extra={"event": "redis.complete"})


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
    server.log_startup_config("face-worker")
    LOGGER.info("queue=%s", server.FACE_QUEUE_NAME, extra={"event": "worker.start"})
    server.photo_worker()


if __name__ == "__main__":
    main()
