# SharePhotos iOS App

这个原生 iOS 端用于补齐 Web 无法做到的 Live Photo 原生体验：

- 从系统相册直接选择实况照片，不需要用户手动选择 HEIC 和 MOV 两个文件。
- 上传时通过 PhotoKit 读取 Live Photo 的 `.photo` 和 `.pairedVideo` 原始资源，再按现有 Web 后端的 multipart 接口上传。
- 下载完整 Live Photo 包后，解压出 HEIC 和 MOV，并用 `PHAssetCreationRequest` 写回系统相册。
- 写回后仍然是 iPhone 系统相册里的 Live Photo，可以长按播放、编辑封面帧、设置锁屏或分享到支持 Live Photo 的 App。

## 运行方式

1. 用 Xcode 创建一个新的 iOS App 工程，名称建议 `SharePhotos`，界面选择 SwiftUI。
2. 将 `SharePhotos/` 目录下的 Swift 文件加入工程。
3. 在 Xcode 的 Package Dependencies 中添加 `https://github.com/weichsel/ZIPFoundation.git`，版本固定 `0.9.12`，用于解压完整 Live Photo 下载包。
4. 将 `Info.plist` 中的相册权限文案合并到工程配置。
5. 真机运行。Live Photo 读写必须在真机上验证，模拟器通常无法完整覆盖。

默认服务地址是 `http://localhost:8000`。在手机真机上测试时，需要改成电脑局域网 IP，例如 `http://192.168.0.175:8000`。

## 后端接口约定

沿用当前 Web 后端：

- `GET /api/albums`
- `POST /api/albums/{albumId}/upload`
- `GET /api/albums/{albumId}/photos/{photoId}/download-image`
- `GET /api/albums/{albumId}/photos/{photoId}/download-live`

Live Photo 上传时，iOS 端会把同一个系统资产导出的 `IMG_1234.HEIC` 和 `IMG_1234.MOV` 一起作为 `photos` 字段提交；后端会按同名文件识别为同一个 Live Photo。
