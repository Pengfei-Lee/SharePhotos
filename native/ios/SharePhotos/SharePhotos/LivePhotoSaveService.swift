import Foundation
import Photos

final class LivePhotoSaveService {
    func saveLivePhoto(imageURL: URL, videoURL: URL) async throws {
        try await saveToPhotoLibrary(imageURL: imageURL, pairedVideoURL: videoURL)
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
