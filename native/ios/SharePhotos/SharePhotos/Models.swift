import Foundation

struct Album: Identifiable, Codable, Hashable {
    let id: String
    let name: String
    let photos: [Photo]
    let folders: [PhotoFolder]
    let contributors: [String]
    let myPhotoIds: [String]?
    let myPhotoCount: Int?
    let myCoverUrl: String?
    let currentUserRole: String?
    let canManage: Bool?
    let canAdmin: Bool?

    var photoCount: Int { photos.count }
    var folderCount: Int { folders.count }
    var isAdmin: Bool { canAdmin == true || ["owner", "admin"].contains(currentUserRole ?? "") }
}

struct User: Identifiable, Codable, Hashable {
    let id: String
    let username: String
    let nickname: String
    let avatarUrl: String?
    let hasFaceProfile: Bool
    let faceProfileStatus: String?
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

struct AuthResponse: Codable {
    let user: User
    let token: String
    let accessToken: String?
    let refreshToken: String?
    let expiresIn: Int?
    let refreshExpiresIn: Int?
    let sessionId: String?
    let warning: String?

    var effectiveAccessToken: String {
        accessToken ?? token
    }
}

struct MeResponse: Codable {
    let user: User
}

struct ProfileResponse: Codable {
    let user: User
    let warning: String?
}

struct AlbumInvite: Identifiable, Codable, Hashable {
    let id: String
    let albumId: String
    let code: String
    let status: String
    let shareUrl: String
    let qrUrl: String
    let albumName: String?
    let photoCount: Int?
    let createdAt: Int?
}

struct InviteResponse: Codable {
    let invite: AlbumInvite
    let joinStatus: String?
    let currentUserRole: String?
}

struct JoinRequestResponse: Codable {
    let status: String
    let requestId: String?
    let message: String?
}

struct AlbumInviteResponse: Codable {
    let invite: AlbumInvite
}

struct JoinRequest: Identifiable, Codable, Hashable {
    let id: String
    let albumId: String
    let status: String
    let createdAt: Int?
    let reviewedAt: Int?
    let user: User
}

struct JoinRequestsResponse: Codable {
    let requests: [JoinRequest]
}

struct ReviewJoinRequestResponse: Codable {
    let status: String
    let album: Album?
}

struct AlbumCollaborationRecord: Identifiable, Codable, Hashable {
    let id: String
    let albumId: String?
    let type: String?
    let title: String?
    let message: String?
    let actor: User?
    let createdAt: Int?

    var displayTitle: String {
        let value = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "协作动态" : value
    }

    var displayMessage: String {
        let value = (message ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "相册成员有新的协作操作" : value
    }
}

struct AlbumCollaborationRecordsResponse: Codable {
    let records: [AlbumCollaborationRecord]
}

struct InboxMessage: Identifiable, Codable, Hashable {
    let id: String
    let type: String?
    let title: String
    let body: String?
    let albumId: String?
    let albumName: String?
    let isRead: Bool
    let createdAt: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case title
        case body
        case albumId
        case albumName
        case isRead
        case read
        case createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        type = try container.decodeIfPresent(String.self, forKey: .type)
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "站内消息"
        body = try container.decodeIfPresent(String.self, forKey: .body)
        albumId = try container.decodeIfPresent(String.self, forKey: .albumId)
        albumName = try container.decodeIfPresent(String.self, forKey: .albumName)
        isRead = try container.decodeIfPresent(Bool.self, forKey: .isRead)
            ?? container.decodeIfPresent(Bool.self, forKey: .read)
            ?? false
        createdAt = try container.decodeIfPresent(Int.self, forKey: .createdAt)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encodeIfPresent(type, forKey: .type)
        try container.encode(title, forKey: .title)
        try container.encodeIfPresent(body, forKey: .body)
        try container.encodeIfPresent(albumId, forKey: .albumId)
        try container.encodeIfPresent(albumName, forKey: .albumName)
        try container.encode(isRead, forKey: .isRead)
        try container.encodeIfPresent(createdAt, forKey: .createdAt)
    }
}

struct InboxMessagesResponse: Codable {
    let messages: [InboxMessage]
    let unreadCount: Int?
}

struct UnreadCountResponse: Codable {
    let unreadCount: Int
}

struct UploadResponse: Codable {
    let album: Album
    let queued: Int
    let ignored: Int
    let photoIds: [String]?
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

struct PendingDeepLink: Identifiable, Hashable {
    let id = UUID()
    let code: String
}

struct PushNavigationRoute: Identifiable, Hashable {
    let id = UUID()
    let destination: String
    let albumId: String?
    let notificationId: String?
}
