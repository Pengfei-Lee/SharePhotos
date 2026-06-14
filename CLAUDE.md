# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PicMe / 识我 是一个面向出游、聚会场景的共享相册产品：多人把各自拍的照片上传到同一相册，后端做人脸识别 +
人物聚类，自动按人物生成子相册，让每个人快速找到"别人拍到自己的照片"。它有 Web H5、原生 iOS、原生
Android 三端（Android 尚未完全开发完），都连同一套后端 API。

更深入的背景请读 `README.md`（部署、OSS、Redis/worker）和 `PROJECT_HANDOFF.md`（架构决策、当前
待办、硬性规则）。`ANDROID_QA_FINDINGS.md` 记录安卓缺陷及其修复/验证状态。

## 仓库结构

- `server.py` —— 整个后端（约 7300 行，单文件）。
- `face_worker.py` —— 独立的人脸识别 worker。
- `public/` —— Web H5 前端（`app.js`、`index.html`、`styles.css`），由 `server.py` 直接托管。
- `native/ios/SharePhotos/` —— SwiftUI iOS 应用（主要逻辑在 `ContentView.swift`）。
- `native/android/SharePhotos/` —— 原生 Android 应用（主要逻辑在 `app/.../MainActivity.java`）。
- `data/` —— 运行时数据（SQLite `sharephotos.db`、缩略图/预览图/上传、日志）。不要删除。
- `docker-compose.yml`、`Dockerfile`、`Caddyfile`、`.github/workflows/deploy.yml` —— 部署相关。

## 常用命令

### 后端（Python，无框架 —— 标准库 `http.server.ThreadingHTTPServer`，端口 8000）
```bash
python3 -m pip install --user -r requirements.txt
python3 server.py            # 在 http://localhost:8000 同时托管 H5 + API
python3 face_worker.py       # 运行 worker（需 FACE_WORKER_MODE / REDIS_URL / WORKER_API_URL 等环境变量）
```
后端没有测试套件、linter 或构建步骤 —— 直接运行即可。

### Docker（生产方式）
```bash
docker compose up -d --build sharephotos redis caddy   # 自动部署所执行的命令
docker compose logs -f
```
生产环境只跑 `sharephotos`、`redis`、`caddy`。**不要在生产服务器启动 `face-worker`** —— 它应在
本地 Mac / 独立机器上运行（见 PROJECT_HANDOFF §8）。

### Android（Gradle，AGP 7.4.2，compileSdk 33，minSdk 23；应用 id `com.sharephotos.app`）
```bash
cd native/android/SharePhotos
./gradlew :app:assembleDebug                 # 产物：app/build/outputs/apk/debug/app-debug.apk
~/Library/Android/sdk/platform-tools/adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-debug.apk
~/Library/Android/sdk/platform-tools/adb -s emulator-5554 shell monkey -p com.sharephotos.app -c android.intent.category.LAUNCHER 1
```
Android 客户端固定连接生产 `https://picme.me`（应用内无服务器切换入口）。
模拟器排错：崩溃后若 `adb` 显示 AVD `offline` / 窗口隐藏，冷启动它：
`~/Library/Android/sdk/emulator/emulator -avd Pixel_7 -no-snapshot-load`（通常是 `default_boot`
快照损坏导致）。

### iOS
用 Xcode 打开 `native/ios/SharePhotos/SharePhotos.xcodeproj`，在模拟器/真机运行。

### 部署
推送到 `master` → GitHub Actions SSH 到服务器执行 `git reset --hard origin/master` +
`docker compose up`。**`git reset --hard` 会覆盖服务器上被跟踪文件的本地改动**；服务器本地配置只能放在
`.env` / Docker volume / 未跟踪文件中。

## 架构（大图景）

**上传 → 识别 → 聚类 流水线。** 客户端上传原图（优先 OSS 直传：`/uploads/init` → PUT 到 OSS →
`/uploads/complete`，不可用时回退服务器中转 `/upload`）。后端记录照片后派发人脸任务。worker 用
InsightFace/ArcFace 检测人脸（512 维向量；缺模型时回退 OpenCV）、聚类、回写结果。单人照片进对应人物子相册；
多脸照片进"合照"并同时进每个被识别人物的子相册；无人脸照片进"其他/未识别"。

