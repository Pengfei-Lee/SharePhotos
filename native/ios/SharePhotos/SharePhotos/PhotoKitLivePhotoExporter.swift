import Foundation
import Photos
import UniformTypeIdentifiers

final class PhotoKitLivePhotoExporter {
    func export(asset: PHAsset) async throws -> LivePhotoResourcePair {
        let resources = PHAssetResource.assetResources(for: asset)
        guard let photo = resources.first(where: { $0.type == .photo || $0.type == .fullSizePhoto }) else {
            throw LivePhotoExportError.missingPhoto
        }

        let pairedVideo = resources.first(where: { $0.type == .pairedVideo })
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let imageURL = directory.appendingPathComponent(photo.originalFilename)
        try await write(resource: photo, to: imageURL)

        var videoFile: UploadFile?
        if let pairedVideo = pairedVideo {
            let videoURL = directory.appendingPathComponent(pairedVideo.originalFilename)
            try await write(resource: pairedVideo, to: videoURL)
            videoFile = UploadFile(
                url: videoURL,
                filename: pairedVideo.originalFilename,
                contentType: contentType(for: pairedVideo.originalFilename, fallback: "video/quicktime")
            )
        }

        return LivePhotoResourcePair(
            image: UploadFile(
                url: imageURL,
                filename: photo.originalFilename,
                contentType: contentType(for: photo.originalFilename, fallback: "image/heic")
            ),
            video: videoFile
        )
    }

    private func write(resource: PHAssetResource, to url: URL) async throws {
        try? FileManager.default.removeItem(at: url)
        let _: Void = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let options = PHAssetResourceRequestOptions()
            options.isNetworkAccessAllowed = true
            PHAssetResourceManager.default().writeData(for: resource, toFile: url, options: options) { error in
                if let error = error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }

    private func contentType(for filename: String, fallback: String) -> String {
        let ext = (filename as NSString).pathExtension
        guard let type = UTType(filenameExtension: ext)?.preferredMIMEType else {
            return fallback
        }
        return type
    }
}

enum LivePhotoExportError: LocalizedError {
    case missingPhoto

    var errorDescription: String? {
        "没有找到可上传的照片资源"
    }
}
