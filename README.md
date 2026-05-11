# 共享相册 Demo

这是一个最小可验证 Demo，用来验证多人协作上传、自动人物文件夹整理、按文件夹下载，以及浏览器跨平台访问。

## 运行

安装依赖：

```bash
python3 -m pip install --user -r requirements.txt
```

首次使用高精度人脸识别时，InsightFace 会自动下载 `buffalo_l` 模型到本机缓存目录。

```bash
python3 server.py
```

打开：

```text
http://localhost:8000
```

局域网内其他设备可以访问本机 IP，例如：

```text
http://你的电脑IP:8000
```

## Docker 部署

服务器只需要安装 Docker 和 Docker Compose。首次启动会构建镜像，并把照片数据保存在项目目录的 `data/`，把 InsightFace 模型缓存在 `models/`。

```bash
git clone git@github.com:Pengfei-Lee/SharePhotos.git
cd SharePhotos
docker compose up -d --build
```

打开：

```text
http://服务器IP:8000
```

常用命令：

```bash
docker compose logs -f
docker compose restart
docker compose down
docker compose up -d --build
```

升级代码：

```bash
git pull
docker compose up -d --build
```

不要删除 `data/`，里面有照片、缩略图和 `db.json`；不要删除 `models/`，否则下次启动会重新下载人脸识别模型。

## OSS 环境变量配置（阿里云）

如果你希望**原图、Live Photo、缩略图、预览图都统一上传到阿里云 OSS**，需要配置以下环境变量。建议 Bucket 保持私有读写，前端只使用服务端生成的签名 URL，不会暴露 AccessKey Secret。

- `OSS_ENDPOINT`：OSS 地域节点，例如 `https://oss-cn-chengdu.aliyuncs.com`
- `OSS_BUCKET`：Bucket 名称，例如 `picme-photos`
- `OSS_ACCESS_KEY_ID`：阿里云 AccessKey ID
- `OSS_ACCESS_KEY_SECRET`：阿里云 AccessKey Secret
- `OSS_PREFIX`（可选）：对象存储总前缀，默认空。一般不需要配置，系统会直接写入 `original/`、`preview/`、`thumb/` 等前缀
- `OSS_SIGNED_URL_EXPIRES`（可选）：签名 URL 有效期，默认 `3600` 秒

OSS 不需要手动创建目录。对象上传时会按 object key 自动形成类似目录的前缀：

```text
original/{albumId}/{photoId}.heic
original/{albumId}/{photoId}.mov
preview/{albumId}/{photoId}.jpg
thumb/{albumId}/{photoId}.webp
faces/{userId}/{photoId}.jpg
avatars/{userId}.jpg
```

数据库会保存 `object_key`、`oss_url`、`resource_type`、`mime_type`、`file_size` 等资源元数据；接口返回给前端的是服务端签名后的临时访问地址。后续接 CDN、STS 临时凭证或 AI 分类前缀（例如 `ai/group/`、`ai/person/`）时，可以继续沿用同一套 object key 规则。

> 不配置 OSS 变量时，系统会保持本地文件存储逻辑，便于本地开发。

### 方式一：本地直接启动时配置

```bash
export OSS_ENDPOINT="https://oss-cn-chengdu.aliyuncs.com"
export OSS_BUCKET="your-bucket-name"
export OSS_ACCESS_KEY_ID="your-access-key-id"
export OSS_ACCESS_KEY_SECRET="your-access-key-secret"
export OSS_SIGNED_URL_EXPIRES="3600"

python3 server.py
```

### 方式二：Docker Compose 配置

`docker-compose.yml` 已预留 OSS 环境变量，可通过 `.env` 或服务器环境变量配置：

```bash
OSS_ENDPOINT=https://oss-cn-chengdu.aliyuncs.com
OSS_BUCKET=picme-photos
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_SIGNED_URL_EXPIRES=3600
```

然后重启：

```bash
docker compose up -d --build
```

## 验证路径

1. 创建一个相册。
2. 用上传者 A 上传几张图片。
3. 换上传者 B 再上传几张图片。
4. 服务端优先使用 InsightFace/ArcFace 检测照片中的人脸，并用 512 维人脸向量进行相似度聚类；缺少模型依赖时才回退到 OpenCV Demo 分类器。
5. 多脸照片会进入“合照”文件夹，同时也会进入照片中每个被识别人物的文件夹。
6. 没有检测到人脸的照片会进入“未识别人脸”文件夹。
7. 点击任意人物文件夹右上角的“下载”，会得到该文件夹的 zip 包。

