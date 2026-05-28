import Foundation
import Photos
import Security

@MainActor
final class SharePhotosStore: ObservableObject {
    @Published var albums: [Album] = []
    @Published var selectedAlbumId: String?
    @Published var uploader = "访客"
    @Published var statusText = "准备好收朋友视角了"
    @Published var isBusy = false
    @Published var uploadProgressText = ""
    @Published var uploadSelectedCount = 0
    @Published var uploadPreparedCount = 0
    @Published var uploadUploadedCount = 0
    @Published var uploadIgnoredCount = 0
    @Published var uploadLivePhotoCount = 0
    @Published var uploadProgressFraction: Double?
    @Published var shareableFile: ShareableFile?
    @Published var operationTitle = ""
    @Published var operationMessage = ""
    @Published var operationProgress: Double?
    @Published var showsOperation = false
    @Published var currentUser: User?
    @Published var authToken: String?
    @Published var authWarning: String?
    @Published var isCheckingAuth = false
    @Published var pendingDeepLink: PendingDeepLink?

    private var api: SharePhotosAPI
    private let exporter = PhotoKitLivePhotoExporter()
    private let saver = LivePhotoSaveService()
    private let tokenStore = KeychainTokenStore()

    init(api: SharePhotosAPI) {
        self.api = api.withBaseURL(api.baseURL)
        self.authToken = tokenStore.readToken()
        self.api.authToken = authToken
        self.api.refreshToken = tokenStore.readRefreshToken()
        self.api.onAuthTokensChanged = { [weak self] response in
            Task { @MainActor in
                self?.updateTokens(from: response)
            }
        }
    }

    var isAuthenticated: Bool {
        authToken != nil && currentUser != nil
    }

    var selectedAlbum: Album? {
        guard let selectedAlbumId else { return nil }
        return albums.first { $0.id == selectedAlbumId }
    }

    func album(id: String) -> Album? {
        albums.first { $0.id == id }
    }

    func folder(albumId: String, folderId: String) -> PhotoFolder? {
        album(id: albumId)?.folders.first { $0.id == folderId }
    }