**三种 worker 执行模式**（通过环境变量切换，见 README"人脸识别独立部署"）：
1. 进程内队列 + 线程（默认，无需 Redis）。
2. `FACE_WORKER_MODE=redis` —— 后端把 `albumId/photoId` 入 Redis；远程 worker 弹出任务，调
   `GET /api/worker/jobs/{albumId}/{photoId}` 取签名原图，做识别，把 preview/thumb/face-crop 上传
   OSS，再通过 `/api/worker/jobs/.../complete` 回写。worker 不读后端 DB、也不共享其 `data/` 目录。
3. `FACE_WORKER_MODE=remote` —— 不用 Redis；后端暴露 claim 接口，worker 轮询领取。

**存储抽象。** 配置了 OSS 环境变量（`OSS_ENDPOINT/BUCKET/ACCESS_KEY_ID/SECRET`）后，所有
原图/Live Photo MOV/预览图/缩略图/人脸图/头像都进**私有** 阿里云 OSS bucket；后端给客户端的是**签名临时
URL**（绝不暴露 AccessKey，绝不用公开 bucket）。object key 遵循固定规则：
`original/{albumId}/{photoId}.{ext}`、`preview/...jpg`、`thumb/...webp`、
`faces/{userId}/{photoId}.jpg`、`avatars/{userId}.jpg`。未配置 OSS 时回退到 `data/` 下的本地文件。
数据库行保存 `object_key/oss_url/resource_type/mime_type/file_size`。

**持久化。** 默认用 SQLite（`data/sharephotos.db`，WAL + 外键，`DB_BACKEND=sqlite`）；首次运行若存在
旧的 `data/db.json` 会自动迁移。`DB_BACKEND=json` 回退到旧文件存储。

**Live Photo。** 一张 Live Photo = 一个 HEIC + 一个 MOV，共用同一 `photoId`；只有 HEIC 时降级为普通
照片。前置（自拍）MOV 的 `tkhd` 矩阵带镜像变换，iOS AVPlayer 会应用、Android `MediaPlayer` 会忽略
—— Android 需自行检测并手动水平翻转。

**权限模型。** 两层：相册级（上传/删除/下载/分享，创建相册时各自可开关）和用户级（分享链接设默认值；协作用户
页可逐人覆盖）。创建者可移除成员。非创建者可退出相册并申请权限升级，由创建者审批。

**通知。** 站内消息中心 + 各处未读角标；iOS 另有 APNs 推送（设备注册 `/api/devices/apns`，由 `APNS_*`
环境变量配置；未配置时仍保留站内消息）。点击消息会跳转到审批页或相册的"我的照片"。

## 原生端约定

- **Android UI 完全用 Java 代码构建**（`MainActivity.java`，约 4900 行）—— 没有 XML 布局；视图/页面用
  辅助方法构造（`vertical()`、`horizontal()`、`card()`、`text()`、`ghostButton()`、
  `outlineButton()`、`round()`、`matchWrap()`、`dp()`）。页面通过 `setContentView` 切换；没有
  resource id，所以驱动运行中的 app 要用 `adb shell uiautomator dump`（读节点 `bounds`）+
  `adb shell input tap`。
  - 坑：绝不要把 `matchWrap()`（MATCH_PARENT 宽）传给"水平行里、且有带 weight 兄弟"的子视图 —— 会把
    带 weight 的视图挤成 0 宽。靠右的次要项用 WRAP_CONTENT 的参数 helper（如 `trailingWrap()`）。
  - 图片加载是三级：内存 `LruCache` → 磁盘（`PhotoDiskCache`，按 URL 哈希做 key，对齐 iOS 的
    `PhotoDiskCache`）→ 网络，并按目标尺寸降采样。Live 视频通过
    `PhotoDiskCache.fetch(identifier, downloader)` 复用同一磁盘缓存。
- **iOS** 用 SwiftUI 实现同样的页面；让 Android 对齐 iOS 时，以
  `native/ios/.../ContentView.swift` 作为布局/图标（SF Symbols）的基准。

## 硬性规则（来自 PROJECT_HANDOFF）

- 密钥（`OSS_ACCESS_KEY_SECRET`、`REDIS_PASSWORD`、`WORKER_TOKEN`、APNs key）只放 `.env` 或服务器
  环境变量 —— 绝不写进代码、绝不暴露给前端。OSS bucket 保持私有。
- 未经要求不要提交/回滚 Xcode 的 `UserInterfaceState.xcuserstate`。
- 不要删除 `data/`（照片、缩略图、SQLite、旧 db.json）或 `models/`（下载的人脸模型）。
