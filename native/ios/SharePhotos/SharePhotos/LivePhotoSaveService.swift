import Foundation
import Photos
import ZIPFoundation

final class LivePhotoSaveService {
    func saveLivePackage(zipURL: URL) async throws {
        let (imageURL, videoURL) = try extractLivePackage(zipURL: zipURL)
        try await saveToPhotoLibrary(imageURL: imageURL, pairedVideoURL: videoURL)
    }

    func extractLivePackage(zipURL: URL) throws -> (imageURL: URL, videoURL: URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try FileManager.default.unzipItem(at: zipURL, to: directory)

        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        guard let imageURL = files.first(where: { Self.isLiveImage($0) }) else {
            throw LivePhotoSaveError.missingImage
        }
        guard let videoURL = files.first(where: { Self.isLiveVideo($0) }) else {
            throw LivePhotoSaveError.missingVideo
        }
        return (imageURL, videoURL)
    }

    func saveStillImage(fileURL: URL) async throws {
        let _: Void = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            PHPhotoLibrary.shared().performChanges {
                let request = PHAssetCreationRequest.forAsset()
                request.creationDate = Date()
                request.addResource(with: .photo, fileURL: fileURL, options: nil)
            } completionHandler: { success, error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else if success {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: LivePhotoSaveError.saveFailed)
                }
            }
        }
    }

    private func saveToPhotoLibrary(imageURL: URL, pairedVideoURL: URL) async throws {
        let _: Void = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            PHPhotoLibrary.shared().performChanges {
                let request = PHAssetCreationRequest.forAsset()
                request.creationDate = Date()
                let photoOptions = PHAssetResourceCreationOptions()
                photoOptions.shouldMoveFile = false
                let videoOptions = PHAssetResourceCreationOptions()
                videoOptions.shouldMoveFile = false
                request.addResource(with: .photo, fileURL: imageURL, options: photoOptions)
                request.addResource(with: .pairedVideo, fileURL: pairedVideoURL, options: videoOptions)
            } completionHandler: { success, error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else if success {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: LivePhotoSaveError.saveFailed)
                }
            }
        }
    }

    private static func isLiveImage(_ url: URL) -> Bool {
        ["heic", "heif", "jpg", "jpeg"].contains(url.pathExtension.lowercased())
    }

    private static func isLiveVideo(_ url: URL) -> Bool {
        ["mov", "mp4"].contains(url.pathExtension.lowercased())
    }
}

enum LivePhotoSaveError: LocalizedError {
    case missingImage
    case missingVideo
    case saveFailed

    var errorDescription: String? {
        switch self {
        case .missingImage:
            return "Live Photo 包里没有找到静态照片"
        case .missingVideo:
            return "Live Photo 包里没有找到配套视频"
        case .saveFailed:
            return "写入系统相册失败"
        }
    }
}
