# PicMe / SharePhotos 项目交接说明

本文档用于帮助下一位 agent 快速理解当前项目状态、架构、部署方式和后续注意事项。

## 1. 项目定位

PicMe 是一个面向朋友出游、聚会场景的共享相册系统。

核心目标：

- 多人把各自拍到的照片上传到同一个相册。
- 后台自动做人脸识别和人物聚类。
- 系统按人物生成子相册，方便每个人快速找到“别人拍到自己的照片”。
- 支持合照、其他照片、Live Photo、单张/批量/子相册下载。
- 同时提供 Web H5 和 iOS 原生端。

当前品牌方向：

- 中文名：识我 / 拾我
- 英文名：PicMe
- 含义：从朋友上传的一堆照片里快速找到我。

## 2. 已完成内容

### 后端能力

- 已实现相册创建、删除、照片上传、照片删除、单张下载、批量下载、子相册下载。
- 已实现多人协作上传。
- 已实现人脸识别分类：
  - 单人照片归入对应人物子相册。
  - 多人照片归入“合照”，同时也加入照片中对应人物的个人子相册。
  - 没有人脸或无法识别的照片归入“其他”。
- 已实现用户手动调整：
  - 子相册昵称编辑。
  - 照片移动到其他子相册。
  - 删除子相册或单张照片。
- 已实现异步识别架构：
  - 上传后先入库。
  - 人脸识别任务进入 Redis 队列。
  - worker 异步消费识别任务。
- 已实现远程 worker 模式：
  - 生产服务器只运行主后端和 Redis。
  - 人脸识别 worker 可以在本地 Mac 或独立机器运行。
- 已完成阿里云 OSS 存储重构：
  - 原图、Live Photo、预览图、缩略图、人脸图统一存储到 OSS。
  - 支持私有 Bucket 和签名 URL。
  - 前端不暴露 AccessKey Secret。
- 已支持 iPhone Live Photo：
  - HEIC + MOV 自动识别为同一张 Live Photo。
  - 只有 HEIC 时降级为普通照片。
  - 支持预览、下载和保存回 iOS 系统相册。

### Web H5

- 移动端优先设计。
- 首页只展示一级相册和创建入口。
- 一级相册进入后展示：
  - 人物分类子相册。
  - 上传照片入口。
  - 查看所有照片入口。
- 子相册照片页已改成接近 iOS/icloud Photos 的连续网格。
- 支持双指缩放切换网格列数。
- 支持点开大图、左右滑切图。
- 支持选择模式、批量操作、更多操作菜单。
- Live Photo 有标识，可预览。

### iOS 原生端

- 已有 SwiftUI iOS 工程。
- 支持连接后端 API。
- 支持从系统相册选择普通照片和 Live Photo。
- 支持上传普通照片和 Live Photo。
- 支持照片列表、子相册、所有照片、大图浏览。
- 支持保存普通照片/Live Photo 回系统相册。
- 支持批量选择、保存、删除等基础交互。
- UI 正在向 iOS 原生相册/icloud Photos 风格靠拢。

## 3. 当前架构

生产服务器目标只保留以下服务：

```text
Caddy
  |
  v
sharephotos 后端
  |
  +--> Redis 队列
  |
  +--> 阿里云 OSS 私有 Bucket

本地 Mac / 独立 worker 机器
  |
  v
face_worker
  |
  +--> Redis / sharephotos 后端
  |
  +--> OSS 资源
```

### Docker 服务

当前生产服务器需要运行：

- `sharephotos`：主后端服务。
- `sharephotos-redis`：Redis 队列。
- `caddy`：反向代理和 HTTPS。

当前生产服务器不需要运行：

- `sharephotos-face-worker`。

如果服务器上还有旧 worker 容器，可以删除：

```bash
docker rm -f sharephotos-face-worker
```

### docker-compose 设计

`docker-compose.yml` 中：

- `sharephotos` 默认启动。
- `redis` 通过 profile 配置，但自动部署会显式启动。
- `face-worker` 放在 `server-worker` profile 中，不应在生产服务器默认启动。
- `caddy` 默认启动。

自动部署当前使用：

```bash
docker compose up -d --build sharephotos redis caddy
```

## 4. OSS 存储设计

OSS 不需要提前创建目录。目录由 object key 自动形成。

当前 object key 规范：

```text
original/{albumId}/{photoId}.heic
original/{albumId}/{photoId}.mov
preview/{albumId}/{photoId}.jpg
thumb/{albumId}/{photoId}.webp
faces/{userId}/{photoId}.jpg
avatars/{userId}.jpg
```

Live Photo 使用同一个 `photoId`：

```text
original/trip001/xxx.heic
original/trip001/xxx.mov
```

数据库记录中需要保存：

- `object_key`
- `oss_url`
- `resource_type`
- `mime_type`
- `file_size`

前端访问图片时，不直接使用公开 Bucket URL，而是通过后端生成签名 URL。

OSS 环境变量：

```env
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_BUCKET=
OSS_ENDPOINT=
OSS_PREFIX=
OSS_SIGNED_URL_EXPIRES=3600
```

注意：

- 不允许把 AccessKey Secret 写死到代码里。
- 不允许在前端暴露 AccessKey Secret。
- 当前目标是私有 Bucket，不是公开读 Bucket。

## 5. Redis 和 worker

Redis 用于异步识别队列。

