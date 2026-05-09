# SharePhotos Native Apps

原生端用于补齐 Web 做不到的系统相册能力，尤其是 iPhone Live Photo：

- iOS：使用 SwiftUI + PhotosUI + PhotoKit。可以从系统相册直接选择 Live Photo，上传 HEIC + MOV 原始资源；下载完整包后写回系统相册，并保持 Live Photo 属性。
- Android：使用 Kotlin + Jetpack Compose + 系统文件选择器。Android 没有统一的 iPhone Live Photo 系统 API，因此支持普通照片、视频、同名图片+视频成对上传，以及厂商 Motion Photo 的尽量保留。

后端仍复用当前 Web 服务，不需要为原生端另起一套 API。

## 目录

- `ios/SharePhotos`: iOS 原生端核心实现。
- `android/SharePhotos`: Android 原生端核心实现。

## 重要边界

iPhone Live Photo 的“长按播放、编辑封面帧、用于锁屏/朋友圈”等能力依赖系统相册识别到原始照片资源和 paired video 资源。Web 页面无法稳定拿到这对原始资源，必须由 iOS 原生端通过 PhotoKit 完成。
