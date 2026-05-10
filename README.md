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

如果你希望**原图、缩略图、预览图都上传到阿里云 OSS**，并且让前端直接访问 OSS URL，需要配置以下环境变量：

- `OSS_ENDPOINT`：OSS 地域节点，例如 `https://oss-cn-hangzhou.aliyuncs.com`
- `OSS_BUCKET`：Bucket 名称，例如 `my-sharephotos`
- `OSS_ACCESS_KEY_ID`：阿里云 AccessKey ID
- `OSS_ACCESS_KEY_SECRET`：阿里云 AccessKey Secret
- `OSS_PREFIX`（可选）：对象存储前缀目录，默认是 `sharephotos`

> 不配置以上变量时，系统会保持原有本地存储逻辑。

### 方式一：本地直接启动时配置

```bash
export OSS_ENDPOINT="https://oss-cn-hangzhou.aliyuncs.com"
export OSS_BUCKET="your-bucket-name"
export OSS_ACCESS_KEY_ID="your-access-key-id"
export OSS_ACCESS_KEY_SECRET="your-access-key-secret"
export OSS_PREFIX="sharephotos"

python3 server.py
```

### 方式二：Docker Compose 配置

在 `docker-compose.yml` 的服务里增加 `environment`（示例）：

```yaml
services:
  sharephotos:
    environment:
      OSS_ENDPOINT: https://oss-cn-hangzhou.aliyuncs.com
      OSS_BUCKET: your-bucket-name
      OSS_ACCESS_KEY_ID: your-access-key-id
      OSS_ACCESS_KEY_SECRET: your-access-key-secret
      OSS_PREFIX: sharephotos
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
