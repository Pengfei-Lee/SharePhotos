import Foundation
import ZIPFoundation

struct DownloadFileManifest: Codable, Hashable {
    let name: String
    let url: String
    let mimeType: String?
    let objectKey: String?
    let size: Int?
}

struct DownloadManifest: Codable, Hashable {
    let type: String
    let filename: String?
    let files: [DownloadFileManifest]?
    let image: DownloadFileManifest?
    let video: DownloadFileManifest?
    let name: String?
    let url: String?
    let mimeType: String?

    var allFiles: [DownloadFileManifest] {
        if let files, !files.isEmpty {
            return files
        }
        if let url {
            return [DownloadFileManifest(name: name ?? filename ?? "download", url: url, mimeType: mimeType, objectKey: nil, size: nil)]
        }
        return [image, video].compactMap { $0 }
    }
}

final class SharePhotosAPI {
    let baseURL: URL
    var authToken: String?
    private let photoCache: PhotoDiskCache

    init(baseURL: URL, authToken: String? = nil, photoCache: PhotoDiskCache = .shared) {
        self.baseURL = baseURL
        self.authToken = authToken
        self.photoCache = photoCache
    }

    func withBaseURL(_ baseURL: URL) -> SharePhotosAPI {
        SharePhotosAPI(baseURL: baseURL, authToken: authToken, photoCache: photoCache)
    }

    func login(username: String, password: String) async throws -> AuthResponse {
        let data = try await jsonRequest(path: "/api/auth/login", method: "POST", body: [
            "username": username,
            "password": password
        ], treatsUnauthorizedAsServerError: true)
        return try JSONDecoder().decode(AuthResponse.self, from: data)
    }

    func register(username: String, nickname: String, password: String, avatarData: Data?) async throws -> AuthResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = authorizedRequest(path: "/api/auth/register")
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        appendField(name: "username", value: username, boundary: boundary, to: &body)
        appendField(name: "nickname", value: nickname, boundary: boundary, to: &body)
        appendField(name: "password", value: password, boundary: boundary, to: &body)
        if let avatarData {
            appendFile(data: avatarData, fieldName: "avatar", filename: "avatar.jpg", contentType: "image/jpeg", boundary: boundary, to: &body)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(AuthResponse.self, from: data)
    }

    func logout() async throws {
        _ = try await request(path: "/api/auth/logout", method: "POST")
    }

    func me() async throws -> User {
        let data = try await request(path: "/api/me")
        return try JSONDecoder().decode(MeResponse.self, from: data).user
    }