    func photos(in album: Album, folder: PhotoFolder) -> [Photo] {
        let ids = Set(folder.photoIds ?? [])
        return album.photos
            .filter { ids.contains($0.id) || $0.allFolderIds.contains(folder.id) }
            .sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) }
    }

    func myPhotos(in album: Album) -> [Photo] {
        let ids = Set(album.myPhotoIds ?? [])
        return album.photos
            .filter { ids.contains($0.id) }
            .sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) }
    }

    func previewPhotos(in album: Album, folder: PhotoFolder, limit: Int = 4) -> [Photo] {
        Array(photos(in: album, folder: folder).prefix(limit))
    }

    func folderCoverURL(album: Album, folder: PhotoFolder) -> URL? {
        if let coverUrl = folder.coverUrl, let url = imageURL(coverUrl) {
            return url
        }
        guard let photo = photos(in: album, folder: folder).first else { return nil }
        return imageURL(photo.faceUrl ?? photo.coverUrl ?? photo.thumbnailUrl ?? photo.previewUrl ?? photo.imageUrl)
    }

    func imageURL(_ path: String?) -> URL? {
        guard let value = api.absoluteURLString(path) else { return nil }
        return URL(string: value)
    }

    func login(username: String, password: String) async -> Bool {
        let normalizedUsername = username.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedUsername.isEmpty, !password.isEmpty else {
            statusText = "请输入登录账号和密码"
            return false
        }
        isBusy = true
        showOperation(title: "正在登录", message: "正在确认你的 PicMe 账号", progress: nil)
        defer { isBusy = false }
        do {
            let response = try await api.login(username: normalizedUsername, password: password)
            setAuthenticated(response: response, warning: nil)
            await loadAlbums()
            statusText = "欢迎回来，\(response.user.nickname)"
            return true
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "登录失败", message: message, progress: nil)
            return false
        }
    }

    func register(username: String, nickname: String, password: String, confirmPassword: String, avatarData: Data?) async -> Bool {
        let normalizedUsername = username.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedNickname = nickname.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isValidUsername(normalizedUsername) else {
            statusText = "登录账号需为 1-20 位字母、数字或下划线"
            return false
        }
        guard !normalizedNickname.isEmpty else {
            statusText = "请输入昵称"
            return false
        }
        guard isValidPasswordFormat(password) else {
            statusText = "密码需为 6-20 位，只能使用数字、字母和英文符号"
            return false
        }
        guard password == confirmPassword else {
            statusText = "两次输入的密码不一致"
            return false
        }

        isBusy = true
        showOperation(title: "创建账号", message: "正在准备你的 PicMe 身份", progress: nil)
        defer { isBusy = false }
        do {
            let response = try await api.register(
                username: normalizedUsername,
                nickname: normalizedNickname,
                password: password,
                avatarData: avatarData
            )
            setAuthenticated(response: response, warning: response.warning)
            statusText = response.warning ?? "账号已创建，欢迎 \(response.user.nickname)"
            await loadAlbums()
            return true
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "注册失败", message: message, progress: nil)
            return false
        }
    }

    func loadMe() async {
        guard let tokenSnapshot = authToken else { return }
        isCheckingAuth = true
        defer { isCheckingAuth = false }
        do {
            let user = try await api.me()
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            currentUser = user
            uploader = user.nickname
            clearExpiredStatusIfNeeded()
        } catch {
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            if case APIError.unauthorized = error {
                expireSession()
            } else {
                statusText = error.sharePhotosNetworkMessage
            }
        }
    }

    func logout() async {
        do {
            try await api.logout()
        } catch {
            // 本地退出优先，服务端 token 失效不影响返回登录页。
        }
        clearAuth()
        albums = []
        selectedAlbumId = nil
        statusText = "已退出登录"
    }

    func updateAvatar(avatarData: Data) async -> Bool {
        guard currentUser != nil else { return false }
        let oldAvatarURL = imageURL(currentUser?.avatarUrl)
        isBusy = true
        showOperation(title: "更新头像", message: "正在保存头像并提交后台识别", progress: nil)
        defer { isBusy = false }
        do {
            let response = try await api.updateAvatar(avatarData: avatarData)
            if let oldAvatarURL {
                await PhotoDiskCache.shared.removeCachedFile(for: oldAvatarURL)
            }
            if let newAvatarURL = imageURL(response.user.avatarUrl) {
                await PhotoDiskCache.shared.removeCachedFile(for: newAvatarURL)
            }
            currentUser = response.user
            uploader = response.user.nickname
            authWarning = response.warning
            statusText = response.warning ?? "头像已更新，正在后台识别人脸"
            showOperation(title: "头像已更新", message: response.warning ?? "后台会自动识别头像并匹配你的照片", progress: 1)
            hideOperation(after: 1.0)
            await loadAlbums()
            let tokenSnapshot = authToken
            Task { @MainActor in
                await pollAvatarRecognition(tokenSnapshot: tokenSnapshot)
            }
            return true
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "更新失败", message: message, progress: nil)
            return false
        }
    }

    func loadAlbums() async {
        let tokenSnapshot = authToken
        do {
            let loadedAlbums = try await api.fetchAlbums()
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            albums = loadedAlbums
            reconcileSelectedAlbum()
            clearExpiredStatusIfNeeded()
            hideOperation(after: 0.6)
        } catch {
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            let message = handleError(error, unauthorizedMessage: "相册刷新失败，请稍后重试")
            statusText = message
            showOperation(title: "连接失败", message: message, progress: nil)
        }
    }

    func selectAlbum(id: String) {
        selectedAlbumId = id
    }

    func refreshAlbum(id: String) async {
        do {
            let album = try await api.fetchAlbum(id: id)
            upsert(album)
        } catch {
            statusText = handleError(error)
        }
    }

    func createAlbum(name: String) async -> Album? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            statusText = "先给这次出游起个名字"
            return nil
        }
        isBusy = true
        showOperation(title: "创建相册", message: "正在开一个朋友照片局", progress: nil)
        defer { isBusy = false }
        do {
            let album = try await api.createAlbum(name: trimmed)
            albums.insert(album, at: 0)
            selectedAlbumId = album.id
            statusText = "已创建 \(album.name)"
            hideOperation(after: 0.8)
            return album
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "创建失败", message: message, progress: nil)
            return nil
        }
    }

    func handleIncomingURL(_ url: URL) {
        guard let code = Self.inviteCode(from: url) else { return }
        pendingDeepLink = PendingDeepLink(code: code)
        statusText = isAuthenticated ? "准备申请加入相册 \(code)" : "请先登录，再加入相册 \(code)"
    }

    func clearPendingDeepLink() {
        pendingDeepLink = nil
    }

    func fetchInvite(album: Album) async throws -> AlbumInvite {
        try await api.albumInvite(albumId: album.id)
    }

    func resetInvite(album: Album) async throws -> AlbumInvite {
        try await api.resetAlbumInvite(albumId: album.id)
    }

    func submitJoinRequest(code: String) async -> Bool {
        let normalized = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !normalized.isEmpty else {
            statusText = "请输入相册码"
            return false
        }
        isBusy = true
        showOperation(title: "申请加入", message: "正在确认相册码", progress: nil)
        defer { isBusy = false }
        do {
            let preview = try await api.invite(code: normalized)
            if preview.joinStatus == "member" {
                await loadAlbums()
                selectedAlbumId = preview.invite.albumId
                statusText = "已打开 \(preview.invite.albumName ?? "相册")"
                hideOperation(after: 0.6)
                return true
            }
            let response = try await api.requestJoin(code: normalized)
            statusText = response.message ?? "申请已提交，等待管理员批准"
            showOperation(title: "申请已提交", message: statusText, progress: 1)
            hideOperation(after: 1.2)
            return true
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "申请失败", message: message, progress: nil)
            return false
        }
    }

    func loadJoinRequests(album: Album) async -> [JoinRequest] {
        do {
            return try await api.joinRequests(albumId: album.id)
        } catch {
            statusText = handleError(error)
            return []
        }
    }

    func reviewJoinRequest(album: Album, request: JoinRequest, approve: Bool) async {
        isBusy = true
        showOperation(title: approve ? "批准加入" : "拒绝申请", message: "正在处理 \(request.user.nickname)", progress: nil)
        defer { isBusy = false }
        do {
            let response = try await api.reviewJoinRequest(albumId: album.id, requestId: request.id, approve: approve)
            if let album = response.album {
                upsert(album)
            }
            statusText = approve ? "已批准 \(request.user.nickname) 加入" : "已拒绝申请"
            hideOperation(after: 0.8)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "处理失败", message: message, progress: nil)
        }
    }

    func deleteAlbum(_ album: Album) async {
        isBusy = true
        showOperation(title: "删除相册", message: "正在删除 \(album.name)", progress: nil)
        defer { isBusy = false }
        do {
            try await api.deleteAlbum(id: album.id)
            albums.removeAll { $0.id == album.id }
            if selectedAlbumId == album.id {
                selectedAlbumId = nil
            }
            statusText = "已删除 \(album.name)"
            hideOperation(after: 0.8)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "删除失败", message: message, progress: nil)
        }
    }

    func renameAlbum(_ album: Album, name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            statusText = "相册名字不能为空"
            return
        }
        isBusy = true
        showOperation(title: "保存相册名", message: "正在更新 \(album.name)", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.renameAlbum(id: album.id, name: trimmed)
            upsert(updated)
            statusText = "相册名已保存"
            hideOperation(after: 0.6)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "保存失败", message: message, progress: nil)
        }
    }

    func uploadAssets(_ assets: [PHAsset]) async {
        guard let album = selectedAlbum else {
            statusText = "请先选择一个相册"
            return
        }
        guard !assets.isEmpty else {
            uploadProgressText = ""
            uploadSelectedCount = 0
            uploadPreparedCount = 0
            uploadUploadedCount = 0
            uploadIgnoredCount = 0
            uploadLivePhotoCount = 0
            uploadProgressFraction = nil
            statusText = "已取消选择，未上传照片"
            return
        }

        isBusy = true
        defer { isBusy = false }

        do {
            statusText = "正在读取系统相册原始文件..."
            uploadSelectedCount = assets.count
            uploadPreparedCount = 0
            uploadUploadedCount = 0
            uploadIgnoredCount = 0
            uploadLivePhotoCount = 0
            uploadProgressFraction = 0
            uploadProgressText = "已选择 \(assets.count) 张，正在读取原始文件"
            var files: [UploadFile] = []
            var liveCount = 0
            for (index, asset) in assets.enumerated() {
                uploadPreparedCount = index
                uploadProgressFraction = Double(index) / Double(max(assets.count, 1)) * 0.45
                uploadProgressText = "正在准备第 \(index + 1)/\(assets.count) 张，Live Photo 会保留动态效果"
                let pair = try await exporter.export(asset: asset)
                files.append(contentsOf: pair.files)
                if pair.video != nil {
                    liveCount += 1
                }
                uploadPreparedCount = index + 1
                uploadLivePhotoCount = liveCount
                uploadProgressFraction = Double(index + 1) / Double(max(assets.count, 1)) * 0.45
            }

            statusText = "正在上传 \(assets.count) 张照片..."
            uploadProgressText = "正在上传 \(assets.count) 张朋友视角"
            uploadProgressFraction = 0.65
            let response = try await api.upload(albumId: album.id, uploader: uploader, files: files)
            upsert(response.album)
            statusText = "上传完成：\(assets.count) 张，其中 \(liveCount) 张 Live Photo，后台开始整理"
            uploadUploadedCount = response.queued
            uploadIgnoredCount = response.ignored
            uploadProgressText = "已收到 \(response.queued) 张，忽略 \(response.ignored) 个非照片文件"
            uploadProgressFraction = 1
            await refreshAlbum(id: album.id)
            await pollRecognition(albumId: album.id, tokenSnapshot: authToken)
        } catch {
            let message = handleError(error)
            statusText = message
            uploadProgressText = message
            uploadProgressFraction = nil
        }
    }

    func downloadFolder(album: Album, folder: PhotoFolder) async {
        isBusy = true
        showOperation(title: "下载照片包", message: "正在打包 \(folder.name)", progress: nil)
        defer { isBusy = false }
        do {
            let url = try await api.downloadFolder(albumId: album.id, folderId: folder.id, name: folder.name)
            shareableFile = ShareableFile(url: url)
            statusText = "已打包 \(folder.name)，可保存或分享"
            showOperation(title: "下载完成", message: "照片包已准备好，选择保存或分享", progress: 1)
            hideOperation(after: 1.2)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "下载失败", message: message, progress: nil)
        }
    }

    func deleteFolder(album: Album, folder: PhotoFolder) async {
        isBusy = true
        showOperation(title: "删除小相册", message: "正在删除 \(folder.name)", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.deleteFolder(albumId: album.id, folderId: folder.id)
            upsert(updated)
            statusText = "已删除 \(folder.name)"
            hideOperation(after: 0.8)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "删除失败", message: message, progress: nil)
        }
    }

    func renameFolder(album: Album, folder: PhotoFolder, name: String) async {
        isBusy = true
        showOperation(title: "保存昵称", message: "正在更新小相册名称", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.renameFolder(albumId: album.id, folderId: folder.id, name: name)
            upsert(updated)
            statusText = "昵称已保存"
            hideOperation(after: 0.6)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "保存失败", message: message, progress: nil)
        }
    }

    func movePhoto(album: Album, photo: Photo, targetFolder: PhotoFolder) async {
        isBusy = true
        showOperation(title: "移动照片", message: "正在移动到 \(targetFolder.name)", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.movePhoto(albumId: album.id, photoId: photo.id, targetFolderId: targetFolder.id)
            upsert(updated)
            statusText = "已移动到 \(targetFolder.name)"
            hideOperation(after: 0.7)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "移动失败", message: message, progress: nil)
        }
    }

    func movePhotos(album: Album, photos: [Photo], targetFolder: PhotoFolder) async {
        guard !photos.isEmpty else { return }
        isBusy = true
        showOperation(title: "移动照片", message: "正在移动 1/\(photos.count) 张到 \(targetFolder.name)", progress: 0)
        defer { isBusy = false }
        do {
            var updatedAlbum = album
            for (index, photo) in photos.enumerated() {
                showOperation(
                    title: "移动照片",
                    message: "正在移动第 \(index + 1)/\(photos.count) 张到 \(targetFolder.name)",
                    progress: Double(index) / Double(max(photos.count, 1))
                )
                updatedAlbum = try await api.movePhoto(albumId: album.id, photoId: photo.id, targetFolderId: targetFolder.id)
            }
            upsert(updatedAlbum)
            statusText = "已移动 \(photos.count) 张到 \(targetFolder.name)"
            showOperation(title: "移动完成", message: "已移动 \(photos.count) 张照片", progress: 1)
            hideOperation(after: 1.0)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "移动失败", message: message, progress: nil)
        }
    }

    func deletePhoto(album: Album, photo: Photo) async {
        isBusy = true
        showOperation(title: "删除照片", message: "正在从照片池移除", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.deletePhoto(albumId: album.id, photoId: photo.id)
            upsert(updated)
            statusText = "已删除照片"
            hideOperation(after: 0.7)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "删除失败", message: message, progress: nil)
        }
    }

    func deletePhotos(album: Album, photos: [Photo]) async {
        guard !photos.isEmpty else { return }
        isBusy = true
        showOperation(title: "删除照片", message: "正在删除 \(photos.count) 张照片", progress: nil)
        defer { isBusy = false }
        do {
            let updated = try await api.deleteSelectedPhotos(albumId: album.id, photoIds: photos.map(\.id))
            upsert(updated)
            statusText = "已删除 \(photos.count) 张照片"
            showOperation(title: "删除完成", message: "照片池已更新", progress: 1)
            hideOperation(after: 0.9)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "删除失败", message: message, progress: nil)
        }
    }

    func saveToSystemPhotos(_ photo: Photo) async {
        isBusy = true
        defer { isBusy = false }

        do {
            let authorization = await requestAddOnlyAuthorization()
            guard authorization == .authorized || authorization == .limited else {
                statusText = "需要允许写入系统相册"
                return
            }

            if photo.isLivePhoto {
                statusText = "正在下载完整 Live Photo..."
                showOperation(title: "保存 Live Photo", message: "正在下载 HEIC + MOV 原始资源", progress: nil)
                let resources = try await api.downloadLiveResources(photo: photo)
                showOperation(title: "保存 Live Photo", message: "正在写入系统相册", progress: 0.75)
                try await saver.saveLivePhoto(imageURL: resources.imageURL, videoURL: resources.videoURL)
                statusText = "已保存到系统相册，仍然可以长按播放"
                showOperation(title: "保存完成", message: "已写入系统相册，可长按播放", progress: 1)
            } else {
                statusText = "正在保存照片..."
                showOperation(title: "保存照片", message: "正在下载原图", progress: nil)
                let imageURL = try await api.downloadStillImage(photo: photo)
                showOperation(title: "保存照片", message: "正在写入系统相册", progress: 0.75)
                try await saver.saveStillImage(fileURL: imageURL)
                statusText = "已保存到系统相册"
                showOperation(title: "保存完成", message: "已写入系统相册", progress: 1)
            }
            hideOperation(after: 1.0)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "保存失败", message: message, progress: nil)
        }
    }

    func savePhotosToSystemPhotos(_ photos: [Photo]) async {
        guard !photos.isEmpty else { return }
        isBusy = true
        defer { isBusy = false }

        do {
            let authorization = await requestAddOnlyAuthorization()
            guard authorization == .authorized || authorization == .limited else {
                statusText = "需要允许写入系统相册"
                return
            }

            for (index, photo) in photos.enumerated() {
                let progress = Double(index) / Double(max(photos.count, 1))
                if photo.isLivePhoto {
                    showOperation(title: "保存照片", message: "正在保存第 \(index + 1)/\(photos.count) 张 Live Photo", progress: progress)
                    let resources = try await api.downloadLiveResources(photo: photo)
                    try await saver.saveLivePhoto(imageURL: resources.imageURL, videoURL: resources.videoURL)
                } else {
                    showOperation(title: "保存照片", message: "正在保存第 \(index + 1)/\(photos.count) 张照片", progress: progress)
                    let imageURL = try await api.downloadStillImage(photo: photo)
                    try await saver.saveStillImage(fileURL: imageURL)
                }
            }
            statusText = "已保存 \(photos.count) 张到系统相册"
            showOperation(title: "保存完成", message: "已保存 \(photos.count) 张，Live Photo 仍可长按播放", progress: 1)
            hideOperation(after: 1.2)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "保存失败", message: message, progress: nil)
        }
    }

    func downloadSelectedPackage(album: Album, photos: [Photo]) async {
        guard !photos.isEmpty else { return }
        isBusy = true
        showOperation(title: "打包照片", message: "正在准备 \(photos.count) 个项目", progress: nil)
        defer { isBusy = false }
        do {
            let url = try await api.downloadSelectedPhotos(albumId: album.id, photoIds: photos.map(\.id), name: album.name)
            shareableFile = ShareableFile(url: url)
            statusText = "已打包 \(photos.count) 个项目"
            showOperation(title: "打包完成", message: "可以保存或分享这个照片包", progress: 1)
            hideOperation(after: 1.2)
        } catch {
            let message = handleError(error)
            statusText = message
            showOperation(title: "打包失败", message: message, progress: nil)
        }
    }

    func livePhotoResources(for photo: Photo) async throws -> (imageURL: URL, videoURL: URL) {
        try await api.downloadLiveResources(photo: photo)
    }

    func livePhotoVideo(for photo: Photo) async throws -> URL {
        try await api.downloadLiveVideo(photo: photo)
    }

    private func upsert(_ album: Album) {
        if let index = albums.firstIndex(where: { $0.id == album.id }) {
            albums[index] = album
        } else {
            albums.insert(album, at: 0)
        }
        selectedAlbumId = album.id
    }

    private func reconcileSelectedAlbum() {
        if selectedAlbumId == nil {
            selectedAlbumId = albums.first?.id
        } else if let selectedAlbumId, !albums.contains(where: { $0.id == selectedAlbumId }) {
            self.selectedAlbumId = albums.first?.id
        }
    }

    private func setAuthenticated(response: AuthResponse, warning: String?) {
        currentUser = response.user
        authToken = response.effectiveAccessToken
        authWarning = warning
        tokenStore.save(accessToken: response.effectiveAccessToken, refreshToken: response.refreshToken)
        api.authToken = response.effectiveAccessToken
        api.refreshToken = response.refreshToken
        uploader = response.user.nickname
    }

    private func updateTokens(from response: AuthResponse) {
        authToken = response.effectiveAccessToken
        tokenStore.save(accessToken: response.effectiveAccessToken, refreshToken: response.refreshToken)
        api.authToken = response.effectiveAccessToken
        api.refreshToken = response.refreshToken
    }

    private func clearAuth() {
        currentUser = nil
        authToken = nil
        authWarning = nil
        tokenStore.deleteToken()
        api.authToken = nil
        api.refreshToken = nil
        showsOperation = false
    }

    private func isValidUsername(_ username: String) -> Bool {
        guard (1...20).contains(username.count) else { return false }
        return username.range(of: #"^[A-Za-z0-9_]+$"#, options: .regularExpression) != nil
    }

    private func isValidPasswordFormat(_ password: String) -> Bool {
        guard (6...20).contains(password.count) else { return false }
        return password.unicodeScalars.allSatisfy { (0x21...0x7E).contains($0.value) }
    }

    private static func inviteCode(from url: URL) -> String? {
        let parts = url.pathComponents
        if let joinIndex = parts.firstIndex(of: "join"), parts.indices.contains(joinIndex + 1) {
            let code = parts[joinIndex + 1].trimmingCharacters(in: .whitespacesAndNewlines)
            return code.isEmpty ? nil : code.uppercased()
        }
        if let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
           let code = components.queryItems?.first(where: { $0.name == "invite" })?.value,
           !code.isEmpty {
            return code.uppercased()
        }
        return nil
    }

    private func handleError(_ error: Error, unauthorizedMessage: String = APIError.unauthorized.localizedDescription) -> String {
        if case APIError.unauthorized = error {
            return unauthorizedMessage
        }
        return error.sharePhotosNetworkMessage
    }

    private func expireSession() {
        clearAuth()
        albums = []
        selectedAlbumId = nil
        statusText = APIError.unauthorized.localizedDescription
    }

    private func clearExpiredStatusIfNeeded() {
        guard statusText == APIError.unauthorized.localizedDescription else { return }
        statusText = albums.isEmpty ? "已登录，还没有相册" : "已同步 \(albums.count) 个相册"
    }

    private func tokenStillRepresentsCurrentSession(_ tokenSnapshot: String?) -> Bool {
        authToken == tokenSnapshot || (tokenSnapshot != nil && authToken != nil)
    }

    private func pollAvatarRecognition(tokenSnapshot: String?) async {
        for attempt in 0..<24 {
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            do {
                let user = try await api.me()
                guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
                currentUser = user
                uploader = user.nickname
                if user.hasFaceProfile || user.faceProfileStatus == "ready" {
                    let loadedAlbums = try await api.fetchAlbums()
                    guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
                    albums = loadedAlbums
                    reconcileSelectedAlbum()
                    statusText = "头像识别完成，已更新你的照片推荐"
                    return
                }
                if user.faceProfileStatus == "failed" {
                    statusText = "头像未识别人脸，可以换一张更清晰的正脸头像"
                    return
                }
                let delaySeconds: UInt64 = attempt < 4 ? 1 : 2
                try await Task.sleep(nanoseconds: delaySeconds * 1_000_000_000)
            } catch {
                guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
                return
            }
        }
        guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
        statusText = "头像识别仍在后台进行，稍后刷新即可看到结果"
    }

    private func pollRecognition(albumId: String, tokenSnapshot: String?) async {
        for attempt in 0..<30 {
            guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
            do {
                let album = try await api.fetchAlbum(id: albumId)
                guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
                upsert(album)
                let active = album.photos.filter { $0.isProcessing }.count
                let ready = album.photos.filter { $0.status == "ready" }.count
                let failed = album.photos.filter { $0.status == "failed" }.count
                if active == 0 {
                    showOperation(
                        title: "整理完成",
                        message: "已整理 \(ready) 张，\(failed) 张需要稍后再看",
                        progress: 1
                    )
                    hideOperation(after: 1.5)
                    return
                }
                let progress = min(0.95, 0.72 + Double(attempt) / 30.0 * 0.22)
                showOperation(
                    title: "正在识别人脸",
                    message: "\(active) 张还在整理，已完成 \(ready) 张",
                    progress: progress
                )
                try await Task.sleep(nanoseconds: 1_500_000_000)
            } catch {
                guard tokenStillRepresentsCurrentSession(tokenSnapshot) else { return }
                if case APIError.unauthorized = error {
                    showOperation(title: "后台继续整理", message: "照片识别仍在后台进行，稍后刷新即可看到结果", progress: nil)
                    hideOperation(after: 1.5)
                    return
                }
                let message = handleError(error)
                statusText = message
                showOperation(title: "识别进度刷新失败", message: message, progress: nil)
                return
            }
        }
        showOperation(title: "后台继续整理", message: "照片比较多，稍后刷新即可看到结果", progress: nil)
    }

    private func showOperation(title: String, message: String, progress: Double?) {
        operationTitle = title
        operationMessage = message
        operationProgress = progress
        showsOperation = true
    }

    private func hideOperation(after seconds: Double) {
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            showsOperation = false
        }
    }

    private func requestAddOnlyAuthorization() async -> PHAuthorizationStatus {
        await withCheckedContinuation { (continuation: CheckedContinuation<PHAuthorizationStatus, Never>) in
            PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
                continuation.resume(returning: status)
            }
        }
    }
}

final class KeychainTokenStore {
    private let service = "me.picme.SharePhotos"
    private let accessAccount = "authToken"
    private let refreshAccount = "refreshToken"

    func readToken() -> String? {
        readToken(account: accessAccount)
    }

    func readRefreshToken() -> String? {
        readToken(account: refreshAccount)
    }

    func save(accessToken: String, refreshToken: String?) {
        saveToken(accessToken, account: accessAccount)
        if let refreshToken, !refreshToken.isEmpty {
            saveToken(refreshToken, account: refreshAccount)
        }
    }

    func saveToken(_ token: String) {
        saveToken(token, account: accessAccount)
    }

    func deleteToken() {
        SecItemDelete(baseQuery(account: accessAccount) as CFDictionary)
        SecItemDelete(baseQuery(account: refreshAccount) as CFDictionary)
    }

    private func readToken(account: String) -> String? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func saveToken(_ token: String, account: String) {
        SecItemDelete(baseQuery(account: account) as CFDictionary)
        var query = baseQuery(account: account)
        query[kSecValueData as String] = Data(token.utf8)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(query as CFDictionary, nil)
    }

    private func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }
}
