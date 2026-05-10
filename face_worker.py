#!/usr/bin/env python3
"""独立人脸识别 Worker：通过 Redis 队列消费任务。"""

import server


def main():
    if not server.use_redis_queue():
        raise RuntimeError("Face worker 需要设置 REDIS_URL 且 FACE_WORKER_MODE=redis")
    server.ensure_store()
    server.enqueue_pending_jobs()
    print("Face worker started, consuming queue:", server.FACE_QUEUE_NAME)
    server.photo_worker()


if __name__ == "__main__":
    main()
