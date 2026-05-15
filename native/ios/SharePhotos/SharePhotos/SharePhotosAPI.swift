import Foundation

final class SharePhotosAPI {
    let baseURL: URL

    init(baseURL: URL) {
        self.baseURL = baseURL
    }

    func withBaseURL(_ baseURL: URL) -> SharePhotosAPI {
        SharePhotosAPI(baseURL: baseURL)
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

    func upload(albumId: String, uploader: String, files: [UploadFile]) async throws -> UploadResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: absoluteURL(path: "/api/albums/\(albumId)/upload"))
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

    func downloadLivePackage(photo: Photo) async throws -> URL {
        guard let path = photo.downloadLiveUrl else {
            throw APIError.missingLiveDownloadURL
        }
        return try await download(path: path, fallbackFilename: "\(photo.id)-live.zip")
    }

    func downloadStillImage(photo: Photo) async throws -> URL {
        guard let path = photo.downloadImageUrl else {
            throw APIError.missingImageDownloadURL
        }
        return try await download(path: path, fallbackFilename: photo.originalName)
    }

    func downloadFolder(albumId: String, folderId: String, name: String) async throws -> URL {
        try await download(path: "/api/albums/\(albumId)/folders/\(folderId)/download", fallbackFilename: "\(name).zip")
    }

    func downloadSelectedPhotos(albumId: String, photoIds: [String], name: String) async throws -> URL {
        try await download(
            path: "/api/albums/\(albumId)/photos/download-selected",
            method: "POST",
            body: ["photoIds": photoIds],
            fallbackFilename: "\(name)-selected.zip"
        )
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
        let url = absoluteURL(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return data
    }

    private func jsonRequest(path: String, method: String, body: [String: Any]) async throws -> Data {
        var request = URLRequest(url: absoluteURL(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        return data
    }

    private func download(path: String, fallbackFilename: String) async throws -> URL {
        try await download(path: path, method: "GET", body: nil, fallbackFilename: fallbackFilename)
    }

    private func download(path: String, method: String, body: [String: Any]?, fallbackFilename: String) async throws -> URL {
        var request = URLRequest(url: absoluteURL(path: path))
        request.httpMethod = method
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (tempURL, response) = try await URLSession.shared.download(for: request)
        guard let httpResponse = response as? HTTPURLResponse, 200..<300 ~= httpResponse.statusCode else {
            throw APIError.badResponse
        }
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension((fallbackFilename as NSString).pathExtension.isEmpty ? "download" : (fallbackFilename as NSString).pathExtension)
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: tempURL, to: destination)
        return destination
    }

    private func absoluteURL(path: String) -> URL {
        if let url = URL(string: path), url.scheme != nil {
            return url
        }
        let base = baseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let normalizedPath = path.hasPrefix("/") ? path : "/\(path)"
        return URL(string: base + normalizedPath)!
    }

    private func appendField(name: String, value: String, boundary: String, to body: inout Data) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(value)\r\n".data(using: .utf8)!)
    }

    private func appendFile(_ file: UploadFile, fieldName: String, boundary: String, to body: inout Data) throws {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(file.filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(file.contentType)\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: file.url))
        body.append("\r\n".data(using: .utf8)!)
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.badResponse
        }
        guard 200..<300 ~= httpResponse.statusCode else {
            let message = String(data: data, encoding: .utf8) ?? "HTTP \(httpResponse.statusCode)"
            throw APIError.server(message)
        }
    }
}

enum APIError: LocalizedError {
    case badResponse
    case server(String)
    case missingLiveDownloadURL
    case missingImageDownloadURL

    var errorDescription: String? {
        switch self {
        case .badResponse:
            return "服务响应异常"
        case .server(let message):
            return message
        case .missingLiveDownloadURL:
            return "这张照片没有完整 Live Photo 下载地址"
        case .missingImageDownloadURL:
            return "这张照片没有静态图下载地址"
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
