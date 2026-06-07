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
- access token 与 refresh token 均失效时会清理旧相册缓存并自动返回登录页，避免停留在不可操作的旧数据页面。
- `GET /api/albums` 只展示当前用户已加入的相册，首页会先展示本地缓存，再静默同步线上数据。
- 首页、登录页、全屏注册页、相册详情、资料页和照片浏览页按 iOS 端视觉方向做了原生轻量对齐；系统返回键会从注册页返回登录、从相册详情返回首页。
- “我的资料”“创建新相册”“加入相册”“分享相册”“申请权限”统一使用全屏页面式容器，不再使用尺寸受限的系统弹窗；头像、昵称、扫码、分享权限和申请进度等操作保持在完整流程页面内。
- 头像、相册封面和照片缩略图使用内存缓存，页面回刷时避免重复下载和闪白。
- 点击首页头像进入资料页，可更换头像、修改昵称、退出登录。
- 注册页支持选择头像、确认密码及与 iOS 一致的账号密码格式校验；退出登录时会同步注销服务端会话。
- 更换头像后会轮询后台识别状态，识别完成自动刷新相册与“我的照片”；资料页展示当前头像识别状态。
- 支持输入相册码、`https://picme.me/join/{code}` 分享链接、实时相机扫码或从相册选择二维码提交加入申请。
- Manifest 已接入 `https://picme.me/join/*` App Link；服务端需要部署 `/.well-known/assetlinks.json` 后，微信/浏览器分享页的“打开识我 App”可唤起 Android 客户端。
- 未登录状态通过分享链接唤起 App 时会保留相册码，登录或注册成功后自动打开加入相册页继续申请。
- 上传使用 OSS 直传链路：`/uploads/init` 获取签名 URL，客户端 `PUT` 到 OSS，再调用 `/uploads/complete` 完成入库和后台整理。
- 相册内点击上传会展示与 iOS 一致的简洁上传页，只保留可选上传者和系统照片选择入口，不暴露相册 ID、OSS 等内部参数。
- 上传过程中底部上传按钮会切换成进度状态，点击可发起取消。
- 上传进度状态会展示标题、百分比、水平进度条和当前步骤，与 iOS 的上传控件保持一致。
- 上传任务从选择照片开始即锁定目标相册；上传中切换页面或打开其他相册不会改变提交目标，进度和取消入口也只显示在原相册。
- 取消上传后会对照上传前的相册照片集合，清理本次已经入库的照片，避免留下半完成内容。
- 上传完成后会持续刷新单个相册的人脸整理状态，整理结束后自动更新人物小相册，并提示成功或失败数量。
- 登录、注册、资料刷新或昵称更新后，上传者默认同步为当前用户昵称；旧照片缺少上传用户 ID 时也会按昵称判断是否属于本人上传。
- 照片详情支持左右切换；Live Photo 先显示静态图，点击播放按钮后再加载视频资源播放。
- 全屏照片浏览的顶部返回、关闭按钮和系统返回键都会回到当前相册，保留浏览上下文。
- 相册详情使用“我的照片 / 人物小相册 / 全部照片”三段式切换，人物小相册支持查看、重命名、下载和删除。
- 进入相册详情时会先展示缓存，再静默刷新单个相册最新数据；人物小相册使用全屏详情页，支持横向切换人物、选择模式和批量操作。
- 照片详情支持保存到系统相册/下载目录，以及按权限规则删除照片。
- “我的照片 / 全部照片”支持选择模式，可全选、保存所选、下载所选照片包和删除所选照片。
- 选择模式支持把所选照片移动到指定人物小相册。
- 创建相册、分享链接、协作用户管理和权限申请已接入四项权限：上传、删除、下载、分享。
- 协作用户页默认只展示用户列表；点按单个用户的“权限”后在当前列表内展开开关，改动会自动保存。
- 分享相册页展示二维码、相册码和分享链接，支持点按复制、系统分享、自动保存链接默认权限和重置相册码。
- 普通协作者可退出相册、申请权限、查看申请进度并撤销待审批申请；创建者可审批加入申请和权限申请。
- 首页提供消息中心入口，支持查看站内消息、点击标记已读、全部已读；审批提醒会跳转审批页，新照片提醒会打开对应相册的“我的照片”。
- 消息提醒、协作用户、协作记录和审批统一使用全屏管理页，顶部关闭与命令区、滚动内容区和卡片视觉与 iOS Sheet 保持一致。
- 全屏管理页会立即展示加载状态；网络失败时在页内显示中文错误和重试入口，不会停留在旧页面或暴露底层英文异常。
- Android 会使用系统后台任务同步未读站内消息并展示通知栏提醒；点击通知会标记消息已读并跳转到审批页或对应相册。当前无需 Firebase 配置，后台同步周期受 Android 系统调度限制。
- 冷启动存在本地登录态时会先静默验证会话，只有 `/api/me` 验证成功后才请求系统通知权限，避免过期会话在登录页打断用户。
- 协作记录、审批历史和消息列表展示操作人或申请人、处理状态及时间，便于后续追溯。
- “已审批”会把加入申请与权限申请合并，并按实际审批时间倒序展示，与 iOS 的统一审批时间线一致。
- 已审批加入申请和权限申请会额外展示实际处理人；Android 6–9 保存照片时会先申请旧版系统存储权限，授权后自动继续刚才的保存操作。

