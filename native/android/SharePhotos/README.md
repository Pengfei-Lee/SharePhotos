# SharePhotos Android App

Android 没有 iPhone Live Photo 的统一系统语义，不同厂商的“动态照片 / Motion Photo”实现不完全一致。因此 Android 端目标是：

- 使用系统 Photo Picker 或文件选择器选择照片、视频和厂商 Motion Photo 文件。
- 如果用户从文件选择器拿到了同名 `HEIC/JPG + MOV/MP4`，按现有后端规则上传成 Live Photo。
- 下载时保存到系统相册或下载目录。普通图片按图片保存，Live Photo 完整包按 zip 保存；厂商是否能在相册里继续识别为动态照片，取决于设备相册格式支持。`DownloadSaver` 已提供保存到 MediaStore 的基础能力。

如果要在 Android 端做到“像 iPhone Live Photo 一样长按播放、编辑封面帧、设锁屏”，只能针对具体厂商格式做适配，Android 系统本身没有统一的 Live Photo API。

## 运行方式

1. 用 Android Studio 打开 `native/android/SharePhotos`。
2. 将 `SharePhotosApi.baseUrl` 改成电脑或服务器地址，例如 `http://192.168.0.175:8000`。
3. 真机运行，使用“选择照片”上传。

## 当前后端接口

- `GET /api/albums`
- `POST /api/albums/{albumId}/upload`
- `GET /api/albums/{albumId}/photos/{photoId}/download-image`
- `GET /api/albums/{albumId}/photos/{photoId}/download-live`