Redis 环境变量：

```env
REDIS_PASSWORD=
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_URL=redis://:your-password@redis:6379/0
```

如果远程 worker 在另一台机器上运行，需要连接生产服务器 Redis：

```env
REDIS_URL=redis://:your-password@服务器IP:6379/0
```

安全注意：

- Redis 需要密码。
- Redis 端口可以映射到宿主机，供远程 worker 访问。
- 防火墙/安全组最好只允许 worker 机器 IP 访问 Redis 端口。

生产服务器不运行 Docker 版 `sharephotos-face-worker`。

worker 应在本地 Mac 或独立机器上运行，例如：

```bash
FACE_WORKER_MODE=redis python3 face_worker.py
```

## 6. GitHub 自动部署

当前自动部署文件：

```text
.github/workflows/deploy.yml
```

当前策略：

- 监听 `master` 分支。
- SSH 到生产服务器。
- 进入 `~/SharePhotos`。
- 强制同步到 `origin/master`。
- 删除旧的 `sharephotos-face-worker` 容器。
- 只启动 `sharephotos redis caddy`。

当前部署命令逻辑：

```bash
git fetch origin master
git checkout master
git reset --hard origin/master
docker rm -f sharephotos-face-worker || true
docker compose up -d --build sharephotos redis caddy
```

注意：

- `git reset --hard origin/master` 会覆盖服务器上已跟踪文件的本地改动。
- `.env` 通常是未跟踪文件，不会被覆盖。
- 如果服务器上手工改了 `Caddyfile` 且没有提交，会被覆盖。

## 7. 当前待办

### 稳定性

- 验证 OSS 私有 Bucket 的完整链路：
  - 上传普通照片。
  - 上传 Live Photo。
  - 生成 preview。
  - 生成 thumb。
  - 生成 face crop。
  - 签名 URL 预览。
  - 单张下载。
  - 批量下载。
  - 子相册下载。
  - 删除后同步删除 OSS 对象。
- 验证远程 worker 在独立机器上的稳定运行。
- 给远程 worker 增加守护进程方式：
  - systemd
  - supervisor
  - pm2
  - Docker 独立部署
- 补充 worker 日志和失败任务重试机制。

### 数据层

- 当前数据仍主要依赖 JSON 文件型存储。
- 数据量上来后建议迁移到 SQLite 或 PostgreSQL。
- 后续需要设计 migration。

### Web H5

- 继续统一 iCloud Photos 风格：
  - 大图浏览白色背景。
  - 保留系统状态栏区域。
  - 图片居中展示。
  - 底部缩略图独立排列，不和主图重叠。
  - Live 标识位置和 iOS 保持一致。
- 移除小图上不必要的文字和三点按钮。
- 继续优化选择模式、批量下载、批量删除体验。

### iOS

- 继续向 iOS 原生相册风格靠拢：
  - 大图浏览顶部排版。
  - 横向缩略图胶片条。
  - 左右滑切换照片。
  - 左滑返回。
  - Live Photo 自动播放/手动播放细节。
- 继续优化保存到系统相册后的体验：
  - 普通照片进入最近项目。
  - Live Photo 保留动态能力。
- 补齐上传、识别、下载的进度反馈。

### 品牌视觉

- 当前品牌方向为 PicMe。
- Logo 仍在探索中。
- 用户不喜欢高饱和、廉价感强的 logo。
- 倾向：
  - 浅色。
  - 科技感。
  - 有艺术性。
  - 可以是“人指着自己”的图形隐喻。
- H5 和 iOS 的 logo、名称、文案需要保持一致。

## 8. 重要注意事项

### 不要在生产服务器启动 face-worker

生产服务器只跑：

```text
sharephotos
redis
caddy
```

不要默认启动：

```text
sharephotos-face-worker
```

### 不要提交密钥

以下内容只能放在 `.env` 或服务器环境变量：

- `OSS_ACCESS_KEY_ID`
- `OSS_ACCESS_KEY_SECRET`
- `REDIS_PASSWORD`
- `WORKER_TOKEN`

### 私有 Bucket

当前目标是 OSS 私有 Bucket。

不要把 Bucket 设置为公开读，除非用户明确改变策略。

### 服务器本地配置

自动部署会覆盖已跟踪文件。

如果服务器上需要保留本地配置，应放在：

- `.env`
- Docker volume
- 未加入 git 的配置文件

### Xcode 状态文件

本地开发时可能出现 Xcode 的 `UserInterfaceState.xcuserstate` 修改。

这类文件通常是 Xcode 用户状态，不要随意提交或回滚，除非用户明确要求。

## 9. 关键文件

```text
server.py
face_worker.py
docker-compose.yml
Dockerfile
Caddyfile
README.md
.github/workflows/deploy.yml
public/app.js
public/styles.css
native/ios/SharePhotos/
```

## 10. 推荐接手顺序

1. 先读 `README.md` 和本文件。
2. 查看 `docker-compose.yml`，确认生产服务只启动 `sharephotos redis caddy`。
3. 查看 `.github/workflows/deploy.yml`，确认部署目标分支和部署命令。
4. 查看 `server.py` 中 OSS、Redis、上传、下载、删除逻辑。
5. 查看 `face_worker.py`，理解远程 worker 消费任务方式。
6. 本地用已有数据启动 Web H5，确认基础功能。
7. 再进入 iOS 工程调试真机体验。