## 当前后端接口覆盖

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/me`
- `POST /api/me/profile`
- `POST /api/me/avatar`
- `GET /api/albums`
- `POST /api/albums`
- `GET /api/albums/{albumId}`
- `DELETE /api/albums/{albumId}`
- `POST /api/albums/{albumId}/rename`
- `POST /api/albums/{albumId}/permissions`
- `POST /api/albums/{albumId}/invite`
- `POST /api/albums/{albumId}/invite/reset`
- `GET /api/albums/{albumId}/members`
- `POST /api/albums/{albumId}/members/{userId}/permissions`
- `DELETE /api/albums/{albumId}/members/{userId}`
- `POST /api/albums/{albumId}/uploads/init`
- `POST /api/albums/{albumId}/uploads/complete`
- `GET /api/albums/{albumId}/folders/{folderId}/download`
- `POST /api/albums/{albumId}/folders/{folderId}/rename`
- `DELETE /api/albums/{albumId}/folders/{folderId}`
- `DELETE /api/albums/{albumId}/photos/{photoId}`
- `POST /api/albums/{albumId}/photos/download-selected`
- `POST /api/albums/{albumId}/photos/delete-selected`
- `POST /api/albums/{albumId}/photos/{photoId}/move`
- `GET /api/albums/{albumId}/collaboration-records`
- `GET /api/albums/{albumId}/join-requests`
- `POST /api/albums/{albumId}/join-requests/{requestId}/approve|reject`
- `GET /api/albums/{albumId}/permission-requests`
- `POST /api/albums/{albumId}/permission-requests`
- `POST /api/albums/{albumId}/permission-requests/{requestId}/approve|reject`
- `DELETE /api/albums/{albumId}/permission-requests/{requestId}`
- `GET /api/invites/{code}`
- `POST /api/invites/{code}/request`
- `GET /api/albums/{albumId}/photos/{photoId}/download-image`
- `GET /api/albums/{albumId}/photos/{photoId}/download-live`
- `GET /api/messages`
- `GET /api/messages/unread-count`
- `POST /api/messages/{messageId}/read`
- `POST /api/messages/mark-read`

## 后续较大功能

- 正式版建议继续补齐 Material 3 组件、更即时的 FCM 推送触发层和更完整的真机视觉适配。
- 目前 token 存在 `SharedPreferences`，能满足最小闭环；正式上架前建议迁移到 AndroidX Security EncryptedSharedPreferences 或系统 Keystore。
