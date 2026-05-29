# SharePhotos Android App

Android 没有 iPhone Live Photo 的统一系统语义，不同厂商的“动态照片 / Motion Photo”实现不完全一致。因此 Android 端目标是：

- 使用系统 Photo Picker 或文件选择器选择照片、视频和厂商 Motion Photo 文件。
- 如果用户从文件选择器拿到了同名 `HEIC/JPG + MOV/MP4`，按现有后端规则上传成 Live Photo。
- 文件流量遵循生产链路：业务服务器只负责鉴权、签名和入库，图片、视频、Live Photo 原文件优先通过 OSS 签名 URL 上传或下载。
- 下载时保存到系统相册或下载目录。普通图片按图片保存；Live Photo 先看静态图，用户明确保存或播放动态内容时再下载视频资源。厂商是否能在相册里继续识别为动态照片，取决于设备相册格式支持。`DownloadSaver` 已提供保存到 MediaStore 的基础能力。

如果要在 Android 端做到“像 iPhone Live Photo 一样长按播放、编辑封面帧、设锁屏”，只能针对具体厂商格式做适配，Android 系统本身没有统一的 Live Photo API。

## 运行方式

1. 用 Android Studio 打开 `native/android/SharePhotos`。
2. 客户端默认连接 PicMe 生产服务，不提供用户可见的服务地址切换入口。
3. 真机运行，先登录，再读取已加入相册、选择照片上传或输入相册码申请加入。

## 已对齐的生产能力

- 生产地址固定为 `https://picme.me`，界面不提供地址切换。
- 登录态按 iOS/H5 的双 token 思路保存到 `SharedPreferences`：`accessToken` 用于普通请求，`refreshToken` 用于 401 后无感刷新并重试一次。
- `GET /api/albums` 只展示当前用户已加入的相册，第一本相册会自动填入上传区域，方便低成本验证。
- 支持输入相册码或 `https://picme.me/join/{code}` 分享链接提交加入申请。
- Manifest 已接入 `https://picme.me/join/*` App Link；用户从微信/浏览器扫码打开分享链接时，可把相册码带入 Android 客户端。
- 上传使用 OSS 直传链路：`/uploads/init` 获取签名 URL，客户端 `PUT` 到 OSS，再调用 `/uploads/complete` 完成入库和后台整理。

## 当前后端接口覆盖

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/albums`
- `POST /api/albums/{albumId}/uploads/init`
- `POST /api/albums/{albumId}/uploads/complete`
- `GET /api/invites/{code}`
- `POST /api/invites/{code}/request`
- `GET /api/albums/{albumId}/photos/{photoId}/download-image`
- `GET /api/albums/{albumId}/photos/{photoId}/download-live`

## 后续较大功能

- 摄像头内置扫码需要引入 CameraX + ML Kit 或 ZXing，并处理相机权限、弱光、相册二维码识别等细节；当前低风险实现先支持外部扫码后的 App Link 和手动输入相册码。
- Android UI 仍是原生轻量表单，不是完整 iOS 卡片式相册首页；正式版建议单独做 Material 3 页面、相册详情、照片瀑布流、Live Photo 详情页和审批列表。
- 目前 token 存在 `SharedPreferences`，能满足最小闭环；正式上架前建议迁移到 AndroidX Security EncryptedSharedPreferences 或系统 Keystore。
