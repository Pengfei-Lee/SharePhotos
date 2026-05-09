import Foundation

struct Album: Identifiable, Codable, Hashable {
    let id: String
    let name: String
    let photos: [Photo]
    let folders: [PhotoFolder]
    let contributors: [String]

    var photoCount: Int { photos.count }
    var folderCount: Int { folders.count }
}

struct PhotoFolder: Identifiable, Codable, Hashable {
    let id: String
    let name: String
    let photoIds: [String]?
    let updatedAt: Int?
    let coverPhotoId: String?
    let coverUrl: String?

    var count: Int { photoIds?.count ?? 0 }
}

struct Photo: Identifiable, Codable, Hashable {
    let id: String
    let type: String?
    let status: String?
    let originalName: String
    let uploader: String?
    let createdAt: Int?
    let folderId: String?
    let folderIds: [String]?
    let folderName: String?
    let folderNames: [String]?
    let imageUrl: String?
    let previewUrl: String?
    let thumbnailUrl: String?
    let coverUrl: String?
    let tinyUrl: String?
    let faceUrl: String?
    let videoUrl: String?
    let downloadImageUrl: String?
    let downloadLiveUrl: String?

    var isLivePhoto: Bool {
        type == "live_photo" && downloadLiveUrl != nil
    }

    var isProcessing: Bool {
        ["queued", "preparing", "processing"].contains(status ?? "")
    }

    var displayUploader: String {
        let value = (uploader ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "访客" : value
    }

    var allFolderIds: [String] {
        if let folderIds, !folderIds.isEmpty {
            return folderIds
        }
        if let folderId {
            return [folderId]
        }
        return []
    }

    var displayFolderNames: String {
        if let folderNames, !folderNames.isEmpty {
            return folderNames.joined(separator: " / ")
        }
        return folderName ?? "未整理"
    }
}

struct AlbumsResponse: Codable {
    let albums: [Album]
}

struct AlbumResponse: Codable {
    let album: Album
}

struct UploadResponse: Codable {
    let album: Album
    let queued: Int
    let ignored: Int
}

struct DeletedAlbumResponse: Codable {
    let deletedAlbumId: String
}

struct UploadFile {
    let url: URL
    let filename: String
    let contentType: String
}

struct LivePhotoResourcePair {
    let image: UploadFile
    let video: UploadFile?

    var files: [UploadFile] {
        if let video = video {
            return [image, video]
        }
        return [image]
    }
}

enum AppRoute: Hashable {
    case album(String)
    case folder(albumId: String, folderId: String)
    case allPhotos(String)
}

struct ShareableFile: Identifiable {
    let id = UUID()
    let url: URL
}
