#!/usr/bin/env python3
"""独立人脸识别 Worker。

默认通过 Redis 队列消费本机/容器内任务；设置 WORKER_API_URL 后，会改为
HTTP 远程模式，从生产后端领取任务并回写识别结果。
"""

import json
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import server


def request_json(url, payload=None):
    
    headers = {"Accept": "application/json"}
    if server.WORKER_TOKEN:
        headers["X-Worker-Token"] = server.WORKER_TOKEN
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST")
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
                analysis = server.analyze_photo_faces(image_path)
            request_json(
                "%s/api/worker/jobs/%s/%s/complete" % (base_url, album_id, photo_id),
                {"analysis": analysis},
            )
            print("Processed remote photo:", album_id, photo_id, analysis.get("status"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            print("Remote worker error:", error)
            time.sleep(5)


def main():
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
