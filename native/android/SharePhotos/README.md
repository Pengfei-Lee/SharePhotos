# SharePhotos Android App

Android 没有 iPhone Live Photo 的统一系统语义，不同厂商的“动态照片 / Motion Photo”实现不完全一致。因此 Android 端目标是：

- 使用系统 Photo Picker 或文件选择器选择照片、视频和厂商 Motion Photo 文件。
- 如果用户从文件选择器拿到了同名 `HEIC/JPG + MOV/MP4`，按现有后端规则上传成 Live Photo。
- 文件流量遵循生产链路：业务服务器只负责鉴权、签名和入库，图片、视频、Live Photo 原文件优先通过 OSS 签名 URL 上传或下载。
- 下载时保存到系统相册或下载目录。普通图片按图片保存；Live Photo 先看静态图，用户明确保存或播放动态内容时再下载视频资源。厂商是否能在相册里继续识别为动态照片，取决于设备相册格式支持。`DownloadSaver` 已提供保存到 MediaStore 的基础能力。

如果要在 Android 端做到“像 iPhone Live Photo 一样长按播放、编辑封面帧、设锁屏”，只能针对具体厂商格式做适配，Android 系统本身没有统一的 Live Photo API。

## 运行方式

1. 用 Android Studio 打开 `native/android/SharePhotos`。
2. 当前工程已配置使用本机 Android SDK API 33；首次打开时按提示等待 Gradle Sync 完成。
3. 客户端默认连接 PicMe 生产服务，不提供用户可见的服务地址切换入口。
4. 手机打开“开发者选项”和“USB 调试”，用 USB 连接 Mac 后在 Android Studio 顶部设备列表选择真机。
5. 点击 Run，先登录，再读取已加入相册、选择照片上传或输入相册码申请加入。

## 推荐编辑工具配置

- Android Studio：推荐使用稳定版，自带 JDK，可直接同步当前 Gradle 工程。
- Project SDK：使用 Android Studio 自带 JBR/JDK 17 或本机 JDK 11+ 均可。
- Gradle：当前工程使用 Android Gradle Plugin `7.4.2`，兼容 Gradle 7.x；如 Android Studio 提示下载 Gradle，允许即可。
- Android SDK：当前可直接使用 API 33；后续正式上架前建议再升级到目标 API 35。
- ADB：安装 Android Studio 的 Platform Tools 后会自带；终端可通过 `~/Library/Android/sdk/platform-tools/adb devices` 查看真机是否已授权。

## 已对齐的生产能力

- 生产地址固定为 `https://picme.me`，界面不提供地址切换。
- 登录态按 iOS/H5 的双 token 思路保存到 `SharedPreferences`：`accessToken` 用于普通请求，`refreshToken` 用于 401 后无感刷新并重试一次。
- `GET /api/albums` 只展示当前用户已加入的相册，首页会先展示本地缓存，再静默同步线上数据。
- 首页、登录页、相册详情、资料页和照片浏览页按 iOS 端视觉方向做了原生轻量对齐。
- 点击首页头像进入资料页，可更换头像、修改昵称、退出登录。
- 支持输入相册码或 `https://picme.me/join/{code}` 分享链接提交加入申请。
- Manifest 已接入 `https://picme.me/join/*` App Link；服务端需要部署 `/.well-known/assetlinks.json` 后，微信/浏览器分享页的“打开识我 App”可唤起 Android 客户端。
- 上传使用 OSS 直传链路：`/uploads/init` 获取签名 URL，客户端 `PUT` 到 OSS，再调用 `/uploads/complete` 完成入库和后台整理。
- 照片详情支持左右切换；Live Photo 先显示静态图，点击播放按钮后再加载视频资源播放。

## 当前后端接口覆盖

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/me/profile`
- `POST /api/me/avatar`
- `GET /api/albums`
- `POST /api/albums/{albumId}/uploads/init`
- `POST /api/albums/{albumId}/uploads/complete`
- `GET /api/invites/{code}`
- `POST /api/invites/{code}/request`
- `GET /api/albums/{albumId}/photos/{photoId}/download-image`
- `GET /api/albums/{albumId}/photos/{photoId}/download-live`

## 后续较大功能

- 摄像头内置扫码需要引入 CameraX + ML Kit 或 ZXing，并处理相机权限、弱光、相册二维码识别等细节；当前低风险实现先支持外部扫码后的 App Link 和手动输入相册码。
- 正式版建议继续补齐 Material 3 组件、审批列表、通知提醒、保存到系统相册等更完整体验。
- 目前 token 存在 `SharedPreferences`，能满足最小闭环；正式上架前建议迁移到 AndroidX Security EncryptedSharedPreferences 或系统 Keystore。
