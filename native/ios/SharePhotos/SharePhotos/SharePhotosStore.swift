import Foundation
import Photos

@MainActor
final class SharePhotosStore: ObservableObject {
    @Published var albums: [Album] = []
    @Published var selectedAlbumId: String?
    @Published var uploader = "访客"
    @Published var statusText = "准备好收朋友视角了"
    @Published var isBusy = false
    @Published var uploadProgressText = ""
    @Published var shareableFile: ShareableFile?
    @Published var operationTitle = ""
    @Published var operationMessage = ""
    @Published var operationProgress: Double?
    @Published var showsOperation = false
    @Published var serverAddress: String
    @Published var isServerSettingsPresented = false

    private var api: SharePhotosAPI
    private let exporter = PhotoKitLivePhotoExporter()
    private let saver = LivePhotoSaveService()
    private let serverAddressKey = "SharePhotosServerAddress"
    private let fallbackServerAddresses = [
        "http://192.168.3.25:8000",
        "http://192.168.0.175:8000"
    ]

    init(api: SharePhotosAPI) {
        let savedAddress = UserDefaults.standard.string(forKey: serverAddressKey)
        let apiAddress = api.baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        var initialAddress = savedAddress ?? apiAddress
        #if !targetEnvironment(simulator)
        if Self.isLocalhostAddress(initialAddress) {
            initialAddress = apiAddress
            UserDefaults.standard.set(apiAddress, forKey: serverAddressKey)
        }
        #endif
        self.serverAddress = initialAddress
        self.api = api.withBaseURL(URL(string: initialAddress) ?? api.baseURL)
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

    func loadAlbums() async {
        showOperation(title: "连接服务中", message: "正在读取 \(serverAddress)", progress: nil)
        do {
            albums = try await fetchAlbumsWithFallback()
            reconcileSelectedAlbum()
            hideOperation(after: 0.6)
        } catch {
            let message = error.sharePhotosNetworkMessage
            statusText = message
            showOperation(title: "连接失败", message: message, progress: nil)
        }
    }

    func updateServerAddress(_ address: String) async -> Bool {
        let normalized = normalizeServerAddress(address)
        guard let url = URL(string: normalized), url.scheme != nil, url.host != nil else {
            let message = "服务地址格式不对，请填写类似 http://192.168.3.25:8000 的地址"
            statusText = message
            showOperation(title: "地址不可用", message: message, progress: nil)
            return false
        }

        showOperation(title: "连接服务中", message: "正在读取 \(normalized)", progress: nil)
        do {
            let candidateAPI = api.withBaseURL(url)
            albums = try await candidateAPI.fetchAlbums()
            api = candidateAPI
            serverAddress = normalized
            UserDefaults.standard.set(normalized, forKey: serverAddressKey)
            reconcileSelectedAlbum()
            statusText = albums.isEmpty ? "已连接服务，还没有相册" : "已连接服务，读取到 \(albums.count) 个相册"
            hideOperation(after: 0.6)
            return true
        } catch {
            let message = error.sharePhotosNetworkMessage
            statusText = message
            showOperation(title: "连接失败", message: message, progress: nil)
            return false
        }
    }

    private func fetchAlbumsWithFallback() async throws -> [Album] {
        var seen = Set<String>()
        let addresses = ([serverAddress] + fallbackServerAddresses)
            .map(normalizeServerAddress)
            .filter { address in
                guard !seen.contains(address) else { return false }
                seen.insert(address)
                return true
            }
        var lastError: Error?

        for address in addresses {
            guard let url = URL(string: address) else { continue }
            do {
                let candidateAPI = api.withBaseURL(url)
                let albums = try await candidateAPI.fetchAlbums()
                api = candidateAPI
                serverAddress = address
                UserDefaults.standard.set(address, forKey: serverAddressKey)
                return albums
            } catch {
                lastError = error
            }
        }

        throw lastError ?? URLError(.cannotConnectToHost)
    }

    private func normalizeServerAddress(_ address: String) -> String {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        let withScheme = trimmed.contains("://") ? trimmed : "http://\(trimmed)"
        return withScheme.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    private static func isLocalhostAddress(_ address: String) -> Bool {
        guard let url = URL(string: address.contains("://") ? address : "http://\(address)") else {
            return false
        }
        return url.host == "localhost" || url.host == "127.0.0.1" || url.host == "::1"
    }

    func selectAlbum(id: String) {
        selectedAlbumId = id
    }

    func refreshAlbum(id: String) async {
        do {
            let album = try await api.fetchAlbum(id: id)
            upsert(album)
        } catch {
            statusText = error.sharePhotosNetworkMessage
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
            statusText = error.localizedDescription
            showOperation(title: "创建失败", message: error.localizedDescription, progress: nil)
            return nil
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
            statusText = error.localizedDescription
            showOperation(title: "删除失败", message: error.localizedDescription, progress: nil)
        }
    }

    func uploadAssets(_ assets: [PHAsset]) async {
        guard let album = selectedAlbum else {
            statusText = "请先选择一个相册"
            return
        }
        guard !assets.isEmpty else {
            uploadProgressText = ""
            statusText = "已取消选择，未上传照片"
            return
        }

        isBusy = true
        defer { isBusy = false }

        do {
            statusText = "正在读取系统相册原始文件..."
            uploadProgressText = "正在读取 \(assets.count) 张原始文件"
            showOperation(title: "准备上传", message: "正在读取系统相册原始文件", progress: 0.05)
            var files: [UploadFile] = []
            var liveCount = 0
            for (index, asset) in assets.enumerated() {
                uploadProgressText = "正在准备第 \(index + 1)/\(assets.count) 张"
                showOperation(
                    title: "准备上传",
                    message: "正在准备第 \(index + 1)/\(assets.count) 张，Live Photo 会保留动态效果",
                    progress: Double(index + 1) / Double(max(assets.count, 1)) * 0.45
                )
                let pair = try await exporter.export(asset: asset)
                files.append(contentsOf: pair.files)
                if pair.video != nil {
                    liveCount += 1
                }
            }

            statusText = "正在上传 \(assets.count) 张照片..."
            uploadProgressText = "上传中，完成后可继续玩，后台会自动分人"
            showOperation(title: "上传中", message: "正在上传 \(assets.count) 张朋友视角", progress: 0.55)
            let response = try await api.upload(albumId: album.id, uploader: uploader, files: files)
            upsert(response.album)
            statusText = "上传完成：\(assets.count) 张，其中 \(liveCount) 张 Live Photo，后台开始整理"
            uploadProgressText = "已收到 \(response.queued) 张，忽略 \(response.ignored) 个非照片文件"
            showOperation(title: "上传完成", message: "已收到 \(response.queued) 张，后台开始识别人脸", progress: 0.7)
            await refreshAlbum(id: album.id)
            await pollRecognition(albumId: album.id)
        } catch {
            statusText = error.localizedDescription
            uploadProgressText = error.localizedDescription
            showOperation(title: "上传失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "下载失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "删除失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "保存失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "移动失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "移动失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "删除失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "删除失败", message: error.localizedDescription, progress: nil)
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
                let zipURL = try await api.downloadLivePackage(photo: photo)
                showOperation(title: "保存 Live Photo", message: "正在写入系统相册", progress: 0.75)
                try await saver.saveLivePackage(zipURL: zipURL)
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
            statusText = error.localizedDescription
            showOperation(title: "保存失败", message: error.localizedDescription, progress: nil)
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
                    let zipURL = try await api.downloadLivePackage(photo: photo)
                    try await saver.saveLivePackage(zipURL: zipURL)
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
            statusText = error.localizedDescription
            showOperation(title: "保存失败", message: error.localizedDescription, progress: nil)
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
            statusText = error.localizedDescription
            showOperation(title: "打包失败", message: error.localizedDescription, progress: nil)
        }
    }

    func livePhotoResources(for photo: Photo) async throws -> (imageURL: URL, videoURL: URL) {
        let zipURL = try await api.downloadLivePackage(photo: photo)
        return try await Task.detached(priority: .userInitiated) {
            try LivePhotoSaveService().extractLivePackage(zipURL: zipURL)
        }.value
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

    private func pollRecognition(albumId: String) async {
        for attempt in 0..<30 {
            do {
                let album = try await api.fetchAlbum(id: albumId)
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
                statusText = error.localizedDescription
                showOperation(title: "识别进度刷新失败", message: error.localizedDescription, progress: nil)
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
