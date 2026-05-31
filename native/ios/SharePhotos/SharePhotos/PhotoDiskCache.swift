import Foundation
import UIKit

actor PhotoDiskCache {
    static let shared = PhotoDiskCache()

    private let directoryURL: URL
    private let maxBytes: Int64
    private var inFlight: [String: Task<URL, Error>] = [:]

    init(maxBytes: Int64 = 2 * 1024 * 1024 * 1024) {
        let cachesURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        self.directoryURL = cachesURL.appendingPathComponent("PicMePhotoCache", isDirectory: true)
        self.maxBytes = maxBytes
    }

    func cachedFile(for remoteURL: URL, preferredExtension: String?) async -> URL? {
        let identifier = stableIdentifier(for: remoteURL)
        let destination = fileURL(for: identifier, preferredExtension: preferredExtension)
        guard FileManager.default.fileExists(atPath: destination.path) else { return nil }
        touch(destination)
        return destination
    }

    func file(
        for remoteURL: URL,
        preferredExtension: String?,
        downloader: @escaping () async throws -> URL
    ) async throws -> URL {
        try await file(
            forIdentifier: stableIdentifier(for: remoteURL),
            preferredExtension: preferredExtension,
            downloader: downloader
        )
    }

    func file(
        forIdentifier identifier: String,
        preferredExtension: String?,
        downloader: @escaping () async throws -> URL
    ) async throws -> URL {
        let destination = fileURL(for: identifier, preferredExtension: preferredExtension)
        if FileManager.default.fileExists(atPath: destination.path) {
            touch(destination)
            return destination
        }

        let key = cacheKey(for: identifier)
        if let task = inFlight[key] {
            return try await task.value
        }

        let task = Task<URL, Error> {
            let downloadedURL = try await downloader()
            try await self.store(downloadedURL, at: destination)
            return destination
        }
        inFlight[key] = task

        do {
            let url = try await task.value
            inFlight[key] = nil
            return url
        } catch {
            inFlight[key] = nil
            throw error
        }
    }

    func dataImage(for remoteURL: URL) async throws -> UIImage {
        let preferredExtension = preferredExtension(for: remoteURL, fallback: "img")
        let fileURL = try await file(for: remoteURL, preferredExtension: preferredExtension) {
            try await Self.download(remoteURL)
        }
        return try await Task.detached(priority: .userInitiated) {
            guard let image = UIImage(contentsOfFile: fileURL.path) else {
                throw PhotoDiskCacheError.invalidImage
            }
            return image
        }.value
    }

    func removeCachedFile(for remoteURL: URL, preferredExtension: String? = nil) async {
        let identifier = stableIdentifier(for: remoteURL)
        let key = cacheKey(for: identifier)
        inFlight[key]?.cancel()
        inFlight[key] = nil
        if let preferredExtension {
            try? FileManager.default.removeItem(at: fileURL(for: identifier, preferredExtension: preferredExtension))
            return
        }
        let prefix = key + "."
        guard let files = try? FileManager.default.contentsOfDirectory(at: directoryURL, includingPropertiesForKeys: nil) else {
            return
        }
        for file in files where file.lastPathComponent.hasPrefix(prefix) {
            try? FileManager.default.removeItem(at: file)
        }
    }

    func stableIdentifier(for remoteURL: URL) -> String {
        if var components = URLComponents(url: remoteURL, resolvingAgainstBaseURL: false) {
            components.query = nil
            components.fragment = nil
            if let normalized = components.string, !normalized.isEmpty {
                return normalized
            }
        }
        return remoteURL.absoluteString
    }

    func preferredExtension(for remoteURL: URL, fallback: String) -> String {
        let ext = remoteURL.pathExtension.trimmingCharacters(in: .whitespacesAndNewlines)
        return ext.isEmpty ? fallback : ext.lowercased()
    }

    private func store(_ sourceURL: URL, at destination: URL) async throws {
        try ensureDirectory()
        try? FileManager.default.removeItem(at: destination)
        do {
            try FileManager.default.moveItem(at: sourceURL, to: destination)
        } catch {
            try FileManager.default.copyItem(at: sourceURL, to: destination)
            try? FileManager.default.removeItem(at: sourceURL)
        }
        touch(destination)
        try markExcludedFromBackup(destination)
        Task { await self.trimIfNeeded() }
    }

    private func ensureDirectory() throws {
        if !FileManager.default.fileExists(atPath: directoryURL.path) {
            try FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)
            try markExcludedFromBackup(directoryURL)
        }
    }

    private func fileURL(for identifier: String, preferredExtension: String?) -> URL {
        let ext = sanitizedExtension(preferredExtension)
        return directoryURL.appendingPathComponent(cacheKey(for: identifier)).appendingPathExtension(ext)
    }

    private func cacheKey(for identifier: String) -> String {
        let data = Data(identifier.utf8)
        let hash = data.reduce(UInt64(1469598103934665603)) { partial, byte in
            (partial ^ UInt64(byte)) &* 1099511628211
        }
        return String(hash, radix: 16)
    }

    private func sanitizedExtension(_ ext: String?) -> String {
        let value = (ext ?? "download").trimmingCharacters(in: CharacterSet(charactersIn: ". \n\t")).lowercased()
        guard !value.isEmpty else { return "download" }
        return value.filter { $0.isLetter || $0.isNumber }.prefix(12).isEmpty ? "download" : String(value.filter { $0.isLetter || $0.isNumber }.prefix(12))
    }

    private func touch(_ url: URL) {
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
    }

    private func markExcludedFromBackup(_ url: URL) throws {
        var mutableURL = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try mutableURL.setResourceValues(values)
    }

    private func trimIfNeeded() async {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: directoryURL,
            includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey, .isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            return
        }

        var entries: [(url: URL, size: Int64, modified: Date)] = []
        var total: Int64 = 0
        for url in files {
            guard let values = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey, .isRegularFileKey]),
                  values.isRegularFile == true else {
                continue
            }
            let size = Int64(values.fileSize ?? 0)
            total += size
            entries.append((url, size, values.contentModificationDate ?? .distantPast))
        }

        guard total > maxBytes else { return }
        for entry in entries.sorted(by: { $0.modified < $1.modified }) {
            try? FileManager.default.removeItem(at: entry.url)
            total -= entry.size
            if total <= maxBytes { break }
        }
    }

    private static func download(_ remoteURL: URL) async throws -> URL {
        var request = URLRequest(url: remoteURL)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (tempURL, response) = try await URLSession.shared.download(for: request)
        guard let httpResponse = response as? HTTPURLResponse, 200..<300 ~= httpResponse.statusCode else {
            throw PhotoDiskCacheError.badResponse
        }
        return tempURL
    }
}

enum PhotoDiskCacheError: LocalizedError {
    case badResponse
    case invalidImage

    var errorDescription: String? {
        switch self {
        case .badResponse:
            return "图片下载失败"
        case .invalidImage:
            return "图片缓存无法读取"
        }
    }
}