    func updateAvatar(avatarData: Data) async throws -> ProfileResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = authorizedRequest(path: "/api/me/avatar")
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        appendFile(data: avatarData, fieldName: "avatar", filename: "avatar.jpg", contentType: "image/jpeg", boundary: boundary, to: &body)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(ProfileResponse.self, from: data)
    }

    func fetchAlbums() async throws -> [Album] {
        let data = try await request(path: "/api/albums")
        return try JSONDecoder().decode(AlbumsResponse.self, from: data).albums
    }

    func fetchAlbum(id: String) async throws -> Album {
        let data = try await request(path: "/api/albums/\(id)")
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func createAlbum(name: String) async throws -> Album {
        let data = try await jsonRequest(path: "/api/albums", method: "POST", body: ["name": name])
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func deleteAlbum(id: String) async throws {
        _ = try await request(path: "/api/albums/\(id)", method: "DELETE")
    }

    func renameAlbum(id: String, name: String) async throws -> Album {
        let data = try await jsonRequest(path: "/api/albums/\(id)/rename", method: "POST", body: ["name": name])
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func albumInvite(albumId: String) async throws -> AlbumInvite {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/invite", method: "POST", body: [:])
        return try JSONDecoder().decode(AlbumInviteResponse.self, from: data).invite
    }

    func resetAlbumInvite(albumId: String) async throws -> AlbumInvite {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/invite/reset", method: "POST", body: [:])
        return try JSONDecoder().decode(AlbumInviteResponse.self, from: data).invite
    }

    func invite(code: String) async throws -> InviteResponse {
        let data = try await request(path: "/api/invites/\(code)")
        return try JSONDecoder().decode(InviteResponse.self, from: data)
    }

    func requestJoin(code: String) async throws -> JoinRequestResponse {
        let data = try await request(path: "/api/invites/\(code)/request", method: "POST")
        return try JSONDecoder().decode(JoinRequestResponse.self, from: data)
    }

    func joinRequests(albumId: String) async throws -> [JoinRequest] {
        let data = try await request(path: "/api/albums/\(albumId)/join-requests")
        return try JSONDecoder().decode(JoinRequestsResponse.self, from: data).requests
    }

    func reviewJoinRequest(albumId: String, requestId: String, approve: Bool) async throws -> ReviewJoinRequestResponse {
        let action = approve ? "approve" : "reject"
        let data = try await request(path: "/api/albums/\(albumId)/join-requests/\(requestId)/\(action)", method: "POST")
        return try JSONDecoder().decode(ReviewJoinRequestResponse.self, from: data)
    }

    func upload(albumId: String, uploader: String, files: [UploadFile]) async throws -> UploadResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = authorizedRequest(path: "/api/albums/\(albumId)/upload")
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        appendField(name: "uploader", value: uploader.isEmpty ? "访客" : uploader, boundary: boundary, to: &body)
        for file in files {
            try appendFile(file, fieldName: "photos", boundary: boundary, to: &body)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(UploadResponse.self, from: data)
    }

    func downloadLiveResources(photo: Photo) async throws -> (imageURL: URL, videoURL: URL) {
        let manifest = try await downloadLiveManifest(photo: photo)
        guard let image = manifest.image ?? manifest.allFiles.first(where: { Self.isLiveImage($0.name) }) else {
            throw APIError.missingLiveImageURL
        }
        let video = try liveVideoFile(from: manifest)
        async let imageURL = downloadManifestFile(image, cachePrefix: "live-image", photoId: photo.id)
        async let videoURL = downloadManifestFile(video, cachePrefix: "live-video", photoId: photo.id)
        return try await (imageURL, videoURL)
    }

    func downloadLiveVideo(photo: Photo) async throws -> URL {
        let manifest = try await downloadLiveManifest(photo: photo)
        let video = try liveVideoFile(from: manifest)
        return try await downloadManifestFile(video, cachePrefix: "live-video", photoId: photo.id)
    }

    func downloadStillImage(photo: Photo) async throws -> URL {
        guard let path = photo.downloadImageUrl else {
            throw APIError.missingImageDownloadURL
        }
        let data = try await request(path: path)
        if let manifest = try? JSONDecoder().decode(DownloadManifest.self, from: data),
           let file = manifest.allFiles.first {
            return try await downloadManifestFile(file, cachePrefix: "still", photoId: photo.id)
        }
        let remoteURL = absoluteURL(path: path)
        return try await downloadRemoteFile(remoteURL, filename: photo.originalName, cachePrefix: "still", cacheId: photo.id)
    }

    func downloadFolder(albumId: String, folderId: String, name: String) async throws -> URL {
        let data = try await request(path: "/api/albums/\(albumId)/folders/\(folderId)/download")
        let manifest = try JSONDecoder().decode(DownloadManifest.self, from: data)
        return try await packageManifestFiles(manifest, fallbackFilename: "\(name).zip")
    }

    func downloadSelectedPhotos(albumId: String, photoIds: [String], name: String) async throws -> URL {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/photos/download-selected", method: "POST", body: ["photoIds": photoIds])
        let manifest = try JSONDecoder().decode(DownloadManifest.self, from: data)
        return try await packageManifestFiles(manifest, fallbackFilename: "\(name)-selected.zip")
    }

    func deleteFolder(albumId: String, folderId: String) async throws -> Album {
        let data = try await request(path: "/api/albums/\(albumId)/folders/\(folderId)", method: "DELETE")
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func renameFolder(albumId: String, folderId: String, name: String) async throws -> Album {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/folders/\(folderId)/rename", method: "POST", body: ["name": name])
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func movePhoto(albumId: String, photoId: String, targetFolderId: String) async throws -> Album {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/photos/\(photoId)/move", method: "POST", body: ["targetFolderId": targetFolderId])
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func deletePhoto(albumId: String, photoId: String) async throws -> Album {
        let data = try await request(path: "/api/albums/\(albumId)/photos/\(photoId)", method: "DELETE")
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func deleteSelectedPhotos(albumId: String, photoIds: [String]) async throws -> Album {
        let data = try await jsonRequest(path: "/api/albums/\(albumId)/photos/delete-selected", method: "POST", body: ["photoIds": photoIds])
        return try JSONDecoder().decode(AlbumResponse.self, from: data).album
    }

    func absoluteURLString(_ path: String?) -> String? {
        guard let path, !path.isEmpty else { return nil }
        return absoluteURL(path: path).absoluteString
    }

    private func request(path: String) async throws -> Data {
        try await request(path: path, method: "GET")
    }

    private func request(path: String, method: String) async throws -> Data {
        var request = authorizedRequest(path: path)
        request.httpMethod = method
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return data
    }

    private func jsonRequest(path: String, method: String, body: [String: Any], treatsUnauthorizedAsServerError: Bool = false) async throws -> Data {
        var request = authorizedRequest(path: path)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data, treatsUnauthorizedAsServerError: treatsUnauthorizedAsServerError)
        return data
    }

    private func downloadManifestFile(_ file: DownloadFileManifest, cachePrefix: String, photoId: String) async throws -> URL {
        let remoteURL = absoluteURL(path: file.url)
        return try await downloadRemoteFile(remoteURL, filename: file.name, cachePrefix: cachePrefix, cacheId: photoId)
    }

    private func downloadLiveManifest(photo: Photo) async throws -> DownloadManifest {
        guard let path = photo.downloadLiveUrl else {
            throw APIError.missingLiveDownloadURL
        }
        let data = try await request(path: path)
        return try JSONDecoder().decode(DownloadManifest.self, from: data)
    }

    private func liveVideoFile(from manifest: DownloadManifest) throws -> DownloadFileManifest {
        guard let video = manifest.video ?? manifest.allFiles.first(where: { Self.isLiveVideo($0.name) }) else {
            throw APIError.missingLiveVideoURL
        }
        return video
    }

    private func downloadRemoteFile(_ remoteURL: URL, filename: String, cachePrefix: String, cacheId: String) async throws -> URL {
        let fallbackExtension = (filename as NSString).pathExtension.isEmpty ? "download" : (filename as NSString).pathExtension
        let preferredExtension = await photoCache.preferredExtension(for: remoteURL, fallback: fallbackExtension)
        let identifier = await cacheIdentifier(prefix: cachePrefix, photoId: cacheId, remoteURL: remoteURL)
        return try await photoCache.file(forIdentifier: identifier, preferredExtension: preferredExtension) {
            try await self.downloadRemoteUncached(remoteURL)
        }
    }

    private func downloadRemoteUncached(_ remoteURL: URL) async throws -> URL {
        let (tempURL, response) = try await URLSession.shared.download(from: remoteURL)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.badResponse
        }
        guard 200..<300 ~= httpResponse.statusCode else {
            throw APIError.badResponse
        }
        return tempURL
    }

    private func packageManifestFiles(_ manifest: DownloadManifest, fallbackFilename: String) async throws -> URL {
        let files = manifest.allFiles
        guard !files.isEmpty else {
            throw APIError.emptyDownloadManifest
        }
        let packageName = manifest.filename ?? fallbackFilename
        let stagingDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
        for file in files {
            let downloaded = try await downloadManifestFile(file, cachePrefix: "package", photoId: file.objectKey ?? file.name)
            let relativePath = Self.safeRelativePath(file.name)
            let destination = stagingDirectory.appendingPathComponent(relativePath)
            try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.copyItem(at: downloaded, to: destination)
        }
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension((packageName as NSString).pathExtension.isEmpty ? "zip" : (packageName as NSString).pathExtension)
        try? FileManager.default.removeItem(at: destination)
        guard let archive = Archive(url: destination, accessMode: .create) else {
            throw APIError.badResponse
        }
        guard let enumerator = FileManager.default.enumerator(
            at: stagingDirectory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            throw APIError.badResponse
        }
        while let fileURL = enumerator.nextObject() as? URL {
            let values = try fileURL.resourceValues(forKeys: [.isRegularFileKey])
            guard values.isRegularFile == true else { continue }
            let entryName = fileURL.path.replacingOccurrences(of: stagingDirectory.path + "/", with: "")
            try archive.addEntry(with: entryName, relativeTo: stagingDirectory)
        }
        try? FileManager.default.removeItem(at: stagingDirectory)
        return destination
    }

    private func cacheIdentifier(prefix: String, photoId: String, remoteURL: URL) async -> String {
        "\(prefix):\(photoId):\(await photoCache.stableIdentifier(for: remoteURL))"
    }

    private func absoluteURL(path: String) -> URL {
        if let url = URL(string: path), url.scheme != nil {
            return url
        }
        let base = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let normalizedPath = path.hasPrefix("/") ? path : "/\(path)"
        return URL(string: base + normalizedPath)!
    }

    private static func isLiveImage(_ name: String) -> Bool {
        ["heic", "heif", "jpg", "jpeg"].contains((name as NSString).pathExtension.lowercased())
    }

    private static func isLiveVideo(_ name: String) -> Bool {
        ["mov", "mp4"].contains((name as NSString).pathExtension.lowercased())
    }

    private static func safeRelativePath(_ path: String) -> String {
        let parts = path.split(separator: "/").map { part in
            part.replacingOccurrences(of: ":", with: "-")
                .replacingOccurrences(of: "\0", with: "")
        }.filter { !$0.isEmpty && $0 != "." && $0 != ".." }
        return parts.isEmpty ? "download" : parts.joined(separator: "/")
    }

    private func authorizedRequest(path: String) -> URLRequest {
        var request = URLRequest(url: absoluteURL(path: path))
        if let authToken, !authToken.isEmpty {
            request.setValue("Bearer \(authToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func appendField(name: String, value: String, boundary: String, to body: inout Data) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(value)\r\n".data(using: .utf8)!)
    }

    private func appendFile(_ file: UploadFile, fieldName: String, boundary: String, to body: inout Data) throws {
        try appendFile(
            data: Data(contentsOf: file.url),
            fieldName: fieldName,
            filename: file.filename,
            contentType: file.contentType,
            boundary: boundary,
            to: &body
        )
    }

    private func appendFile(data: Data, fieldName: String, filename: String, contentType: String, boundary: String, to body: inout Data) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(contentType)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n".data(using: .utf8)!)
    }

    private func validate(response: URLResponse, data: Data, treatsUnauthorizedAsServerError: Bool = false) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.badResponse
        }
        if httpResponse.statusCode == 401 {
            if treatsUnauthorizedAsServerError {
                throw APIError.server(errorMessage(from: data) ?? "登录账号或密码不正确")
            }
            throw APIError.unauthorized
        }
        guard 200..<300 ~= httpResponse.statusCode else {
            throw APIError.server(errorMessage(from: data) ?? "HTTP \(httpResponse.statusCode)")
        }
    }

    private func errorMessage(from data: Data) -> String? {
        if let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = payload["error"] as? String,
           !message.isEmpty {
            return message
        }
        let message = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return message?.isEmpty == false ? message : nil
    }
}

enum APIError: LocalizedError {
    case badResponse
    case unauthorized
    case server(String)
    case missingLiveDownloadURL
    case missingImageDownloadURL
    case missingLiveImageURL
    case missingLiveVideoURL
    case emptyDownloadManifest

    var errorDescription: String? {
        switch self {
        case .badResponse:
            return "服务响应异常"
        case .unauthorized:
            return "登录已失效，请重新登录"
        case .server(let message):
            return message
        case .missingLiveDownloadURL:
            return "这张照片没有完整 Live Photo 下载地址"
        case .missingImageDownloadURL:
            return "这张照片没有静态图下载地址"
        case .missingLiveImageURL:
            return "Live Photo 缺少 HEIC 原图地址"
        case .missingLiveVideoURL:
            return "Live Photo 缺少 MOV 视频地址"
        case .emptyDownloadManifest:
            return "没有可下载的文件"
        }
    }
}

extension Error {
    var sharePhotosNetworkMessage: String {
        if let apiError = self as? APIError {
            return apiError.localizedDescription
        }
        if let urlError = self as? URLError {
            switch urlError.code {
            case .notConnectedToInternet:
                return "连接失败：iOS 可能没有允许本地网络访问，或手机和 Mac 不在同一个 Wi-Fi。请到 设置 > 识我 > 本地网络 打开权限后重试。"
            case .cannotConnectToHost, .timedOut, .networkConnectionLost:
                return "连接失败：没有连上 PicMe 服务。请确认服务已启动、手机和 Mac 在同一个 Wi-Fi，并检查服务地址是否正确。"
            case .cannotFindHost, .unsupportedURL, .badURL:
                return "连接失败：服务地址不正确，请填写 Mac 的局域网地址，例如 http://192.168.3.25:8000。"
            default:
                return urlError.localizedDescription
            }
        }
        return localizedDescription
    }
}