## Demo 边界

这个版本先把产品闭环跑通。人物分类已不依赖文件名，而是优先使用 InsightFace/ArcFace 进行人脸检测和向量聚类，并提供全量重分析、合照多归属、人物合并、单张照片移动、重新识别等纠错流程。生产版本建议继续增加人物命名、相册级阈值调优和后台任务队列。Immich 这类项目可作为后续架构参考。

## 缺陷

1. 照片点开后，首先看到的是上次点开的照片，加载1～2s后才会显示这张照片，需要进行优化这个缺陷【待验证】
2. 照片查看应该支持左滑或右滑功能，方便查看，而不是只能点右上角的叉返回【完成】
3. 照片上不显示文件名，可以保留上传者和时间【完成】


## 优化功能

1. 要加上用户注册与登陆
2. 要支持live动图的上传与下载
3. 一级相册要加上专属分享链接（二维码）才能加入，以及加入链接可选设置密码的机制
4. 一级相册和二级相册都要支持重命名【子相册封面右上角新增小的“名”按钮，点击可给小相册改名，还可以进一步优化】
5. 下载最好不是压缩包，而是直接下载到系统相册里面


## 人脸识别独立部署（Redis 队列解耦）

已支持将人脸识别从主服务中拆分为独立 Worker：

- `sharephotos`（主服务）：仅负责上传与 API，上传后把任务写入 Redis 队列
- `face-worker`（新服务）：从 Redis 队列消费任务并执行人脸识别入库
- `redis`：任务队列

### Docker Compose（推荐）

`docker-compose.yml` 已内置 `redis` 和 `face-worker`，通过 `server-worker` profile 启动。Redis 支持通过环境变量配置密码并开放远程访问端口。

```bash
REDIS_PASSWORD="换成强密码"
docker compose --profile server-worker up -d --build
```

### 环境变量

- `FACE_WORKER_MODE=redis`：开启 Redis 队列模式
- `REDIS_PASSWORD`：Redis 密码，不要写进代码，建议放 `.env`
- `REDIS_HOST=redis`（可选）：Redis 主机，容器内默认 `redis`
- `REDIS_PORT=6379`（可选）：宿主机开放端口，默认 `6379`
- `REDIS_DB=0`（可选）：Redis DB 编号
- `REDIS_URL=redis://:你的密码@redis:6379/0`：容器内 Redis 连接地址
- `FACE_QUEUE_NAME`（可选）：队列名，默认 `sharephotos:face:jobs`

示例 `.env`：

```bash
REDIS_PASSWORD=replace-with-a-strong-password
REDIS_HOST=redis
REDIS_DB=0
REDIS_URL=redis://:replace-with-a-strong-password@redis:6379/0
REDIS_PORT=6379
```

如果没有配置 `REDIS_URL`，主服务和 `face-worker` 都会自动使用 `REDIS_HOST`、`REDIS_PORT`、`REDIS_DB`、`REDIS_PASSWORD` 拼出连接地址。

如果要从服务器外部连接 Redis，地址通常是：

```bash
redis://:replace-with-a-strong-password@你的服务器IP:6379/0
```

远程开放 Redis 端口有安全风险，生产环境建议同时配置云安全组/防火墙，只允许你的固定 IP 访问。

### 本地分离启动示例

终端 1（API 服务）：

```bash
export FACE_WORKER_MODE=redis
export REDIS_URL=redis://:replace-with-a-strong-password@127.0.0.1:6379/0
python3 server.py
```

终端 2（Worker）：

```bash
export FACE_WORKER_MODE=redis
export REDIS_URL=redis://:replace-with-a-strong-password@127.0.0.1:6379/0
python3 face_worker.py
```

不设置 `FACE_WORKER_MODE=redis` 时，系统保持原本的进程内队列+线程消费模式，前后端接口保持不变。

### 本地机器远程做人脸识别

如果生产服务器 CPU 不适合跑模型，可以让生产后端只负责上传与入库，本地 Mac 负责识别：

生产服务端：

```bash
export FACE_WORKER_MODE=remote
export WORKER_TOKEN=替换成一段随机密钥
docker compose up -d --build
```

本地 Mac：

```bash
export WORKER_API_URL=http://服务器IP
export WORKER_TOKEN=替换成同一段随机密钥
python3 face_worker.py
```

远程 Worker 会从生产后端领取 `queued/preparing/processing` 状态的照片，下载后在本机执行人脸识别，并把识别结果回写到生产后端。
