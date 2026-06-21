import Photos
import PhotosUI
import SwiftUI
import UIKit

private struct PicMeBackButton: View {
    @Environment(\.dismiss) private var dismiss
    var dark = false

    var body: some View {
        Button {
            dismiss()
        } label: {
            glassIcon("chevron.left", dark: dark)
        }
        .buttonStyle(.plain)
    }
}

private struct PicMeSwipeBackModifier: ViewModifier {
    @Environment(\.dismiss) private var dismiss

    func body(content: Content) -> some View {
        content
            .contentShape(Rectangle())
            .simultaneousGesture(
                DragGesture(minimumDistance: 20, coordinateSpace: .local)
                    .onEnded { value in
                        let isFromLeftEdge = value.startLocation.x <= 34
                        let isBackSwipe = value.translation.width > 72 && abs(value.translation.height) < 80
                        if isFromLeftEdge && isBackSwipe {
                            dismiss()
                        }
                    },
                including: .gesture
            )
    }
}

private extension View {
    func picMeSwipeBack() -> some View {
        modifier(PicMeSwipeBackModifier())
    }
}

private struct PicMeHomeAlbum: Identifiable {
    let id: String
    let title: String
    let photoCount: Int
    let peopleCount: Int
    let myCount: Int
    let newCount: Int
    let newMineCount: Int
    let kind: String
    let members: [String]
    let album: Album?

    static let fallback: [PicMeHomeAlbum] = [
        .init(id: "demo-chongqing", title: "重庆三日游", photoCount: 326, peopleCount: 8, myCount: 48, newCount: 12, newMineCount: 7, kind: "city", members: ["张三", "李四", "王五", "小美"], album: nil),
        .init(id: "demo-hotpot", title: "重庆火锅局", photoCount: 236, peopleCount: 12, myCount: 19, newCount: 5, newMineCount: 3, kind: "food", members: ["张三", "李四", "王五", "飞飞"], album: nil),
        .init(id: "demo-birthday", title: "生日聚会", photoCount: 189, peopleCount: 6, myCount: 23, newCount: 0, newMineCount: 0, kind: "warm", members: ["李四", "小美", "飞飞"], album: nil),
        .init(id: "demo-sanya", title: "三亚旅行", photoCount: 246, peopleCount: 5, myCount: 31, newCount: 0, newMineCount: 0, kind: "nature", members: ["王五", "飞飞", "阿May"], album: nil)
    ]

    init(
        id: String,
        title: String,
        photoCount: Int,
        peopleCount: Int,
        myCount: Int,
        newCount: Int,
        newMineCount: Int,
        kind: String,
        members: [String],
        album: Album?
    ) {
        self.id = id
        self.title = title
        self.photoCount = photoCount
        self.peopleCount = peopleCount
        self.myCount = myCount
        self.newCount = newCount
        self.newMineCount = newMineCount
        self.kind = kind
        self.members = members
        self.album = album
    }

    init(album: Album) {
        id = album.id
        title = album.name
        photoCount = album.photos.count
        peopleCount = max(album.displayPeopleCount, album.displayMemberCount, album.contributors.count)
        myCount = album.myPhotoCount ?? (album.myPhotoIds?.count ?? 0)
        newCount = album.displayNewPhotoCount
        newMineCount = album.displayNewMyPhotoCount
        kind = PicMeHomeAlbum.kind(for: album.name)
        members = memberNames(album)
        self.album = album
    }

    private static func kind(for title: String) -> String {
        if title.contains("火锅") || title.contains("餐") { return "food" }
        if title.contains("三亚") || title.contains("旅行") { return "nature" }
        if title.contains("生日") || title.contains("聚会") { return "warm" }
        return "city"
    }
}

struct PicMeHomeView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let onMessages: () -> Void
    var onNavigationDepthChanged: (Bool) -> Void = { _ in }
    @Binding var pendingAlbumRoute: String?
    @State private var route: HomeRoute?
    private var isPreviewMode: Bool { ProcessInfo.processInfo.environment["PICME_UI_PREVIEW_HOME"] == "1" }

    init(
        onMessages: @escaping () -> Void,
        onNavigationDepthChanged: @escaping (Bool) -> Void = { _ in },
        pendingAlbumRoute: Binding<String?> = .constant(nil)
    ) {
        self.onMessages = onMessages
        self.onNavigationDepthChanged = onNavigationDepthChanged
        _pendingAlbumRoute = pendingAlbumRoute
    }

    private enum HomeRoute: Identifiable {
        case album(String)
        case person(String)

        var id: String {
            switch self {
            case .album(let id): return "album-\(id)"
            case .person(let id): return "person-\(id)"
            }
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                header
                if let visual = alertVisualAlbum {
                    Group {
                        if let album = visual.album {
                            Button {
                                route = .person(album.id)
                            } label: {
                                newMyPhotosBanner(visual)
                            }
                            .buttonStyle(.plain)
                        } else {
                            newMyPhotosBanner(visual)
                        }
                    }
                    .padding(.top, 16)
                }
                PicMeSectionHeader(title: "全部相册")
                    .padding(.top, 20)
                if visualAlbums.isEmpty {
                    emptyState(icon: "photo.on.rectangle", title: "还没有相册", message: "点击底部加号创建第一个共享相册。")
                        .padding(.top, 12)
                } else {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                        ForEach(visualAlbums) { visual in
                            if let album = visual.album {
                                PicMeAlbumCard(visual: visual) {
                                    route = .album(album.id)
                                }
                            } else {
                                PicMeAlbumCard(visual: visual)
                            }
                        }
                    }
                    .padding(.top, 12)
                }
                Spacer(minLength: 108)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .background(PicMeBackground())
        .navigationBarHidden(true)
        .refreshableCompat { await store.loadAlbums() }
        .onChange(of: pendingAlbumRoute) { albumId in
            guard let albumId else { return }
            route = .album(albumId)
            pendingAlbumRoute = nil
        }
        .fullScreenCover(item: $route) { route in
            homeDestination(route)
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("晚上好，\(displayName)")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Text("\(visualAlbums.count) 个相册 · 最近新增 \(recentNewPhotoCount) 张照片")
                    .font(.system(size: 13, weight: .regular))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Button(action: onMessages) {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: "bell")
                        .font(.headline.weight(.bold))
                        .frame(width: 42, height: 42)
                        .background(PicMeStyle.card, in: Circle())
                        .shadow(color: PicMeStyle.ink.opacity(0.06), radius: 12, y: 3)
                        .foregroundColor(PicMeStyle.primaryText)
                    if store.unreadMessageCount > 0 || isPreviewMode {
                        Circle().fill(PicMeStyle.red).frame(width: 9, height: 9).offset(x: -8, y: 8)
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private var visualAlbums: [PicMeHomeAlbum] {
        let albums = store.albums.map(PicMeHomeAlbum.init(album:))
        return albums.isEmpty && isPreviewMode ? PicMeHomeAlbum.fallback : albums
    }

    private var displayName: String {
        if isPreviewMode && store.currentUser == nil {
            return "飞飞"
        }
        return store.currentUser?.nickname ?? store.uploader
    }

    private var recentNewPhotoCount: Int {
        if isPreviewMode && store.albums.isEmpty {
            return 156
        }
        let count = store.albumsSummary?.recentNewPhotoCount ?? visualAlbums.reduce(0) { $0 + $1.newCount }
        return count == 0 && store.albums.isEmpty && isPreviewMode ? 156 : count
    }

    private var alertVisualAlbum: PicMeHomeAlbum? {
        visualAlbums.first { $0.newMineCount > 0 }
    }

    private func myGroup(for album: Album) -> AlbumPeopleGroup {
        if let id = album.myPhotoIds, !id.isEmpty {
            return AlbumPeopleGroup(id: album.myMatchedFolderId ?? "mine", name: album.myMatchedFolderName ?? "我", photoIds: id, photoCount: id.count, coverUrl: album.myCoverUrl)
        }
        return album.displayPeopleGroups.first ?? AlbumPeopleGroup(id: "mine", name: "我", photoIds: [], photoCount: 0, coverUrl: album.myCoverUrl)
    }

    @ViewBuilder
    private func homeDestination(_ route: HomeRoute) -> some View {
        switch route {
        case .album(let id):
            NavigationView {
                PicMeAlbumDetailView(albumId: id) {
                    self.route = nil
                }
            }
            .navigationViewStyle(.stack)
        case .person(let id):
            if let album = store.album(id: id) {
                NavigationView {
                    PicMePersonAlbumView(album: album, group: myGroup(for: album), isSelf: true)
                }
                .navigationViewStyle(.stack)
            } else {
                emptyState(icon: "person.crop.square", title: "照片暂不可用", message: "请下拉刷新相册后重试。")
            }
        }
    }

    private func newMyPhotosBanner(_ visual: PicMeHomeAlbum) -> some View {
        ZStack(alignment: .topTrailing) {
            Circle()
                .fill(.white.opacity(0.12))
                .frame(width: 110, height: 110)
                .offset(x: 40, y: -40)
            HStack(spacing: 13) {
                Image(systemName: "sparkles")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 46, height: 46)
                    .background(.white.opacity(0.22), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                VStack(alignment: .leading, spacing: 3) {
                    Text("发现 \(visual.newMineCount) 张新照片有你")
                        .font(.system(size: 15.5, weight: .semibold))
                        .foregroundColor(.white)
                    Text("「\(visual.title)」新增 \(visual.newCount) 张 · 点击查看")
                        .font(.system(size: 13, weight: .regular))
                        .foregroundColor(.white.opacity(0.9))
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(.white)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 15)
        }
        .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: PicMeStyle.violet.opacity(0.32), radius: 26, y: 10)
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }
}

private struct PicMeAlbumCard: View {
    @EnvironmentObject private var store: SharePhotosStore
    let visual: PicMeHomeAlbum
    var onOpen: (() -> Void)?
    private let coverHeight: CGFloat = 118
    private let cardHeight: CGFloat = 236
    @State private var deckIndex = 0
    @State private var dragOffset: CGSize = .zero
    @State private var departingOffset: CGSize = .zero
    @State private var departingRotation: Double = 0
    @State private var isDeparting = false

    var body: some View {
        PicMeCard(radius: 16) {
            VStack(alignment: .leading, spacing: 0) {
                ZStack(alignment: .topTrailing) {
                    visualCover
                    if visual.newCount > 0 {
                        HStack(spacing: 3) {
                            Image(systemName: "sparkles")
                                .font(.system(size: 11, weight: .bold))
                            Text("+\(visual.newCount)")
                                .font(.system(size: 11, weight: .bold, design: .monospaced))
                        }
                        .foregroundColor(.white)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(PicMeStyle.red, in: Capsule())
                        .shadow(color: .black.opacity(0.2), radius: 8, y: 2)
                        .padding(8)
                    }
                }
                VStack(alignment: .leading, spacing: 0) {
                    Text(visual.title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(PicMeStyle.primaryText)
                        .lineLimit(1)
                    HStack(spacing: 10) {
                        smallStat("photo", "\(visual.photoCount)")
                        smallStat("person.crop.square", "\(visual.myCount)")
                    }
                    .padding(.top, 7)
                    if visual.newCount > 0 {
                        Text(visual.newMineCount > 0 ? "\(visual.newMineCount) 张新照片有你" : "新增 \(visual.newCount) 张")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(PicMeStyle.blue)
                            .padding(.top, 7)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.top, 10)
                .padding(.bottom, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .frame(height: cardHeight - coverHeight, alignment: .top)
            }
        }
        .frame(height: cardHeight, alignment: .top)
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .onTapGesture {
            guard abs(dragOffset.width) < 4, abs(dragOffset.height) < 4 else { return }
            onOpen?()
        }
    }

    private var visualCover: some View {
        PicMeAlbumDeckCover(
            visual: visual,
            urls: deckURLs,
            currentIndex: deckIndex,
            dragOffset: dragOffset,
            departingOffset: departingOffset,
            departingRotation: departingRotation,
            isDeparting: isDeparting,
            height: coverHeight
        )
        .overlay(alignment: .bottomLeading) {
            HStack(spacing: -7) {
                ForEach(Array(visual.members.prefix(3).enumerated()), id: \.offset) { _, name in
                    PicMeAvatar(name: name, size: 20)
                        .overlay(Circle().stroke(.white.opacity(0.95), lineWidth: 1.8))
                }
                if visual.peopleCount > 3 {
                    Text("+\(visual.peopleCount - 3)")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundColor(.white)
                        .frame(width: 20, height: 20)
                        .background(.black.opacity(0.4), in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1.5))
                }
            }
            .padding(8)
        }
        .frame(height: coverHeight)
        .clipped()
        .gesture(coverDragGesture)
    }

    private var deckURLs: [URL?] {
        guard let album = visual.album else { return [] }
        let photos = album.photos.prefix(12).map { photo in
            store.imageURL(photo.coverUrl ?? photo.thumbnailUrl ?? photo.previewUrl ?? photo.imageUrl ?? photo.tinyUrl)
        }
        if !photos.isEmpty { return Array(photos) }
        if let cover = store.imageURL(album.myCoverUrl ?? album.coverUrl ?? album.heroUrl) {
            return [cover]
        }
        return []
    }

    private var coverDragGesture: some Gesture {
        DragGesture(minimumDistance: 4, coordinateSpace: .local)
            .onChanged { value in
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                dragOffset = value.translation
            }
            .onEnded { value in
                let horizontal = value.translation.width
                guard abs(horizontal) > abs(value.translation.height), abs(horizontal) > 44 else {
                    withAnimation(.interpolatingSpring(stiffness: 260, damping: 24)) {
                        dragOffset = .zero
                    }
                    return
                }
                throwTopCard(direction: horizontal >= 0 ? 1 : -1)
            }
    }

    private func throwTopCard(direction: CGFloat) {
        let target = CGSize(width: direction * 190, height: -18)
        withAnimation(.timingCurve(0.16, 1, 0.3, 1, duration: 0.34)) {
            departingOffset = target
            departingRotation = Double(direction * 16)
            isDeparting = true
            dragOffset = .zero
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.20) {
            var transaction = Transaction()
            transaction.disablesAnimations = true
            withTransaction(transaction) {
                deckIndex = nextDeckIndex
                departingOffset = .zero
                departingRotation = 0
                isDeparting = false
            }
        }
    }

    private var nextDeckIndex: Int {
        let count = max(deckURLs.count, 1)
        return (deckIndex + 1) % count
    }
}

private struct PicMeAlbumDeckCover: View {
    let visual: PicMeHomeAlbum
    let urls: [URL?]
    let currentIndex: Int
    let dragOffset: CGSize
    let departingOffset: CGSize
    let departingRotation: Double
    let isDeparting: Bool
    let height: CGFloat

    var body: some View {
        ZStack {
            ForEach(Array(deckSlots.reversed()), id: \.slot) { item in
                coverImage(url: item.url, seed: item.seed)
                    .frame(maxWidth: .infinity)
                    .frame(height: cardHeight(for: item.slot))
                    .clipped()
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(.white.opacity(0.78), lineWidth: 2))
                    .shadow(color: PicMeStyle.ink.opacity(item.slot == 0 ? 0.18 : 0.08), radius: item.slot == 0 ? 12 : 7, y: item.slot == 0 ? 5 : 3)
                    .scaleEffect(scale(for: item.slot))
                    .rotationEffect(.degrees(rotation(for: item.slot)))
                    .offset(offset(for: item.slot))
                    .opacity(opacity(for: item.slot))
                    .zIndex(Double(3 - item.slot))
            }
        }
        .padding(.trailing, 12)
        .padding(.bottom, 10)
        .frame(maxWidth: .infinity)
        .frame(height: height)
        .clipped()
        .animation(.interpolatingSpring(stiffness: 280, damping: 26), value: dragOffset)
    }

    private var deckSlots: [(slot: Int, url: URL?, seed: String)] {
        (0..<3).map { slot in
            let seed = "\(visual.kind)-\(slot)"
            guard !urls.isEmpty else { return (slot, nil, seed) }
            return (slot, urls[(currentIndex + slot) % urls.count], seed)
        }
    }

    @ViewBuilder
    private func coverImage(url: URL?, seed: String) -> some View {
        if let url {
            PicMeRemoteImage(url: url)
        } else {
            PicMeStripePlaceholder(seed: seed)
        }
    }

    private func offset(for slot: Int) -> CGSize {
        let base = CGSize(width: CGFloat(slot) * 8, height: CGFloat(slot) * 7)
        guard slot == 0 else { return base }
        if isDeparting {
            return CGSize(width: departingOffset.width, height: departingOffset.height)
        }
        return CGSize(width: dragOffset.width, height: dragOffset.height)
    }

    private func rotation(for slot: Int) -> Double {
        guard slot == 0 else { return [0, 3.5, -3.0][slot] }
        if isDeparting { return departingRotation }
        return Double(dragOffset.width / 16)
    }

    private func scale(for slot: Int) -> CGFloat {
        slot == 0 ? 1 : 1 - CGFloat(slot) * 0.025
    }

    private func cardHeight(for slot: Int) -> CGFloat {
        height - CGFloat(slot) * 3
    }

    private func opacity(for slot: Int) -> Double {
        guard slot == 0, isDeparting else { return 1 }
        return 0
    }
}

struct PicMeAlbumDetailView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    var onClose: (() -> Void)?
    @State private var tab: DetailTab = .people
    @State private var uploadPresented = false
    @State private var sharePresented = false
    @State private var membersPresented = false
    @State private var settingsPresented = false

    private var album: Album? { store.album(id: albumId) }

    init(albumId: String, onClose: (() -> Void)? = nil) {
        self.albumId = albumId
        self.onClose = onClose
    }

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PicMeStyle.background.ignoresSafeArea()
            ScrollView {
                if let album {
                    VStack(alignment: .leading, spacing: 0) {
                        hero(album)
                        VStack(alignment: .leading, spacing: 16) {
                            NavigationLink(destination: PicMePersonAlbumView(album: album, group: myGroup(album), isSelf: true)) {
                                HStack(spacing: 12) {
                                    Image(systemName: "sparkles")
                                        .foregroundColor(.white)
                                        .frame(width: 38, height: 38)
                                        .background(PicMeStyle.gradient, in: Circle())
                                    Text("你出现在 \(album.myPhotoCount ?? myGroup(album).count) 张照片")
                                        .font(.subheadline.weight(.black))
                                        .foregroundColor(PicMeStyle.primaryText)
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundColor(PicMeStyle.blue)
                                }
                                .padding(14)
                                .background(PicMeStyle.softGradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            }
                            .buttonStyle(.plain)
                            PicMeSegmentedControl(items: DetailTab.allCases, selection: $tab) { $0.title }
                            tabContent(album)
                        }
                        .padding(20)
                        .background(PicMeStyle.background)
                        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                        .offset(y: -20)
                    }
                } else {
                    ProgressView("正在打开相册").padding(40)
                }
            }
            .background(PicMeBackground())
            .navigationBarHidden(true)

            Button {
                guard let album else { return }
                if album.effectivePermissions.upload {
                    uploadPresented = true
                } else {
                    store.showPermissionDenied(album: album, action: "上传")
                }
            } label: {
                Image(systemName: "arrow.up")
                    .font(.title3.weight(.black))
                    .foregroundColor(.white)
                    .frame(width: 58, height: 58)
                    .background(PicMeStyle.gradient, in: Circle())
                    .shadow(color: PicMeStyle.blue.opacity(0.4), radius: 18, y: 8)
            }
            .buttonStyle(.plain)
            .padding(.trailing, 18)
            .padding(.bottom, 28)
            .zIndex(10)
        }
        .task {
            store.selectAlbum(id: albumId)
            await store.refreshAlbum(id: albumId)
        }
        .fullScreenCover(isPresented: $uploadPresented) {
            PicMeUploadView(albumId: albumId)
        }
        .fullScreenCover(isPresented: $sharePresented) {
            if let album {
                PicMeShareView(album: album)
            }
        }
        .fullScreenCover(isPresented: $membersPresented) {
            if let album {
                PicMeMembersView(album: album)
            }
        }
        .fullScreenCover(isPresented: $settingsPresented) {
            if let album {
                PicMeAlbumSettingsView(album: album) {
                    settingsPresented = false
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                        sharePresented = true
                    }
                }
            }
        }
        .picMeSwipeBack()
    }

    private enum DetailTab: String, CaseIterable, Identifiable, Hashable {
        case people, groups, all
        var id: String { rawValue }
        var title: String {
            switch self {
            case .people: return "人物"
            case .groups: return "合照"
            case .all: return "全部"
            }
        }
    }

    private func hero(_ album: Album) -> some View {
        ZStack(alignment: .bottomLeading) {
            albumCover(album, height: 236, radius: 0)
            LinearGradient(colors: [.black.opacity(0.35), .clear, .black.opacity(0.55)], startPoint: .top, endPoint: .bottom)
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button {
                        close()
                    } label: {
                        glassIcon("chevron.left", dark: true)
                            .frame(width: 56, height: 56)
                            .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("返回")
                    .zIndex(20)
                    Spacer()
                    Button { sharePresented = true } label: { glassIcon("square.and.arrow.up", dark: true) }
                    Button { settingsPresented = true } label: { glassIcon("ellipsis", dark: true) }
                }
                Spacer()
                HStack(spacing: 8) {
                    Text(album.name)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundColor(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                    Image(systemName: "pencil")
                        .font(.system(size: 20, weight: .regular))
                        .foregroundColor(.white.opacity(0.85))
                }
                Button { membersPresented = true } label: {
                    HStack(spacing: 10) {
                        PicMeAvatarStack(names: memberNames(album), size: 28, limit: 4)
                        Text("\(max(album.displayMemberCount, memberNames(album).count)) 人参与 · \(album.photos.count) 张照片")
                            .font(.system(size: 13, weight: .regular))
                            .foregroundColor(.white.opacity(0.92))
                            .lineLimit(1)
                        Image(systemName: "chevron.right").font(.caption.weight(.bold))
                    }
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 14)
            .padding(.top, 50)
            .padding(.bottom, 18)
        }
        .frame(height: 236)
    }

    private func close() {
        if let onClose {
            onClose()
        } else {
            dismiss()
        }
    }

    private func tabContent(_ album: Album) -> some View {
        Group {
            switch tab {
            case .people:
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 18) {
                    ForEach(album.displayPeopleGroups) { group in
                        NavigationLink(destination: PicMePersonAlbumView(album: album, group: group, isSelf: group.id == album.myMatchedFolderId)) {
                            VStack(spacing: 8) {
                                PicMePersonAvatar(name: group.name, url: personAvatarURL(for: group, in: album), size: 72)
                                    .overlay(Circle().stroke(PicMeStyle.blue, lineWidth: 3))
                                Text(group.name).font(.caption.weight(.black)).foregroundColor(PicMeStyle.primaryText).lineLimit(1)
                                Text("\(group.count) 张").font(.caption2.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            case .groups:
                VStack(alignment: .leading, spacing: 12) {
                    Label("同一张照片识别到多张人脸自动归类", systemImage: "sparkles")
                        .font(.caption.weight(.semibold))
                        .foregroundColor(PicMeStyle.secondaryText)
                    ForEach(album.displayCoPhotoGroups) { group in
                        NavigationLink(destination: PicMeCoPhotoView(album: album, group: group)) {
                            PicMeCoPhotoRow(group: group)
                        }
                        .buttonStyle(.plain)
                    }
                    if album.displayCoPhotoGroups.isEmpty {
                        emptyState(icon: "person.2.crop.square.stack", title: "暂无合照分组", message: "识别到多人同框后会自动出现在这里。")
                    }
                }
            case .all:
                PicMePhotoGrid(album: album, photos: album.photos.sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) })
            }
        }
    }

    private func myGroup(_ album: Album) -> AlbumPeopleGroup {
        if let id = album.myMatchedFolderId, let group = album.displayPeopleGroups.first(where: { $0.id == id }) {
            return group
        }
        return album.displayPeopleGroups.first ?? AlbumPeopleGroup(id: "mine", name: "我", photoIds: album.myPhotoIds ?? [], photoCount: album.myPhotoCount, coverUrl: album.myCoverUrl)
    }

    private func personAvatarURL(for group: AlbumPeopleGroup, in album: Album) -> URL? {
        let ids = Set(group.photoIds)
        let groupPhotos = album.photos
            .filter { ids.contains($0.id) || $0.allFolderIds.contains(group.id) }
            .sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) }
        for photo in groupPhotos {
            if let url = store.imageURL(photo.faceUrl ?? photo.coverUrl ?? photo.thumbnailUrl ?? photo.previewUrl ?? photo.imageUrl) {
                return url
            }
        }
        return store.imageURL(group.coverUrl)
    }
}

private struct PicMePersonAvatar: View {
    let name: String
    let url: URL?
    let size: CGFloat

    var body: some View {
        ZStack {
            PicMeAvatar(name: name, size: size)
            if let url {
                PicMeRemoteImage(url: url)
                    .frame(width: size, height: size)
                    .clipShape(Circle())
                    .overlay(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [.clear, .black.opacity(0.18)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    )
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .contentShape(Circle())
    }
}

private struct PicMeCoPhotoRow: View {
    @EnvironmentObject private var store: SharePhotosStore
    let group: AlbumCoPhotoGroup

    var body: some View {
        PicMeCard(radius: 16) {
            HStack(spacing: 13) {
                ZStack(alignment: .topLeading) {
                    PicMeRemoteImage(url: store.imageURL(group.coverUrl))
                    picMeBadge("\(group.faceCount) 人", color: .black.opacity(0.55))
                        .padding(6)
                }
                .frame(width: 72, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                VStack(alignment: .leading, spacing: 5) {
                    Text(group.name).font(.headline.weight(.black)).foregroundColor(PicMeStyle.primaryText).lineLimit(1)
                    Text("\(group.faceCount) 人同框 · \(group.count) 张合照").font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
                    PicMeAvatarStack(names: group.people, size: 24, limit: 3)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundColor(PicMeStyle.secondaryText.opacity(0.55))
            }
            .padding(11)
        }
    }
}

struct PicMeAlbumDetailPrototypeView: View {
    @State private var tab: DetailTab = .people
    @State private var settingsOpen = false

    private enum DetailTab: String, CaseIterable, Identifiable {
        case people, groups, all
        var id: String { rawValue }
        var title: String {
            switch self {
            case .people: return "人物"
            case .groups: return "合照"
            case .all: return "全部"
            }
        }
    }

    private let members = ["张三", "李四", "王五", "小美"]
    private let people: [(String, Int)] = [("飞飞", 48), ("张三", 65), ("李四", 42), ("王五", 39), ("小美", 30)]
    private let groups: [(String, [String], Int, Int, String)] = [
        ("全员同框", ["张三", "李四", "王五", "小美", "飞飞", "阿May"], 6, 8, "people"),
        ("你 和 张三", ["飞飞", "张三"], 2, 15, "warm"),
        ("三人行", ["李四", "王五", "小美"], 3, 9, "city"),
        ("李四 和 王五", ["李四", "王五"], 2, 12, "nature")
    ]
    private let tiles: [(String, String, CGFloat, Bool)] = [
        ("food", "火锅", 1.0, false), ("city", "洪崖洞夜景", 1.5, true), ("people", "合照 · 6人", 0.78, false),
        ("nature", "长江索道", 0.8, false), ("people", "人物 A", 1.0, false), ("warm", "江湖菜", 1.3, false),
        ("night", "夜景", 1.4, false), ("people", "合照 · 4人", 0.85, true), ("cool", "解放碑", 1.0, false)
    ]

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PicMeStyle.background.ignoresSafeArea()
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    hero
                    VStack(alignment: .leading, spacing: 0) {
                        myBanner
                            .padding(.top, 16)
                        segmented
                            .padding(.top, 16)
                        tabContent
                            .padding(.top, tab == .all ? 18 : 20)
                    }
                    .padding(.horizontal, tab == .all ? 16 : 20)
                    .padding(.bottom, 120)
                    .background(PicMeStyle.background)
                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .offset(y: -20)
                }
            }
            .ignoresSafeArea(edges: .top)
            .background(PicMeStyle.background)

            Button {} label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 25, weight: .semibold))
                    .foregroundColor(.white)
                    .frame(width: 56, height: 56)
                    .background(PicMeStyle.gradient, in: Circle())
                    .shadow(color: PicMeStyle.blue.opacity(0.45), radius: 24, y: 10)
            }
            .buttonStyle(.plain)
            .padding(.trailing, 18)
            .padding(.bottom, 30)
            .zIndex(10)
        }
        .sheet(isPresented: $settingsOpen) {
            PicMeAlbumSettingsPrototypeSheet()
        }
    }

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            PicMeStripePlaceholder(seed: "night")
            LinearGradient(colors: [PicMeStyle.ink.opacity(0.35), .clear, PicMeStyle.ink.opacity(0.55)], startPoint: .top, endPoint: .bottom)
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    PicMeBackButton(dark: true)
                    Spacer()
                    glassIcon("square.and.arrow.up", dark: true)
                    Button { settingsOpen = true } label: { glassIcon("ellipsis", dark: true) }
                        .buttonStyle(.plain)
                }
                Spacer()
                HStack(spacing: 8) {
                    Text("重庆三日游")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundColor(.white)
                    Image(systemName: "pencil")
                        .font(.system(size: 20, weight: .regular))
                        .foregroundColor(.white.opacity(0.85))
                }
                HStack(spacing: 10) {
                    PicMeAvatarStack(names: members, size: 28, limit: 4)
                    Text("8 人参与 · 326 张照片")
                        .font(.system(size: 13, weight: .regular))
                        .foregroundColor(.white.opacity(0.9))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.white.opacity(0.85))
                }
            }
            .padding(.horizontal, 14)
            .padding(.top, 50)
            .padding(.bottom, 18)
        }
        .frame(height: 236)
    }

    private var myBanner: some View {
        HStack(spacing: 12) {
            Image(systemName: "sparkles")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(.white)
                .frame(width: 38, height: 38)
                .background(PicMeStyle.gradient, in: Circle())
            Text("你出现在 48 张照片")
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(PicMeStyle.blue)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(PicMeStyle.softGradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(PicMeStyle.blue.opacity(0.18), lineWidth: 0.5))
    }

    private var segmented: some View {
        HStack(spacing: 22) {
            ForEach(DetailTab.allCases) { item in
                Button {
                    tab = item
                } label: {
                    VStack(spacing: 0) {
                        Text(item.title)
                            .font(.system(size: 15, weight: tab == item ? .bold : .medium))
                            .foregroundColor(tab == item ? PicMeStyle.primaryText : PicMeStyle.secondaryText)
                            .padding(.bottom, 12)
                        Capsule()
                            .fill(tab == item ? AnyShapeStyle(PicMeStyle.gradient) : AnyShapeStyle(Color.clear))
                            .frame(height: 3)
                    }
                    .fixedSize()
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .overlay(alignment: .bottom) {
            Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5)
        }
    }

    @ViewBuilder
    private var tabContent: some View {
        switch tab {
        case .people:
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 18) {
                ForEach(people, id: \.0) { name, count in
                    VStack(spacing: 7) {
                        PicMeAvatar(name: name, size: 70)
                            .padding(2.5)
                            .background(PicMeStyle.gradient, in: Circle())
                            .overlay(Circle().stroke(.white, lineWidth: 2.5))
                        Text(name)
                            .font(.system(size: 13.5, weight: .semibold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text("\(count) 张")
                            .font(.system(size: 11.5, weight: .regular))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                }
            }
        case .groups:
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(PicMeStyle.blue)
                    Text("同一张照片识别到多张人脸自动归类")
                        .font(.system(size: 12.5))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
                ForEach(groups, id: \.0) { group in
                    groupRow(group)
                }
            }
        case .all:
            HStack(alignment: .top, spacing: 8) {
                masonryColumn(Array(tiles.enumerated()).filter { $0.offset % 2 == 0 }.map(\.element))
                masonryColumn(Array(tiles.enumerated()).filter { $0.offset % 2 == 1 }.map(\.element))
            }
        }
    }

    private func groupRow(_ item: (String, [String], Int, Int, String)) -> some View {
        HStack(spacing: 13) {
            ZStack(alignment: .topLeading) {
                PicMeStripePlaceholder(seed: item.4)
                HStack(spacing: 3) {
                    Image(systemName: "person.2")
                        .font(.system(size: 11, weight: .semibold))
                    Text("\(item.2)")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                }
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(.white.opacity(0.88), in: Capsule())
                .padding(5)
            }
            .frame(width: 72, height: 72)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(item.0)
                    .font(.system(size: 15.5, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("\(item.2) 人同框 · \(item.3) 张合照")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
                PicMeAvatarStack(names: item.1, size: 24, limit: 3)
                    .padding(.top, 6)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Color(hex: 0xC7CDD6))
        }
        .padding(11)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 12, y: 3)
    }

    private func masonryColumn(_ items: [(String, String, CGFloat, Bool)]) -> some View {
        VStack(spacing: 8) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                PicMeStripePlaceholder(seed: item.0)
                    .overlay {
                        if !item.1.isEmpty {
                            Text(item.1)
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .foregroundColor(PicMeStyle.ink.opacity(0.5))
                        }
                    }
                    .overlay(alignment: .topLeading) {
                        if item.3 {
                            Text("LIVE")
                                .font(.system(size: 9.5, weight: .bold, design: .monospaced))
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(.white.opacity(0.82), in: Capsule())
                                .padding(7)
                        }
                    }
                    .aspectRatio(1 / item.2, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }
}

private struct PicMeAlbumSettingsPrototypeSheet: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Capsule().fill(PicMeStyle.ink.opacity(0.14)).frame(width: 38, height: 5).frame(maxWidth: .infinity)
            HStack {
                Text("相册设置")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Spacer()
                Text("完成")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(PicMeStyle.blue)
            }
            VStack(spacing: 0) {
                settingsRow("分享与邀请", icon: "square.and.arrow.up")
                Divider().padding(.leading, 58)
                settingsRow("重命名相册", icon: "pencil")
            }
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            sectionTitle("成员默认权限", subtitle: nil)
            PermissionList(permissions: .allAllowed)
            Spacer()
        }
        .padding(.horizontal, 20)
        .padding(.top, 10)
        .background(PicMeStyle.background)
    }
}

private struct PicMePersonAlbumView: View {
    let album: Album
    let group: AlbumPeopleGroup
    var isSelf = false

    private var photos: [Photo] {
        let ids = Set(group.photoIds)
        if ids.isEmpty { return album.photos }
        return album.photos.filter { ids.contains($0.id) || $0.allFolderIds.contains(group.id) }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                PicMeTopBar(title: isSelf ? "我的照片" : group.name, subtitle: "来自「\(album.name)」")
                PicMeAvatar(name: group.name, size: 94)
                    .overlay(Circle().stroke(PicMeStyle.blue, lineWidth: 4))
                Text(group.name + (isSelf ? " (我)" : ""))
                    .font(.title2.weight(.black))
                    .foregroundColor(PicMeStyle.primaryText)
                HStack(spacing: 0) {
                    statBlock("\(photos.count)", "张照片")
                    statBlock("1", "个相册")
                }
                PicMePhotoGrid(album: album, photos: photos)
            }
            .padding(.bottom, 34)
        }
        .background(PicMeBackground())
        .navigationBarHidden(true)
        .picMeSwipeBack()
    }
}

private struct PicMeCoPhotoView: View {
    let album: Album
    let group: AlbumCoPhotoGroup

    private var photos: [Photo] {
        let ids = Set(group.photoIds)
        return album.photos.filter { ids.contains($0.id) }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                PicMeTopBar(title: "合照", subtitle: "来自「\(album.name)」")
                PicMeAvatarStack(names: group.people, size: 58, limit: 5)
                Text(group.name)
                    .font(.title2.weight(.black))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("\(group.faceCount) 人同框 · \(photos.count) 张合照")
                    .font(.caption.weight(.semibold))
                    .foregroundColor(PicMeStyle.secondaryText)
                PicMePhotoGrid(album: album, photos: photos)
            }
            .padding(.bottom, 34)
        }
        .background(PicMeBackground())
        .navigationBarHidden(true)
        .picMeSwipeBack()
    }
}

private struct PicMePhotoGrid: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let photos: [Photo]
    @State private var selectedPhoto: Photo?
    @State private var gridColumnCount = 3
    @GestureState private var pinchScale: CGFloat = 1

    private var effectiveGridColumnCount: Int {
        clampedColumnCount(Int((CGFloat(gridColumnCount) / max(pinchScale, 0.45)).rounded()))
    }

    var body: some View {
        let spacing: CGFloat = effectiveGridColumnCount <= 3 ? 4 : 2
        let columns = Array(repeating: GridItem(.flexible(), spacing: spacing), count: effectiveGridColumnCount)

        LazyVGrid(columns: columns, spacing: spacing) {
            ForEach(photos) { photo in
                Button { selectedPhoto = photo } label: {
                    GeometryReader { proxy in
                        ZStack(alignment: .topLeading) {
                            PicMeRemoteImage(url: photoURL(photo))
                                .frame(width: proxy.size.width, height: proxy.size.height)
                                .clipped()
                            if photo.isLivePhoto {
                                picMeBadge("LIVE", color: .black.opacity(0.45))
                                    .padding(effectiveGridColumnCount <= 4 ? 6 : 3)
                                    .scaleEffect(effectiveGridColumnCount <= 4 ? 1 : 0.78, anchor: .topLeading)
                            }
                        }
                    }
                    .aspectRatio(1, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: gridCornerRadius, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 4)
        .contentShape(Rectangle())
        .simultaneousGesture(gridZoomGesture, including: .all)
        .animation(.spring(response: 0.22, dampingFraction: 0.88), value: effectiveGridColumnCount)
        .fullScreenCover(item: $selectedPhoto) { photo in
            PicMePhotoPreview(album: album, photos: photos, initialPhoto: photo)
        }
    }

    private var gridZoomGesture: some Gesture {
        MagnificationGesture(minimumScaleDelta: 0.015)
            .updating($pinchScale) { value, state, _ in
                state = value
            }
            .onEnded { value in
                let target = clampedColumnCount(Int((CGFloat(gridColumnCount) / max(value, 0.45)).rounded()))
                guard target != gridColumnCount else { return }
                withAnimation(.spring(response: 0.24, dampingFraction: 0.86)) {
                    gridColumnCount = target
                }
            }
    }

    private var gridCornerRadius: CGFloat {
        switch effectiveGridColumnCount {
        case 0...3: return 8
        case 4: return 6
        default: return 3
        }
    }

    private func clampedColumnCount(_ value: Int) -> Int {
        min(7, max(2, value))
    }

    private func photoURL(_ photo: Photo) -> URL? {
        store.imageURL(photo.tinyUrl ?? photo.thumbnailUrl ?? photo.coverUrl ?? photo.previewUrl ?? photo.imageUrl)
    }
}

private struct PicMePhotoPreview: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let album: Album
    let photos: [Photo]
    let initialPhoto: Photo
    @State private var currentIndex = 0
    @State private var liked = false
    @State private var infoOpen = false
    @State private var saved = false

    var body: some View {
        ZStack {
            PicMeStyle.background.ignoresSafeArea()
            VStack(spacing: 0) {
                previewTopBar
                photoStage
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                bottomPanel
            }
            if saved {
                savedToast
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.22), value: infoOpen)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: saved)
        .statusBarHidden(false)
        .picMeSwipeBack()
        .onAppear {
            currentIndex = photos.firstIndex(where: { $0.id == initialPhoto.id }) ?? 0
        }
    }

    private var previewTopBar: some View {
        HStack {
            Button { dismiss() } label: {
                glassIcon("chevron.left")
            }
            .buttonStyle(.plain)
            Spacer()
            VStack(spacing: 2) {
                Text(formatDate(currentPhoto?.createdAt))
                    .font(.system(size: 14.5, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("\(currentIndex + 1) / \(max(photos.count, 1)) · \(album.name)")
                    .font(.system(size: 11.5))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .lineLimit(1)
            }
            Spacer()
            Button {
            } label: {
                glassIcon("paperplane")
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(.ultraThinMaterial)
        .background(PicMeStyle.background.opacity(0.72))
        .overlay(alignment: .bottom) {
            Rectangle().fill(PicMeStyle.hairline.opacity(0.6)).frame(height: 0.5)
        }
    }

    private var photoStage: some View {
        TabView(selection: $currentIndex) {
            ForEach(Array(photos.enumerated()), id: \.element.id) { index, photo in
                PicMeRemoteImage(url: fullImageURL(photo))
                    .scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(PicMeStyle.background)
                    .padding(.vertical, 10)
                    .tag(index)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(PicMeStyle.background)
        .clipped()
    }

    private var bottomPanel: some View {
        VStack(spacing: 0) {
            if infoOpen, let photo = currentPhoto {
                infoPanel(photo)
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
                    .padding(.bottom, 4)
            }
            filmstrip
            HStack(spacing: 4) {
                previewAction("heart", liked ? "已喜欢" : "喜欢", active: liked, color: PicMeStyle.red) {
                    liked.toggle()
                }
                previewAction("square.and.arrow.down", saved ? "已保存" : "下载", active: saved, color: PicMeStyle.green) {
                    if let photo = currentPhoto {
                        Task { await store.savePhotosToSystemPhotos([photo]) }
                        saved = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { saved = false }
                    }
                }
                previewAction("person.2", "人物", active: infoOpen, color: PicMeStyle.blue) {
                    infoOpen.toggle()
                }
                previewAction("ellipsis", "更多", active: false, color: PicMeStyle.primaryText) {
                    infoOpen.toggle()
                }
            }
            .padding(.horizontal, 14)
            .padding(.top, 6)
            .padding(.bottom, 26)
        }
        .background(.ultraThinMaterial)
        .background(PicMeStyle.background.opacity(0.86))
        .overlay(alignment: .top) {
            Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5)
        }
    }

    private func infoPanel(_ photo: Photo) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            previewInfoLine("clock", formatDate(photo.createdAt))
            previewInfoLine("person", "上传者 \(photo.displayUploader)")
            previewInfoLine("folder", photo.displayFolderNames)
            Text("出现人物")
                .font(.system(size: 12))
                .foregroundColor(PicMeStyle.secondaryText)
                .padding(.top, 2)
                .padding(.bottom, 9)
            HStack(spacing: 16) {
                PicMeAvatar(name: "我", size: 40)
                    .overlay(Circle().stroke(.white, lineWidth: 2))
                if !photo.displayUploader.isEmpty {
                    VStack(spacing: 4) {
                        PicMeAvatar(name: photo.displayUploader, size: 40)
                            .overlay(Circle().stroke(.white, lineWidth: 2))
                        Text(photo.displayUploader)
                            .font(.system(size: 10.5))
                            .foregroundColor(PicMeStyle.primaryText)
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 14, y: 3)
    }

    private var filmstrip: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 4) {
                    ForEach(Array(photos.enumerated()), id: \.element.id) { index, photo in
                        PicMeRemoteImage(url: thumbnailURL(photo))
                            .frame(width: index == currentIndex ? 52 : 34, height: index == currentIndex ? 52 : 44)
                            .clipped()
                            .clipShape(RoundedRectangle(cornerRadius: index == currentIndex ? 6 : 3, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: index == currentIndex ? 6 : 3)
                                    .stroke(index == currentIndex ? PicMeStyle.blue : .clear, lineWidth: 2)
                            )
                            .opacity(index == currentIndex ? 1 : 0.5)
                            .id(photo.id)
                            .onTapGesture { currentIndex = index }
                    }
                }
                .padding(.horizontal, 172)
                .padding(.vertical, 12)
            }
            .onAppear { proxy.scrollTo(currentPhoto?.id, anchor: .center) }
            .onChange(of: currentIndex) { _ in
                withAnimation(.spring(response: 0.25, dampingFraction: 0.82)) {
                    proxy.scrollTo(currentPhoto?.id, anchor: .center)
                }
            }
        }
    }

    private var savedToast: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark")
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(.white)
                .frame(width: 20, height: 20)
                .background(PicMeStyle.green, in: Circle())
            Text("已保存到相册")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.white)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 11)
        .background(PicMeStyle.ink.opacity(0.88), in: Capsule())
        .shadow(color: .black.opacity(0.28), radius: 24, y: 8)
        .offset(y: 250)
    }

    private var currentPhoto: Photo? {
        photos[safe: currentIndex]
    }

    private func fullImageURL(_ photo: Photo) -> URL? {
        store.imageURL(photo.previewUrl ?? photo.imageUrl ?? photo.coverUrl ?? photo.thumbnailUrl ?? photo.tinyUrl)
    }

    private func thumbnailURL(_ photo: Photo) -> URL? {
        store.imageURL(photo.tinyUrl ?? photo.thumbnailUrl ?? photo.coverUrl ?? photo.previewUrl ?? photo.imageUrl)
    }

    private func previewInfoLine(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 11) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .regular))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 18)
            Text(text)
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.primaryText)
                .lineLimit(1)
            Spacer()
        }
        .padding(.bottom, 11)
    }

    private func previewAction(_ icon: String, _ label: String, active: Bool, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 23, weight: .regular))
                Text(label)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundColor(active ? color : PicMeStyle.primaryText)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }
}

struct PicMePhotoPickerPrototypeView: View {
    @State private var selected: [Int] = [1, 4, 7]
    private let sections: [(title: String, live: Set<Int>, items: [String])] = [
        ("今天", [1, 7], ["warm", "city", "food", "people", "nature", "night", "cool", "warm", "people"]),
        ("本周 · 5月20日", [2], ["food", "city", "nature", "people", "warm", "cool", "food", "night", "people", "nature", "city", "warm"]),
        ("更早 · 5月12日", [], ["food", "people", "cool", "nature", "city", "warm", "people", "food", "night"])
    ]

    private var totalCount: Int { sections.reduce(0) { $0 + $1.items.count } }

    var body: some View {
        ZStack(alignment: .bottom) {
            PicMeStyle.background.ignoresSafeArea()
            VStack(spacing: 0) {
                pickerHeader
                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 6) {
                        varGrid
                        Text("共 \(totalCount) 张照片")
                            .font(.system(size: 13))
                            .foregroundColor(PicMeStyle.secondaryText)
                            .frame(maxWidth: .infinity)
                            .padding(.top, 14)
                            .padding(.bottom, selected.isEmpty ? 24 : 108)
                    }
                    .padding(.top, 12)
                }
            }
            pickerBottomBar
                .offset(y: selected.isEmpty ? 110 : 0)
        }
        .animation(.spring(response: 0.28, dampingFraction: 0.82), value: selected)
    }

    private var pickerHeader: some View {
        HStack {
            Button("取消") {}
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 52, alignment: .leading)
            Spacer()
            HStack(spacing: 5) {
                Text("所有照片")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Image(systemName: "chevron.down")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
            }
            Spacer()
            Button(selected.isEmpty ? "" : "清空") { selected.removeAll() }
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(selected.isEmpty ? Color(hex: 0xC7CDD6) : PicMeStyle.blue)
                .frame(width: 52, alignment: .trailing)
        }
        .padding(.horizontal, 16)
        .padding(.top, 50)
        .frame(height: 102, alignment: .bottom)
        .padding(.bottom, 12)
        .background(.ultraThinMaterial)
        .background(PicMeStyle.background.opacity(0.82))
        .overlay(alignment: .bottom) { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
    }

    private var varGrid: some View {
        let indexedSections = sections.indices.map { offset in
            (
                offset: offset,
                start: sections[..<offset].reduce(0) { $0 + $1.items.count },
                section: sections[offset]
            )
        }
        return VStack(alignment: .leading, spacing: 6) {
            ForEach(indexedSections, id: \.offset) { item in
                VStack(alignment: .leading, spacing: 0) {
                    Text(item.section.title)
                        .font(.system(size: 14.5, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 3), count: 3), spacing: 3) {
                        ForEach(Array(item.section.items.enumerated()), id: \.offset) { index, kind in
                            pickerTile(kind: kind, index: item.start + index, isLive: item.section.live.contains(index))
                        }
                    }
                    .padding(.horizontal, 3)
                }
            }
        }
    }

    private func pickerTile(kind: String, index: Int, isLive: Bool) -> some View {
        let order = selected.firstIndex(of: index)
        let isOn = order != nil
        return Button {
            if let order {
                selected.remove(at: order)
            } else {
                selected.append(index)
            }
        } label: {
            ZStack(alignment: .topTrailing) {
                PicMeStripePlaceholder(seed: kind)
                    .scaleEffect(isOn ? 0.90 : 1)
                    .overlay(isOn ? PicMeStyle.blue.opacity(0.18) : Color.clear)
                if isLive && !isOn {
                    HStack(spacing: 3) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 9, weight: .black))
                        Text("LIVE")
                            .font(.system(size: 9, weight: .black))
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .background(.black.opacity(0.32), in: Capsule())
                    .padding(6)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                }
                ZStack {
                    Circle()
                        .fill(isOn ? PicMeStyle.blue : Color.black.opacity(0.18))
                        .overlay(Circle().stroke(isOn ? Color.clear : Color.white.opacity(0.95), lineWidth: 1.6))
                        .shadow(color: .black.opacity(0.25), radius: 4, y: 1)
                    if let order {
                        Text("\(order + 1)")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .frame(width: 22, height: 22)
                .padding(7)
            }
            .aspectRatio(1, contentMode: .fit)
            .clipped()
        }
        .buttonStyle(.plain)
    }

    private var pickerBottomBar: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text("已选 \(selected.count) 张")
                    .font(.system(size: 15.5, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("上传至「重庆三日游」")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Button {} label: {
                HStack(spacing: 7) {
                    Text("下一步")
                    Image(systemName: "chevron.right")
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(.white)
                .frame(height: 48)
                .padding(.horizontal, 26)
                .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .shadow(color: PicMeStyle.blue.opacity(0.4), radius: 20, y: 8)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 24)
        .background(.ultraThinMaterial)
        .background(.white.opacity(0.86))
        .overlay(alignment: .top) { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
    }
}

struct PicMeUploadFlowPrototypeView: View {
    enum Phase {
        case preview
        case uploading
        case done
    }

    @State private var phase: Phase
    @State private var progress: Double
    private let total = 128
    private let live = 12
    private let mb = 48
    private let found = ["飞飞", "张三", "李四", "王五", "小美", "阿May", "陈七"]

    init(initialPhase: Phase = .preview) {
        _phase = State(initialValue: initialPhase)
        _progress = State(initialValue: initialPhase == .uploading ? 0.64 : (initialPhase == .done ? 1 : 0))
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                uploadHeader
                VStack(spacing: 0) {
                    summaryCard
                    switch phase {
                    case .preview:
                        previewBody
                    case .uploading:
                        uploadingBody
                    case .done:
                        doneBody
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 18)
                .padding(.bottom, 24)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .picMeSwipeBack()
    }

    private var title: String {
        switch phase {
        case .preview: return "上传确认"
        case .uploading: return "正在上传"
        case .done: return "上传完成"
        }
    }

    private var uploadHeader: some View {
        HStack {
            Button(phase == .preview ? "上一步" : "关闭") {}
                .font(.system(size: 16))
                .foregroundColor(phase == .uploading ? Color(hex: 0xC7CDD6) : PicMeStyle.secondaryText)
            Spacer()
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Color.clear.frame(width: 48, height: 1)
        }
        .padding(.horizontal, 18)
        .padding(.top, 58)
        .padding(.bottom, 12)
        .background(.ultraThinMaterial)
        .background(PicMeStyle.background.opacity(0.80))
        .overlay(alignment: .bottom) { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
    }

    private var summaryCard: some View {
        VStack(spacing: 0) {
            uploadSummaryRow(icon: "photo", color: PicMeStyle.blue, title: "\(total) 张照片", subtitle: "含 \(live) 张 Live Photo", done: phase == .preview || progress >= 1)
            Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.horizontal, 14)
            uploadSummaryRow(icon: "icloud", color: PicMeStyle.green, title: phase == .preview ? "预计上传 \(mb) MB" : phase == .uploading ? "正在上传 \(Int(Double(total) * progress))/\(total) 张" : "已上传 \(total) 张 · \(mb) MB", subtitle: "Wi-Fi 环境 · 约 20 秒", done: phase == .done)
            if phase != .preview {
                ProgressView(value: progress)
                    .tint(PicMeStyle.blue)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 14)
            }
        }
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 16, y: 4)
    }

    private func uploadSummaryRow(icon: String, color: Color, title: String, subtitle: String, done: Bool) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 23, weight: .semibold))
                .foregroundColor(color)
                .frame(width: 44, height: 44)
                .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text(subtitle)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Image(systemName: "checkmark")
                .font(.system(size: 18, weight: .black))
                .foregroundColor(done ? PicMeStyle.green : Color(hex: 0xC7CDD6))
        }
        .padding(14)
    }

    private var previewBody: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 13) {
                Image(systemName: "sparkles")
                    .font(.system(size: 21, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 40, height: 40)
                    .background(PicMeStyle.gradient, in: Circle())
                    .shadow(color: PicMeStyle.violet.opacity(0.32), radius: 16, y: 6)
                VStack(alignment: .leading, spacing: 3) {
                    Text("上传后自动识别人物与合照")
                        .font(.system(size: 15.5, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text("照片上传完成后，AI 会在云端后台识别人脸，并按「人物」「合照」自动归类，无需等待即可离开。")
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.blue.opacity(0.8))
                        .lineSpacing(2)
                }
            }
            .padding(18)
            .background(PicMeStyle.gradient.opacity(0.12), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(PicMeStyle.blue.opacity(0.18), lineWidth: 0.5))
            .padding(.top, 22)
            HStack(spacing: 7) {
                Image(systemName: "lock")
                    .font(.system(size: 14, weight: .semibold))
                Text("人脸数据仅用于本相册归类 · 不对外公开")
                    .font(.system(size: 13))
            }
            .foregroundColor(PicMeStyle.secondaryText)
            .padding(.top, 16)
            PicMePrimaryButton(title: "开始上传", systemImage: "icloud.and.arrow.up") {
                phase = .uploading
                progress = 0.64
            }
            .padding(.top, 18)
        }
    }

    private var uploadingBody: some View {
        VStack(spacing: 0) {
            VStack(spacing: 0) {
                ZStack {
                    Circle().fill(PicMeStyle.gradient).frame(width: 90, height: 90)
                    Image(systemName: "icloud.and.arrow.up")
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundColor(.white)
                    Circle()
                        .stroke(PicMeStyle.blue.opacity(0.36), lineWidth: 2)
                        .frame(width: 106, height: 106)
                }
                .shadow(color: PicMeStyle.violet.opacity(0.4), radius: 30, y: 10)
                Text("\(Int(progress * 100))%")
                    .font(.system(size: 30, weight: .black))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.top, 16)
                Text("正在上传照片，请保持网络连接…")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.blue.opacity(0.72))
                    .padding(.top, 2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 28)
            .background(PicMeStyle.gradient.opacity(0.12), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .padding(.top, 22)
        }
    }

    private var doneBody: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "checkmark")
                    .font(.system(size: 14, weight: .black))
                    .foregroundColor(.white)
                    .frame(width: 26, height: 26)
                    .background(PicMeStyle.green, in: Circle())
                Text("\(total) 张照片已全部上传成功")
                    .font(.system(size: 14.5, weight: .bold))
                    .foregroundColor(Color(hex: 0x15803D))
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(PicMeStyle.green.opacity(0.10), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(PicMeStyle.green.opacity(0.28), lineWidth: 0.5))
            .padding(.top, 16)

            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 12) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 20, weight: .black))
                        .foregroundColor(.white)
                        .frame(width: 46, height: 46)
                        .background(PicMeStyle.gradient, in: Circle())
                        .shadow(color: PicMeStyle.violet.opacity(0.30), radius: 16, y: 6)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("已识别 \(found.count) 位人物")
                            .font(.system(size: 15.5, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text("合照已按多人同框自动归类完成")
                            .font(.system(size: 13))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    Spacer()
                }
                LazyVGrid(columns: Array(repeating: GridItem(.fixed(52), spacing: 14), count: 5), spacing: 12) {
                    ForEach(found, id: \.self) { name in
                        VStack(spacing: 5) {
                            PicMeAvatar(name: name, size: 48)
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                                .shadow(color: PicMeStyle.ink.opacity(0.12), radius: 8, y: 2)
                            Text(name)
                                .font(.system(size: 11.5, weight: .medium))
                                .foregroundColor(PicMeStyle.primaryText)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .padding(18)
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 16, y: 4)
            .padding(.top, 16)
            PicMePrimaryButton(title: "进入相册查看", systemImage: "photo") {}
                .padding(.top, 20)
            Button("返回首页") {}
                .font(.system(size: 15, weight: .bold))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .padding(.top, 8)
        }
    }
}

struct PicMeSharePrototypeView: View {
    @State private var toastVisible = false

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 0) {
                    shareHeader
                    VStack(spacing: 0) {
                        qrCard
                        linkRow
                        PicMePrimaryButton(title: "分享到微信", systemImage: "square.and.arrow.up") {
                            withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) { toastVisible = true }
                        }
                        .padding(.top, 14)
                        Text("加入与权限")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.top, 20)
                            .padding(.horizontal, 2)
                            .padding(.bottom, 10)
                        VStack(spacing: 0) {
                            shareEntryRow(icon: "lock", label: "访问验证", value: "输入密码")
                            shareEntryRow(icon: "checkmark", label: "加入审核", value: "管理员审批")
                            shareEntryRow(icon: "person.2", label: "成员权限", value: "3 项已开启", isLast: true)
                        }
                        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                        Button("预览加入流程") {}
                            .font(.system(size: 15, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                            .frame(maxWidth: .infinity)
                            .frame(height: 48)
                            .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .padding(.top, 16)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 40)
                }
            }
            .background(PicMeStyle.background.ignoresSafeArea())
            if toastVisible {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 12, weight: .black))
                        .foregroundColor(.white)
                        .frame(width: 20, height: 20)
                        .background(PicMeStyle.green, in: Circle())
                    Text("已生成微信分享链接")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 11)
                .background(.black.opacity(0.88), in: Capsule())
                .shadow(color: .black.opacity(0.28), radius: 24, y: 8)
                .padding(.bottom, 54)
            }
        }
    }

    private var shareHeader: some View {
        HStack {
            PicMeDismissCircleButton()
            Spacer()
            Text("分享 重庆三日游")
                .font(.system(size: 17, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Color.clear.frame(width: 38, height: 38)
        }
        .padding(.horizontal, 16)
        .padding(.top, 50)
        .padding(.bottom, 12)
        .background(PicMeStyle.background.opacity(0.82))
    }

    private var qrCard: some View {
        VStack(spacing: 0) {
            ZStack {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(.white)
                    .frame(width: 172, height: 172)
                    .shadow(color: PicMeStyle.ink.opacity(0.08), radius: 12, y: 2)
                QRPlaceholder()
                    .frame(width: 144, height: 144)
                PicMeLogoMark(size: 34)
                    .padding(3)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            Text("扫码加入「重庆三日游」")
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 16)
            Text("扫二维码或打开链接即可申请加入")
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.secondaryText)
                .padding(.top, 3)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 20)
        .padding(.bottom, 18)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.07), radius: 22, y: 6)
    }

    private var linkRow: some View {
        Button {
            withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) { toastVisible = true }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "link")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(PicMeStyle.blue)
                Text("picme.com/s/abc123")
                    .font(.system(size: 14.5))
                    .foregroundColor(PicMeStyle.primaryText)
                    .lineLimit(1)
                Spacer()
                HStack(spacing: 5) {
                    Image(systemName: "doc.on.doc")
                        .font(.system(size: 14, weight: .semibold))
                    Text("复制")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(PicMeStyle.blue)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(PicMeStyle.blue.opacity(0.12), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .frame(height: 50)
            .padding(.horizontal, 14)
            .background(PicMeStyle.ink.opacity(0.04), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(PicMeStyle.hairline, lineWidth: 0.5))
        }
        .buttonStyle(.plain)
        .padding(.top, 12)
    }

    private func shareEntryRow(icon: String, label: String, value: String, isLast: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.blue)
                .frame(width: 34, height: 34)
                .background(PicMeStyle.blue.opacity(0.11), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            Text(label)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Text(value)
                .font(.system(size: 13.5))
                .foregroundColor(PicMeStyle.secondaryText)
            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .bold))
                .foregroundColor(Color(hex: 0xC7CDD6))
        }
        .padding(14)
        .overlay(alignment: .bottom) {
            if !isLast {
                Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 60)
            }
        }
    }
}

struct PicMeJoinPrototypeView: View {
    let submitted: Bool
    @State private var passwordLength = 3

    var body: some View {
        if submitted {
            submittedBody
        } else {
            joinBody
        }
    }

    private var joinBody: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                joinHeader
                albumChip
                    .padding(.horizontal, 20)
                    .padding(.top, 18)
                VStack(alignment: .leading, spacing: 0) {
                    Text("访问密码")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text("管理员已为该相册设置密码")
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.secondaryText)
                        .padding(.top, 2)
                    HStack(spacing: 10) {
                        ForEach(0..<6, id: \.self) { index in
                            Button {
                                passwordLength = min(6, index + 1)
                            } label: {
                                Text(index < passwordLength ? "•" : "")
                                    .font(.system(size: 24, weight: .semibold))
                                    .foregroundColor(PicMeStyle.primaryText)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 54)
                                    .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(index < passwordLength ? PicMeStyle.blue : PicMeStyle.hairline, lineWidth: index < passwordLength ? 1.5 : 0.5))
                                    .shadow(color: index < passwordLength ? PicMeStyle.blue.opacity(0.18) : .clear, radius: 12, y: 4)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.top, 14)
                }
                .padding(.horizontal, 20)
                .padding(.top, 26)
                PicMePrimaryButton(title: "提交申请", disabled: passwordLength < 6) {
                    passwordLength = 6
                }
                .padding(.horizontal, 20)
                .padding(.top, 30)
                HStack(spacing: 7) {
                    Image(systemName: "lock")
                        .font(.system(size: 13, weight: .semibold))
                    Text("提交后需管理员审批，通过后消息通知你")
                        .font(.system(size: 12.5))
                }
                .foregroundColor(PicMeStyle.secondaryText)
                .padding(.top, 16)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .picMeSwipeBack()
    }

    private var submittedBody: some View {
        VStack(spacing: 0) {
            joinHeader
            Spacer(minLength: 0)
            ZStack {
                Circle().fill(PicMeStyle.orange.opacity(0.14)).frame(width: 104, height: 104)
                Image(systemName: "hourglass")
                    .font(.system(size: 50, weight: .regular))
                    .foregroundColor(PicMeStyle.orange)
            }
            Text("申请已提交")
                .font(.system(size: 22, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 22)
            Text("管理员将在 24 小时内处理。\n通过后将通过消息推送通知你成功加入。")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
                .lineSpacing(3)
                .padding(.top, 8)
            PicMePrimaryButton(title: "知道了") {}
                .padding(.horizontal, 30)
                .padding(.top, 30)
            Spacer(minLength: 72)
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private var joinHeader: some View {
        HStack {
            PicMeDismissCircleButton()
            Spacer()
            Text("加入相册")
                .font(.system(size: 17, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Color.clear.frame(width: 38, height: 38)
        }
        .padding(.horizontal, 16)
        .padding(.top, 50)
        .padding(.bottom, 12)
        .background(PicMeStyle.background.opacity(0.82))
    }

    private var albumChip: some View {
        HStack(spacing: 12) {
            PicMeStripePlaceholder(seed: "city")
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text("重庆三日游")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("326 张照片 · 8 位成员")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Text("需审批")
                .font(.system(size: 11.5, weight: .semibold))
                .foregroundColor(PicMeStyle.orange)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(PicMeStyle.orange.opacity(0.14), in: Capsule())
        }
        .padding(12)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 12, y: 3)
    }
}

struct PicMeNotificationsPrototypeView: View {
    struct Request: Identifiable {
        let id: Int
        let name: String
        let kind: String
        let album: String
        let reason: String
        let time: String
        let desc: String
    }

    let showDetail: Bool
    private let requests = [
        Request(id: 1, name: "张三", kind: "join", album: "重庆三日游", reason: "我是本次团建成员", time: "2 分钟前", desc: "申请加入「重庆三日游」"),
        Request(id: 2, name: "李四", kind: "perm", album: "重庆三日游", reason: "需要下载原图整理", time: "5 小时前", desc: "申请「重庆三日游」更多权限"),
        Request(id: 3, name: "王五", kind: "join", album: "重庆三日游", reason: "摄影师，帮忙整理照片", time: "5 小时前", desc: "申请加入「重庆三日游」"),
        Request(id: 4, name: "小美", kind: "join", album: "重庆三日游", reason: "活动参与者", time: "1 天前", desc: "申请加入「重庆三日游」")
    ]

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    messageHeader
                    HStack(spacing: 8) {
                        Text("待处理申请")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text("\(requests.count)")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                            .frame(minWidth: 20, minHeight: 20)
                            .padding(.horizontal, 2)
                            .background(PicMeStyle.red, in: Capsule())
                    }
                    .padding(.horizontal, 22)
                    .padding(.top, 16)
                    .padding(.bottom, 10)
                    VStack(spacing: 10) {
                        ForEach(Array(requests.enumerated()), id: \.element.id) { index, request in
                            notificationSwipeRow(request, hint: index == 0)
                        }
                    }
                    .padding(.horizontal, 20)
                    HStack {
                        Text("历史消息")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Spacer()
                        Image(systemName: "chevron.down")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    .padding(.horizontal, 22)
                    .padding(.top, 22)
                    .padding(.bottom, 40)
                }
            }
            .background(PicMeStyle.background.ignoresSafeArea())
            if showDetail {
                Color.black.opacity(0.40).ignoresSafeArea()
                requestDetailSheet(requests[0])
            }
        }
    }

    private var messageHeader: some View {
        HStack(spacing: 8) {
            PicMeDismissCircleButton()
                .frame(width: 32, height: 32)
            Text("通知")
                .font(.system(size: 28, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Button("全部已读") {}
                .font(.system(size: 13.5, weight: .medium))
                .foregroundColor(PicMeStyle.secondaryText)
        }
        .padding(.horizontal, 20)
        .padding(.top, 54)
    }

    private func notificationSwipeRow(_ request: Request, hint: Bool) -> some View {
        ZStack(alignment: .trailing) {
            HStack(spacing: 0) {
                Spacer()
                VStack(spacing: 5) {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .bold))
                    Text("拒绝")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 75, height: 70)
                .background(Color(hex: 0xECEEF2))
                VStack(spacing: 5) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 18, weight: .bold))
                    Text("通过")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(.white)
                .frame(width: 75, height: 70)
                .background(PicMeStyle.gradient)
            }
            notificationCard(request, hint: hint)
                .offset(x: hint ? -108 : 0)
        }
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func notificationCard(_ request: Request, hint: Bool) -> some View {
        HStack(spacing: 12) {
            ZStack(alignment: .bottomTrailing) {
                PicMeAvatar(name: request.name, size: 46)
                Image(systemName: request.kind == "perm" ? "lock" : "person")
                    .font(.system(size: 10, weight: .black))
                    .foregroundColor(.white)
                    .frame(width: 20, height: 20)
                    .background(request.kind == "perm" ? PicMeStyle.violet : PicMeStyle.blue, in: Circle())
                    .overlay(Circle().stroke(.white, lineWidth: 2))
                    .offset(x: 2, y: 2)
            }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(request.name)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text(request.time)
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
                Text(request.desc)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .lineLimit(1)
            }
            Spacer()
            if hint {
                Text("滑动处理 →")
                    .font(.system(size: 10.5, weight: .semibold))
                    .foregroundColor(PicMeStyle.blue)
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 70)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 12, y: 3)
    }

    private func requestDetailSheet(_ request: Request) -> some View {
        VStack(spacing: 0) {
            Capsule().fill(PicMeStyle.ink.opacity(0.14)).frame(width: 38, height: 5).padding(.top, 10).padding(.bottom, 18)
            HStack(spacing: 14) {
                PicMeAvatar(name: request.name, size: 56)
                VStack(alignment: .leading, spacing: 2) {
                    Text(request.name)
                        .font(.system(size: 20, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text(request.time)
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
                Spacer()
                Text(request.kind == "perm" ? "权限申请" : "加入申请")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(request.kind == "perm" ? PicMeStyle.violet : PicMeStyle.blue)
                    .padding(.horizontal, 11)
                    .padding(.vertical, 5)
                    .background((request.kind == "perm" ? PicMeStyle.violet : PicMeStyle.blue).opacity(0.12), in: Capsule())
            }
            .padding(.horizontal, 20)
            VStack(spacing: 0) {
                detailInfoRow("folder", "相册", request.album)
                detailInfoRow("text.bubble", "申请理由", request.reason)
                detailInfoRow(request.kind == "perm" ? "lock" : "person", request.kind == "perm" ? "申请权限" : "申请角色", request.kind == "perm" ? "下载原图 + 删除照片" : "普通成员", last: true)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 3)
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
            .padding(.horizontal, 20)
            .padding(.top, 16)
            HStack(spacing: 12) {
                Button("拒绝") {}
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .background(PicMeStyle.ink.opacity(0.05), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                Button("通过") {}
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .shadow(color: PicMeStyle.blue.opacity(0.35), radius: 20, y: 8)
            }
            .padding(.horizontal, 20)
            .padding(.top, 20)
            .padding(.bottom, 30)
        }
        .frame(maxWidth: .infinity)
        .background(PicMeStyle.background, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private func detailInfoRow(_ icon: String, _ label: String, _ value: String, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 18)
            Text(label)
                .font(.system(size: 13.5))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 64, alignment: .leading)
            Text(value)
                .font(.system(size: 14.5))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
        }
        .padding(.vertical, 11)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
        }
    }
}

struct PicMeMyPhotosPrototypeView: View {
    let selectionMode: Bool
    @State private var selected: [Int] = [0, 3, 6]
    @State private var mode: Mode = .photos
    private let kinds = ["people", "warm", "nature", "food", "cool", "people", "city", "warm", "people", "nature", "people", "food"]
    private let liked: Set<Int> = [0, 4, 7, 10]

    private enum Mode: String, CaseIterable, Identifiable, Hashable {
        case photos, albums
        var id: String { rawValue }
        var title: String { self == .photos ? "照片" : "相册" }
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    myHeader
                    if !selectionMode {
                        segmented
                        if mode == .photos {
                            filterChips
                        }
                    }
                    if selectionMode || mode == .photos {
                        photoGrid
                            .padding(.horizontal, 16)
                            .padding(.top, 16)
                    } else {
                        albumRows
                            .padding(.horizontal, 20)
                            .padding(.top, 16)
                    }
                    Color.clear
                        .frame(height: selectionMode ? 120 : 108)
                }
            }
            .background(PicMeStyle.background.ignoresSafeArea())
            if selectionMode {
                downloadBar
            }
        }
    }

    private var albumRows: some View {
        VStack(spacing: 10) {
            myAlbumRow(title: "重庆三日游", count: 48, seed: "city")
            myAlbumRow(title: "生日聚会", count: 23, seed: "warm")
            myAlbumRow(title: "三亚旅行", count: 31, seed: "nature")
            myAlbumRow(title: "重庆火锅局", count: 19, seed: "food")
        }
    }

    private func myAlbumRow(title: String, count: Int, seed: String) -> some View {
        HStack(spacing: 12) {
            PicMeStripePlaceholder(seed: seed)
                .overlay {
                    Text("封面")
                        .font(.system(size: 10.5, weight: .semibold, design: .monospaced))
                        .foregroundColor(PicMeStyle.ink.opacity(0.45))
                }
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("你出现在 \(count) 张")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(Color(hex: 0xC7CDD6))
        }
        .padding(10)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 12, y: 3)
    }

    private var myHeader: some View {
        HStack(alignment: selectionMode ? .center : .top) {
            if selectionMode {
                Button("取消") {}
                    .font(.system(size: 16))
                    .foregroundColor(PicMeStyle.secondaryText)
                Spacer()
                Text(selected.isEmpty ? "选择要下载的照片" : "已选 \(selected.count) 张")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Spacer()
                Button("全选") {}
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(PicMeStyle.blue)
            } else {
                VStack(alignment: .leading, spacing: 2) {
                    Text("我的照片")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text("你出现在 83 张照片 · 横跨 8 个相册")
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
                Spacer()
                glassIcon("arrow.down")
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .frame(minHeight: selectionMode ? 46 : 54, alignment: .top)
    }

    private var segmented: some View {
        PicMeSegmentedControl(items: Mode.allCases, selection: $mode) { $0.title }
        .padding(.horizontal, 20)
        .padding(.top, 18)
    }

    private var filterChips: some View {
        HStack(spacing: 8) {
            chip("全部", selected: true) {}
            Button {} label: {
                HStack(spacing: 5) {
                    Image(systemName: "heart.fill")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(PicMeStyle.red)
                    Text("喜欢")
                        .font(.system(size: 13.5, weight: .semibold))
                        .foregroundColor(PicMeStyle.primaryText)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(PicMeStyle.ink.opacity(0.05), in: Capsule())
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
    }

    private var photoGrid: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
            ForEach(Array(kinds.enumerated()), id: \.offset) { index, kind in
                myPhotoTile(kind: kind, index: index)
            }
        }
    }

    private func myPhotoTile(kind: String, index: Int) -> some View {
        let order = selected.firstIndex(of: index)
        let on = order != nil
        return ZStack(alignment: .topTrailing) {
            PicMeStripePlaceholder(seed: kind)
                .overlay(alignment: .center) {
                    if kind == "people" && index == 0 {
                        Text("人物 飞飞")
                            .font(.system(size: 10.5, weight: .bold))
                            .foregroundColor(PicMeStyle.ink.opacity(0.45))
                    }
                }
                .scaleEffect(selectionMode && on ? 0.92 : 1)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            if liked.contains(index) && !selectionMode {
                Image(systemName: "heart.fill")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 22, height: 22)
                    .background(.black.opacity(0.32), in: Circle())
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                    .padding(6)
            }
            if index == 4 && !selectionMode {
                HStack(spacing: 3) {
                    Circle()
                        .stroke(PicMeStyle.primaryText, lineWidth: 1.4)
                        .frame(width: 8, height: 8)
                    Text("LIVE")
                        .font(.system(size: 9, weight: .bold))
                }
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(.white.opacity(0.82), in: Capsule())
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(6)
            }
            if selectionMode {
                if on {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(PicMeStyle.blue.opacity(0.16))
                }
                ZStack {
                    Circle()
                        .fill(on ? PicMeStyle.blue : Color.black.opacity(0.18))
                        .overlay(Circle().stroke(on ? Color.clear : Color.white.opacity(0.95), lineWidth: 1.6))
                        .shadow(color: .black.opacity(0.25), radius: 4, y: 1)
                    if let order {
                        Text("\(order + 1)")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .frame(width: 22, height: 22)
                .padding(7)
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }

    private var downloadBar: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text("已选 \(selected.count) 张")
                    .font(.system(size: 15.5, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("点击下方按钮预览并下载")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Button {} label: {
                HStack(spacing: 7) {
                    Image(systemName: "arrow.down")
                    Text("下载")
                }
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(.white)
                .frame(height: 48)
                .padding(.horizontal, 24)
                .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .shadow(color: PicMeStyle.blue.opacity(0.4), radius: 20, y: 8)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 24)
        .background(.ultraThinMaterial)
        .background(.white.opacity(0.88))
        .overlay(alignment: .top) { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
    }
}

struct PicMeDownloadPrototypeView: View {
    enum Phase { case preview, downloading, done }
    let phase: Phase
    @State private var live = true
    private let count = 12
    private let kinds = ["people", "warm", "nature", "food", "cool", "people", "city", "warm", "people"]

    var body: some View {
        if phase == .done {
            downloadDone
        } else {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {
                    simpleHeader(title: phase == .preview ? "下载预览" : "下载预览")
                    HStack {
                        Text("已选 \(count) 张")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Spacer()
                        Text("预计 43.2 MB")
                            .font(.system(size: 13))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 5), count: 3), spacing: 5) {
                        ForEach(Array(kinds.enumerated()), id: \.offset) { index, kind in
                            ZStack {
                                PicMeStripePlaceholder(seed: kind)
                                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                if index == kinds.count - 1 {
                                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                                        .fill(PicMeStyle.ink.opacity(0.55))
                                    Text("+3")
                                        .font(.system(size: 22, weight: .bold))
                                        .foregroundColor(.white)
                                }
                            }
                            .frame(height: 92)
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 10)
                    Text("下载画质")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                        .padding(.horizontal, 22)
                        .padding(.top, 16)
                        .padding(.bottom, 8)
                    VStack(spacing: 0) {
                        qualityRow(title: "原图", desc: "保留最高画质 · 约 43.2 MB", selected: true)
                        qualityRow(title: "标准", desc: "节省空间 · 约 13.2 MB", selected: false, last: true)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 2)
                    .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                    .padding(.horizontal, 20)
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text("保留 Live Photo")
                                .font(.system(size: 15))
                                .foregroundColor(PicMeStyle.primaryText)
                            Text("下载动态照片的视频与音频")
                                .font(.system(size: 13))
                                .foregroundColor(PicMeStyle.secondaryText)
                        }
                        Spacer()
                        Toggle("", isOn: $live).labelsHidden().tint(PicMeStyle.blue)
                    }
                    .padding(13)
                    .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                    .padding(.horizontal, 20)
                    .padding(.top, 10)
                    if phase == .downloading {
                        progressBlock
                    } else {
                        PicMePrimaryButton(title: "下载 12 张 · 43.2 MB", systemImage: "arrow.down") {}
                            .padding(.horizontal, 20)
                            .padding(.top, 18)
                    }
                }
                .padding(.bottom, 24)
            }
            .background(PicMeStyle.background.ignoresSafeArea())
        }
    }

    private func qualityRow(title: String, desc: String, selected: Bool, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: selected ? .semibold : .regular))
                    .foregroundColor(PicMeStyle.primaryText)
                Text(desc)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                .font(.system(size: 20, weight: .semibold))
                .foregroundColor(selected ? PicMeStyle.blue : PicMeStyle.secondaryText.opacity(0.45))
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
        }
    }

    private var progressBlock: some View {
        VStack(spacing: 10) {
            ProgressView(value: 0.64)
                .tint(PicMeStyle.blue)
            Text("正在下载 8/12 张…")
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.secondaryText)
        }
        .padding(.horizontal, 20)
        .padding(.top, 26)
    }

    private var downloadDone: some View {
        VStack(spacing: 0) {
            simpleHeader(title: "下载完成")
            Spacer(minLength: 0)
            Image(systemName: "checkmark")
                .font(.system(size: 50, weight: .bold))
                .foregroundColor(PicMeStyle.green)
                .frame(width: 104, height: 104)
                .background(PicMeStyle.green.opacity(0.14), in: Circle())
            Text("已保存 \(count) 张照片")
                .font(.system(size: 22, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 22)
            Text("照片已保存到系统相册 · 含 Live Photo 动态。")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
                .padding(.top, 8)
            PicMePrimaryButton(title: "完成") {}
                .padding(.horizontal, 30)
                .padding(.top, 30)
            Spacer(minLength: 72)
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }
}

struct PicMeTransferPrototypeView: View {
    private let tasks: [(type: String, album: String, total: Int, done: Int, ai: Int?, status: String)] = [
        ("upload", "重庆三日游", 320, 182, 96, "running"),
        ("download", "三亚旅行", 246, 138, nil, "paused"),
        ("download", "重庆火锅局", 512, 301, nil, "failed"),
        ("upload", "生日聚会", 89, 89, 89, "done")
    ]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                Text("传输")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                HStack(spacing: 8) {
                    chip("全部", selected: true) {}
                    chip("上传", selected: false) {}
                    chip("下载", selected: false) {}
                }
                .padding(.horizontal, 20)
                .padding(.top, 14)
                transferSection("进行中", count: 2) {
                    transferTask(tasks[0])
                    transferTask(tasks[1])
                }
                transferSection("失败 · 需重试", count: 1, danger: true) {
                    transferTask(tasks[2])
                }
                transferSection("已完成", count: 1, collapsible: true) {
                    transferTask(tasks[3])
                }
                Spacer(minLength: 108)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private func transferSection<Content: View>(_ title: String, count: Int, danger: Bool = false, collapsible: Bool = false, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("\(count)")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(danger ? .white : PicMeStyle.secondaryText)
                    .frame(minWidth: 20, minHeight: 20)
                    .padding(.horizontal, 2)
                    .background(danger ? PicMeStyle.red : PicMeStyle.ink.opacity(0.08), in: Capsule())
                if collapsible {
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
            }
            content()
        }
        .padding(.horizontal, 20)
        .padding(.top, 18)
    }

    private func transferTask(_ task: (type: String, album: String, total: Int, done: Int, ai: Int?, status: String)) -> some View {
        let upload = task.type == "upload"
        let failed = task.status == "failed"
        let done = task.status == "done"
        let paused = task.status == "paused"
        let color = upload ? PicMeStyle.blue : PicMeStyle.green
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: upload ? "arrow.up" : "arrow.down")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundColor(color)
                    .frame(width: 42, height: 42)
                    .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(upload ? "上传到" : "下载自")「\(task.album)」")
                        .font(.system(size: 14.5, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text(done ? "已完成 \(task.total) 张" : failed ? "网络中断" : paused ? "已暂停" : (upload ? "上传中 · AI 识别同步进行" : "下载中"))
                        .font(.system(size: 13))
                        .foregroundColor(failed ? PicMeStyle.red : PicMeStyle.secondaryText)
                }
                Spacer()
                if done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 15, weight: .black))
                        .foregroundColor(PicMeStyle.green)
                        .frame(width: 28, height: 28)
                        .background(PicMeStyle.green.opacity(0.14), in: Circle())
                } else {
                    HStack(spacing: 7) {
                        Image(systemName: failed ? "arrow.clockwise" : paused ? "play.fill" : "pause")
                        Image(systemName: "xmark")
                    }
                    .font(.system(size: 15, weight: .bold))
                    .foregroundColor(PicMeStyle.secondaryText)
                }
            }
            if !done {
                transferProgress(label: upload ? "上传照片" : "下载", done: task.done, total: task.total, color: failed ? PicMeStyle.red : color)
                if upload {
                    transferProgress(label: "AI 识别人脸", done: task.ai ?? 0, total: task.total, color: failed ? PicMeStyle.red : PicMeStyle.blue)
                }
            }
        }
        .padding(14)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
    }

    private func transferProgress(label: String, done: Int, total: Int, color: Color) -> some View {
        VStack(spacing: 5) {
            HStack {
                Text(label)
                    .font(.system(size: 12))
                    .foregroundColor(PicMeStyle.secondaryText)
                Spacer()
                Text("\(done)/\(total)")
                    .font(.system(size: 11.5, weight: .semibold, design: .monospaced))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            ProgressView(value: Double(done), total: Double(total))
                .tint(color)
        }
        .padding(.top, 10)
    }
}

struct PicMeProfileDashboardView: View {
    @EnvironmentObject private var store: SharePhotosStore
    var onOpenMyPhotos: () -> Void = {}
    var onOpenMyAlbums: () -> Void = {}
    @State private var editOpen = false
    @State private var categoryTitle: String?

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                Text("我的")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                profileCard
                statsCard
                VStack(spacing: 0) {
                    profileCategory("lock", "账户与安全")
                    profileCategory("person", "隐私与人脸识别")
                    profileCategory("bell", "通用")
                    profileCategory("text.bubble", "帮助与关于", last: true)
                }
                .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                .padding(.horizontal, 20)
                .padding(.top, 18)
                Button {
                    Task { await store.logout() }
                } label: {
                    Text("退出登录")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(PicMeStyle.red)
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                }
                .buttonStyle(.plain)
                .disabled(store.isBusy)
                .padding(.horizontal, 20)
                .padding(.top, 18)
                .padding(.bottom, 108)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .fullScreenCover(isPresented: $editOpen) {
            PicMeProfileEditView()
        }
        .fullScreenCover(isPresented: Binding(
            get: { categoryTitle != nil },
            set: { isPresented in
                if !isPresented { categoryTitle = nil }
            }
        )) {
            PicMeProfileCategoryView(title: categoryTitle ?? "设置")
        }
    }

    private var profileCard: some View {
        Button { editOpen = true } label: {
            HStack(spacing: 14) {
                profileCardAvatar
                VStack(alignment: .leading, spacing: 2) {
                    Text(displayName)
                        .font(.system(size: 20, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text(accountText)
                        .font(.system(size: 13))
                        .foregroundColor(PicMeStyle.secondaryText)
                    Text(picMeIdText)
                        .font(.system(size: 11.5, weight: .semibold))
                        .foregroundColor(PicMeStyle.blue)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 3)
                        .background(PicMeStyle.gradient.opacity(0.12), in: Capsule())
                        .padding(.top, 5)
                }
                Spacer()
                Image(systemName: "pencil")
                    .font(.system(size: 19, weight: .semibold))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
        }
        .buttonStyle(.plain)
        .padding(16)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.06), radius: 20, y: 6)
        .padding(.horizontal, 20)
        .padding(.top, 14)
    }

    private var statsCard: some View {
        HStack(spacing: 0) {
            Button(action: onOpenMyPhotos) {
                profileStat("\(myPhotoCount)", "我的照片")
            }
            .buttonStyle(.plain)
            Rectangle().fill(PicMeStyle.hairline).frame(width: 1).padding(.vertical, 8)
            Button(action: onOpenMyAlbums) {
                profileStat("\(myAlbumCount)", "出现相册")
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 14)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
        .padding(.horizontal, 20)
        .padding(.top, 14)
    }

    private var displayName: String {
        let nickname = store.currentUser?.nickname.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !nickname.isEmpty { return nickname }
        let username = store.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !username.isEmpty { return username }
        return store.uploader.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "PicMe 用户" : store.uploader
    }

    private var accountText: String {
        let username = store.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return username.isEmpty ? "已登录" : "@\(username)"
    }

    private var picMeIdText: String {
        let userId = store.currentUser?.id.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return userId.isEmpty ? "PicMe ID" : "PicMe ID · \(userId)"
    }

    private var myPhotoCount: Int {
        store.albums.reduce(0) { total, album in
            total + profileMyPhotos(in: album).count
        }
    }

    private var myAlbumCount: Int {
        store.albums.filter { !profileMyPhotos(in: $0).isEmpty }.count
    }

    private func profileMyPhotos(in album: Album) -> [Photo] {
        let explicit = store.myPhotos(in: album)
        if !explicit.isEmpty { return explicit }
        if let folderId = album.myMatchedFolderId {
            let folderPhotos = album.photos
                .filter { $0.allFolderIds.contains(folderId) || $0.folderId == folderId }
                .sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) }
            if !folderPhotos.isEmpty { return folderPhotos }
        }
        return []
    }

    @ViewBuilder
    private var profileCardAvatar: some View {
        ZStack {
            PicMeAvatar(name: displayName, size: 60)
            if let avatarUrl = store.currentUser?.avatarUrl,
               let url = store.imageURL(avatarUrl) {
                PicMeRemoteImage(url: url)
                    .id(store.avatarImageVersion)
                    .frame(width: 60, height: 60)
                    .clipShape(Circle())
            }
        }
        .frame(width: 60, height: 60)
        .padding(2.5)
        .background(PicMeStyle.gradient, in: Circle())
    }

    private func profileStat(_ value: String, _ label: String) -> some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.system(size: 22, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Text(label)
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.secondaryText)
        }
        .frame(maxWidth: .infinity)
    }

    private func profileCategory(_ icon: String, _ label: String, last: Bool = false) -> some View {
        Button { categoryTitle = label } label: {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(PicMeStyle.blue)
                    .frame(width: 32, height: 32)
                    .background(PicMeStyle.blue.opacity(0.11), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                Text(label)
                    .font(.system(size: 15))
                    .foregroundColor(PicMeStyle.primaryText)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(Color(hex: 0xC7CDD6))
            }
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity)
            .frame(height: 62)
            .contentShape(Rectangle())
            .overlay(alignment: .bottom) {
                if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 58) }
            }
        }
        .buttonStyle(.plain)
    }
}

struct PicMeCreateAlbumPrototypeView: View {
    @Environment(\.dismiss) private var dismiss
    let created: Bool
    @State private var name = "重庆三日游"

    var body: some View {
        ZStack {
            PicMeStyle.background.ignoresSafeArea()
            PicMeStyle.ink.opacity(0.45).ignoresSafeArea()
            if created {
                createdCard
            } else {
                createCard
            }
        }
    }

    private var createCard: some View {
        VStack(spacing: 0) {
            Text("新建相册")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            TextField("相册名称", text: $name)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.primaryText)
                .multilineTextAlignment(.center)
                .frame(height: 54)
                .padding(.horizontal, 16)
                .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(PicMeStyle.ink.opacity(0.06), lineWidth: 1))
                .padding(.top, 20)
            HStack(spacing: 12) {
                Button("取消") { dismiss() }
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .frame(maxWidth: .infinity)
                    .frame(height: 50)
                    .background(PicMeStyle.ink.opacity(0.05), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                PicMePrimaryButton(title: "创建", disabled: name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) {}
                    .frame(maxWidth: .infinity)
            }
            .padding(.top, 22)
        }
        .padding(.horizontal, 22)
        .padding(.top, 26)
        .padding(.bottom, 22)
        .background(PicMeStyle.background, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.28), radius: 60, y: 24)
        .padding(.horizontal, 28)
    }

    private var createdCard: some View {
        VStack(spacing: 0) {
            Image(systemName: "checkmark")
                .font(.system(size: 38, weight: .bold))
                .foregroundColor(PicMeStyle.green)
                .frame(width: 72, height: 72)
                .background(PicMeStyle.green.opacity(0.14), in: Circle())
            Text("相册创建成功")
                .font(.system(size: 21, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 18)
            Text("把「\(name)」分享给好友，一起上传照片吧")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
                .padding(.top, 8)
            PicMePrimaryButton(title: "去分享相册", systemImage: "square.and.arrow.up") {}
                .padding(.top, 22)
            Button("先进入相册") { dismiss() }
                .font(.system(size: 14.5, weight: .semibold))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(height: 44)
                .padding(.top, 2)
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 24)
        .padding(.top, 30)
        .padding(.bottom, 24)
        .background(PicMeStyle.background, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: .black.opacity(0.28), radius: 60, y: 24)
        .padding(.horizontal, 28)
    }
}

struct PicMeMemberPermissionsPrototypeView: View {
    @State private var upload = true
    @State private var download = true
    @State private var invite = true
    @State private var delete = false

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                simpleHeader(title: "成员权限")
                Text("通过此链接加入者的权限")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 22)
                    .padding(.top, 14)
                    .padding(.bottom, 8)
                VStack(spacing: 0) {
                    permissionToggle("允许上传照片", isOn: $upload)
                    permissionToggle("允许下载照片", isOn: $download)
                    permissionToggle("允许邀请他人", isOn: $invite)
                    permissionToggle("允许删除照片", isOn: $delete, last: true)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 4)
                .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
                .padding(.horizontal, 20)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private func permissionToggle(_ title: String, isOn: Binding<Bool>, last: Bool = false) -> some View {
        HStack {
            Text(title)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Toggle("", isOn: isOn).labelsHidden().tint(PicMeStyle.blue)
        }
        .padding(.vertical, 13)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5) }
        }
    }
}

struct PicMePermissionRequestView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let draft: PermissionRequestDraft
    @State private var permissions: AlbumPermissions

    init(draft: PermissionRequestDraft) {
        self.draft = draft
        _permissions = State(initialValue: draft.permissions)
    }

    var body: some View {
        VStack(spacing: 0) {
            simpleHeader(title: "申请权限")
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 14) {
                    albumListRow(draft.album)
                    sectionTitle("需要开启的权限", subtitle: "提交后由相册管理员审批")
                    PicMeCard(radius: 16) {
                        VStack(spacing: 0) {
                            permissionToggle("允许上传照片", icon: "square.and.arrow.up", isOn: $permissions.upload)
                            permissionToggle("允许下载照片", icon: "arrow.down.circle", isOn: $permissions.download)
                            permissionToggle("允许分享相册", icon: "link", isOn: $permissions.share)
                            permissionToggle("允许删除照片", icon: "trash", isOn: $permissions.delete, last: true)
                        }
                        .padding(.horizontal, 14)
                    }
                    HStack(spacing: 7) {
                        Image(systemName: "lock")
                            .font(.system(size: 13, weight: .semibold))
                        Text("申请记录只对相册管理员可见")
                            .font(.system(size: 12.5))
                    }
                    .foregroundColor(PicMeStyle.secondaryText)
                    .frame(maxWidth: .infinity, alignment: .center)
                    PicMePrimaryButton(title: store.isBusy ? "提交中..." : "提交申请", disabled: store.isBusy) {
                        Task {
                            _ = await store.submitPermissionRequest(album: draft.album, permissions: permissions)
                            store.permissionRequestDraft = nil
                            dismiss()
                        }
                    }
                    .padding(.top, 6)
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)
                .padding(.bottom, 34)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private func permissionToggle(_ title: String, icon: String, isOn: Binding<Bool>, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.blue)
                .frame(width: 34, height: 34)
                .background(PicMeStyle.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            Text(title)
                .font(.system(size: 15, weight: .medium))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Toggle("", isOn: isOn)
                .labelsHidden()
                .tint(PicMeStyle.blue)
        }
        .frame(height: 58)
        .overlay(alignment: .bottom) {
            if !last {
                Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 46)
            }
        }
    }
}

struct PicMeProfileEditView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    @State private var avatarPickerPresented = false
    @State private var avatarImage: UIImage?
    @State private var avatarData: Data?

    private var canSaveAvatar: Bool {
        avatarData != nil && !store.isBusy
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                editHeader
                Button {
                    avatarPickerPresented = true
                } label: {
                    ZStack(alignment: .bottomTrailing) {
                        profileAvatar
                            .frame(width: 86, height: 86)
                            .clipShape(Circle())
                            .padding(3)
                            .background(PicMeStyle.gradient, in: Circle())
                            .shadow(color: PicMeStyle.violet.opacity(0.30), radius: 28, y: 10)
                        Image(systemName: "camera")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(PicMeStyle.blue)
                            .frame(width: 30, height: 30)
                            .background(.white, in: Circle())
                            .shadow(color: .black.opacity(0.18), radius: 8, y: 2)
                            .offset(x: -2, y: -2)
                    }
                }
                .buttonStyle(.plain)
                .padding(.top, 20)
                VStack(spacing: 18) {
                    editGroup {
                        editRow("昵称", displayName)
                        editRow("头像识别", faceProfileStatusText, last: true)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("账户")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(PicMeStyle.secondaryText)
                            .padding(.horizontal, 4)
                        editGroup {
                            editRow("登录账号", accountText)
                            editRow("PicMe ID", picMeIdText, sub: "当前版本支持更新头像，昵称与账号编辑需服务端开放后启用。", last: true)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 22)
                .padding(.bottom, 28)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .sheet(isPresented: $avatarPickerPresented) {
            PicMeAvatarImagePicker { image, data in
                avatarImage = image
                avatarData = data
            }
        }
        .picMeSwipeBack()
    }

    private var editHeader: some View {
        HStack {
            Button { dismiss() } label: {
                glassIcon("chevron.left")
            }
            .buttonStyle(.plain)
            Spacer()
            Text("编辑资料")
                .font(.system(size: 17, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Button(store.isBusy ? "保存中" : "保存") {
                Task {
                    guard let avatarData else {
                        dismiss()
                        return
                    }
                    if await store.updateAvatar(avatarData: avatarData) {
                        self.avatarData = nil
                        self.avatarImage = nil
                        dismiss()
                    }
                }
            }
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(store.isBusy ? PicMeStyle.secondaryText : PicMeStyle.blue)
                .frame(width: 38, height: 38)
                .disabled(store.isBusy)
        }
        .padding(.horizontal, 16)
        .padding(.top, 50)
        .padding(.bottom, 12)
    }

    private func editGroup<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 0) { content() }
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
    }

    private func editRow(_ label: String, _ value: String, sub: String? = nil, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            Text(label)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 74, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(value)
                    .font(.system(size: 15))
                    .foregroundColor(PicMeStyle.primaryText)
                if let sub {
                    Text(sub)
                        .font(.system(size: 11.5))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .frame(height: sub == nil ? 52 : 62)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 88) }
        }
    }

    @ViewBuilder
    private var profileAvatar: some View {
        if let avatarImage {
            Image(uiImage: avatarImage)
                .resizable()
                .aspectRatio(contentMode: .fill)
        } else if let avatarUrl = store.currentUser?.avatarUrl, let url = store.imageURL(avatarUrl) {
            PicMeRemoteImage(url: url)
                .id(store.avatarImageVersion)
        } else {
            PicMeAvatar(name: displayName, size: 86)
        }
    }

    private var displayName: String {
        let nickname = store.currentUser?.nickname.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !nickname.isEmpty { return nickname }
        let username = store.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !username.isEmpty { return username }
        return store.uploader.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "PicMe 用户" : store.uploader
    }

    private var accountText: String {
        let username = store.currentUser?.username.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return username.isEmpty ? "-" : "@\(username)"
    }

    private var picMeIdText: String {
        let userId = store.currentUser?.id.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return userId.isEmpty ? "-" : userId
    }

    private var faceProfileStatusText: String {
        if store.currentUser?.hasFaceProfile == true { return "已启用人脸推荐" }
        switch store.currentUser?.faceProfileStatus {
        case "queued", "processing":
            return "头像正在后台识别"
        case "failed":
            return "头像未识别人脸"
        default:
            return "上传清晰头像后可提升推荐准确度"
        }
    }
}

private struct PicMeAvatarImagePicker: UIViewControllerRepresentable {
    let onPicked: (UIImage, Data) -> Void
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var configuration = PHPickerConfiguration(photoLibrary: .shared())
        configuration.filter = .images
        configuration.selectionLimit = 1
        let picker = PHPickerViewController(configuration: configuration)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked, dismiss: dismiss)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPicked: (UIImage, Data) -> Void
        let dismiss: DismissAction

        init(onPicked: @escaping (UIImage, Data) -> Void, dismiss: DismissAction) {
            self.onPicked = onPicked
            self.dismiss = dismiss
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            guard let provider = results.first?.itemProvider else {
                dismiss()
                return
            }
            guard provider.canLoadObject(ofClass: UIImage.self) else {
                dismiss()
                return
            }
            provider.loadObject(ofClass: UIImage.self) { [onPicked, dismiss] object, _ in
                guard let image = object as? UIImage else {
                    DispatchQueue.main.async { dismiss() }
                    return
                }
                let data = image.jpegData(compressionQuality: 0.88) ?? Data()
                DispatchQueue.main.async {
                    onPicked(image, data)
                    dismiss()
                }
            }
        }
    }
}

struct PicMeActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

struct PicMeProfileCategoryView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let title: String
    @AppStorage("PicMeProfile.faceRecognitionEnabled") private var faceOn = true
    @AppStorage("PicMeProfile.inAppNotificationsEnabled") private var notifOn = true
    @State private var checkingForUpdate = false
    @State private var updateMessage: String?
    @State private var updateAlertPresented = false

    init(title: String = "隐私与人脸识别") {
        self.title = title
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                simpleHeader(title: title)
                if title == "帮助与关于" {
                    helpAndAboutContent
                } else {
                    privacyAndGeneralContent
                }
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .alert("版本检查", isPresented: $updateAlertPresented) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(updateMessage ?? "当前已是最新可用版本。")
        }
    }

    private var privacyAndGeneralContent: some View {
        VStack(spacing: 0) {
            VStack(spacing: 0) {
                settingToggle("person", "允许在他人相册中识别我", isOn: $faceOn)
                settingRow("eye", "谁可以找到我", value: "相册成员")
                settingRow("sparkles", "我的人脸数据", last: true)
            }
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
            .padding(.horizontal, 20)
            .padding(.top, 18)
            Text("通用")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 24)
                .padding(.top, 22)
                .padding(.bottom, 8)
            VStack(spacing: 0) {
                settingToggle("bell", "应用内通知提示", isOn: $notifOn)
                settingRow("arrow.down", "下载画质", value: "原图")
                Button {
                    Task {
                        await PhotoDiskCache.shared.clearAll()
                        store.statusText = "照片缓存已清理"
                    }
                } label: {
                    settingRow("folder", "清理缓存", value: "立即清理", last: true)
                }
                .buttonStyle(.plain)
            }
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
            .padding(.horizontal, 20)
        }
    }

    private var helpAndAboutContent: some View {
        VStack(spacing: 16) {
            VStack(spacing: 8) {
                Image("PicMeLogo")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 70, height: 70)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                Text("识我")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("版本 \(appVersion) · 构建 \(buildNumber)")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 24)
            .padding(.bottom, 10)
            VStack(spacing: 0) {
                Button {
                    checkForUpdate()
                } label: {
                    settingRow("arrow.triangle.2.circlepath", "检查版本更新", value: checkingForUpdate ? "检查中..." : nil)
                }
                .buttonStyle(.plain)
                .disabled(checkingForUpdate)
                settingRow("doc.text", "用户协议")
                settingRow("hand.raised", "隐私政策", last: true)
            }
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
            .padding(.horizontal, 20)
            if let updateMessage {
                Text(updateMessage)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .multilineTextAlignment(.center)
                    .lineSpacing(2)
                    .padding(.horizontal, 28)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: updateMessage)
    }

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
    }

    private var buildNumber: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "-"
    }

    private func checkForUpdate() {
        checkingForUpdate = true
        updateMessage = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            checkingForUpdate = false
            updateMessage = "当前已是最新可用版本。TestFlight 有新版本时会自动提示更新。"
            updateAlertPresented = true
        }
    }

    private func settingRow(_ icon: String, _ label: String, value: String? = nil, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            settingIcon(icon)
            Text(label)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            if let value {
                Text(value)
                    .font(.system(size: 13.5))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 58)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 58) }
        }
    }

    private func settingToggle(_ icon: String, _ label: String, isOn: Binding<Bool>, last: Bool = false) -> some View {
        HStack(spacing: 12) {
            settingIcon(icon)
            Text(label)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Toggle("", isOn: isOn).labelsHidden().tint(PicMeStyle.blue)
        }
        .padding(.horizontal, 14)
        .frame(height: 58)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 58) }
        }
    }

    private func settingIcon(_ icon: String) -> some View {
        Image(systemName: icon)
            .font(.system(size: 17, weight: .semibold))
            .foregroundColor(PicMeStyle.blue)
            .frame(width: 32, height: 32)
            .background(PicMeStyle.blue.opacity(0.11), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
    }
}

struct PicMeRegisterPrototypeView: View {
    let step: Int
    var onLogin: (() -> Void)?
    @State private var currentStep: Int
    private let wall = ["warm", "people", "nature", "city", "food", "people", "night", "people", "cool", "warm", "people", "nature", "food", "people", "city"]

    init(step: Int, onLogin: (() -> Void)? = nil) {
        self.step = step
        self.onLogin = onLogin
        _currentStep = State(initialValue: step)
    }

    var body: some View {
        ZStack {
            PicMeStyle.background.ignoresSafeArea()
            switch currentStep {
            case 2:
                welcomeStep
            case 3:
                faceUploadStep
            case 4:
                faceDoneStep
            default:
                accountStep
            }
        }
    }

    private var accountStep: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                ZStack(alignment: .bottom) {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 5), count: 3), spacing: 5) {
                        ForEach(Array(wall.enumerated()), id: \.offset) { _, kind in
                            PicMeStripePlaceholder(seed: kind)
                                .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                                .aspectRatio(1, contentMode: .fit)
                        }
                    }
                    .padding(5)
                    LinearGradient(colors: [.clear, PicMeStyle.background], startPoint: .center, endPoint: .bottom)
                }
                .frame(height: 296)
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 10) {
                        PicMeLogoMark(size: 44)
                        Text("PicMe")
                            .font(.system(size: 24, weight: .black))
                            .foregroundColor(PicMeStyle.primaryText)
                    }
                    Text("找到别人\n拍到你的照片")
                        .font(.system(size: 28, weight: .black))
                        .foregroundColor(PicMeStyle.primaryText)
                        .lineSpacing(1)
                        .padding(.top, 20)
                    Text("AI 自动整理聚会、旅行、家庭相册中的照片")
                        .font(.system(size: 16))
                        .foregroundColor(PicMeStyle.secondaryText)
                        .lineSpacing(2)
                        .padding(.top, 10)
                    VStack(spacing: 12) {
                        lightField("person", "登录账号 / PicMe ID", "picme_user")
                        lightField("lock", "设置密码", "123456", secure: true)
                    }
                    .padding(.top, 24)
                    PicMePrimaryButton(title: "立即开始") {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 2 }
                    }
                        .padding(.top, 18)
                    Button("已有账号? 立即登录") { onLogin?() }
                        .font(.system(size: 13.5, weight: .semibold))
                        .foregroundColor(PicMeStyle.blue)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 16)
                }
                .padding(.horizontal, 28)
                .padding(.bottom, 46)
                .offset(y: -44)
            }
        }
    }

    private var welcomeStep: some View {
        VStack(spacing: 0) {
            Button { withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 1 } } label: {
                glassIcon("chevron.left")
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.leading, 16)
            .padding(.top, 54)
            Image(systemName: "sparkles")
                .font(.system(size: 36, weight: .bold))
                .foregroundColor(.white)
                .frame(width: 72, height: 72)
                .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                .shadow(color: PicMeStyle.violet.opacity(0.34), radius: 32, y: 14)
                .padding(.top, 46)
            Text("欢迎来到 PicMe")
                .font(.system(size: 25, weight: .black))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 20)
            Text("上传一张清晰正脸照，系统会在共享相册里自动帮你找到出现在照片中的自己")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
                .lineSpacing(2)
                .padding(.horizontal, 28)
                .padding(.top, 8)
            VStack(spacing: 12) {
                onboardingRow("person", "自动识别人物", "AI 识别相册里出现的每个人")
                onboardingRow("sparkles", "自动归类照片", "按人物、合照、场景智能整理")
                onboardingRow("heart", "发现别人拍到你", "找到朋友镜头里的你，一键收藏")
            }
            .padding(.horizontal, 24)
            .padding(.top, 28)
            Spacer()
            PicMePrimaryButton(title: "上传照片", systemImage: "camera") {
                withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 3 }
            }
                .padding(.horizontal, 24)
            Button("稍后再说") { withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 4 } }
                .font(.system(size: 14.5, weight: .semibold))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(height: 44)
                .padding(.bottom, 30)
        }
    }

    private var faceUploadStep: some View {
        VStack(spacing: 0) {
            Button { withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 2 } } label: {
                glassIcon("chevron.left")
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.leading, 16)
            .padding(.top, 54)
            Text("上传一张正脸照")
                .font(.system(size: 24, weight: .black))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 34)
            Text("清晰、光线充足、不遮挡五官")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .padding(.top, 8)
            Spacer()
            ZStack {
                Circle()
                    .stroke(PicMeStyle.blue.opacity(0.42), style: StrokeStyle(lineWidth: 2, dash: [8, 7]))
                    .frame(width: 200, height: 200)
                    .background(PicMeStyle.card, in: Circle())
                VStack(spacing: 8) {
                    Image(systemName: "camera")
                        .font(.system(size: 40, weight: .medium))
                        .foregroundColor(PicMeStyle.blue)
                    Text("点击上传")
                        .font(.system(size: 13.5, weight: .semibold))
                        .foregroundColor(PicMeStyle.blue)
                }
            }
            Spacer()
            VStack(spacing: 11) {
                privacyLine("lock", "仅用于照片匹配")
                privacyLine("eye", "不会公开展示")
                privacyLine("checkmark", "不会用于其他用途")
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 14)
            .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 18, y: 4)
            .padding(.horizontal, 24)
            .padding(.bottom, 18)
            PicMePrimaryButton(title: "上传正脸照", systemImage: "camera") {
                withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) { currentStep = 4 }
            }
                .padding(.horizontal, 24)
                .padding(.bottom, 30)
        }
    }

    private var faceDoneStep: some View {
        VStack(spacing: 0) {
            Spacer()
            ZStack(alignment: .bottomTrailing) {
                PicMeStripePlaceholder(seed: "people")
                    .frame(width: 128, height: 128)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(.white, lineWidth: 4))
                    .padding(4)
                    .background(PicMeStyle.gradient, in: Circle())
                    .shadow(color: PicMeStyle.violet.opacity(0.4), radius: 40, y: 16)
                Image(systemName: "checkmark")
                    .font(.system(size: 19, weight: .black))
                    .foregroundColor(.white)
                    .frame(width: 40, height: 40)
                    .background(PicMeStyle.green, in: Circle())
                    .overlay(Circle().stroke(.white, lineWidth: 3))
            }
            Text("准备好了")
                .font(.system(size: 27, weight: .black))
                .foregroundColor(PicMeStyle.primaryText)
                .padding(.top, 28)
            Text("以后在共享相册里，系统会自动帮你找到别人拍到你的照片")
                .font(.system(size: 16))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
                .lineSpacing(3)
                .padding(.horizontal, 44)
                .padding(.top, 10)
            Spacer()
            PicMePrimaryButton(title: "进入 PicMe") { onLogin?() }
                .padding(.horizontal, 24)
                .padding(.bottom, 34)
        }
    }

    private func lightField(_ icon: String, _ placeholder: String, _ value: String, secure: Bool = false) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.secondaryText)
            Text(secure ? String(repeating: "•", count: value.count) : value)
                .font(.system(size: 15))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
        }
        .frame(height: 52)
        .padding(.horizontal, 16)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 14, y: 3)
    }

    private func onboardingRow(_ icon: String, _ title: String, _ desc: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 22, weight: .semibold))
                .foregroundColor(PicMeStyle.blue)
                .frame(width: 46, height: 46)
                .background(PicMeStyle.gradient.opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 15.5, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text(desc)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 18, y: 4)
    }

    private func privacyLine(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .bold))
                .foregroundColor(PicMeStyle.green)
            Text(text)
                .font(.system(size: 13.5))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
        }
    }
}

struct PicMePersonPrototypeView: View {
    private let kinds = ["people", "warm", "nature", "food", "cool", "people", "city", "warm", "people"]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                simpleHeader(title: "飞飞")
                PicMeAvatar(name: "飞飞", size: 92)
                    .padding(3)
                    .background(PicMeStyle.gradient, in: Circle())
                    .shadow(color: PicMeStyle.violet.opacity(0.30), radius: 30, y: 10)
                    .padding(.top, 14)
                Text("飞飞")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.top, 14)
                HStack(spacing: 0) {
                    statPill("48", "张照片")
                    Rectangle().fill(PicMeStyle.hairline).frame(width: 1).padding(.vertical, 7)
                    statPill("12", "个相册")
                }
                .padding(.top, 14)
                HStack(spacing: 0) {
                    Text("照片")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                        .background(PicMeStyle.gradient, in: Capsule())
                    Text("相册")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundColor(PicMeStyle.secondaryText)
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                }
                .padding(3)
                .background(PicMeStyle.ink.opacity(0.06), in: Capsule())
                .padding(.horizontal, 20)
                .padding(.top, 22)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                    ForEach(Array(kinds.enumerated()), id: \.offset) { index, kind in
                        PicMeStripePlaceholder(seed: kind)
                            .overlay {
                                if kind == "people" {
                                    Text("人物 飞飞")
                                        .font(.system(size: 10, weight: .bold))
                                        .foregroundColor(PicMeStyle.ink.opacity(0.45))
                                }
                            }
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            .aspectRatio(1, contentMode: .fit)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 16)
                .padding(.bottom, 28)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private func statPill(_ value: String, _ label: String) -> some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.system(size: 24, weight: .bold))
                .foregroundColor(PicMeStyle.primaryText)
            Text(label)
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.secondaryText)
        }
        .padding(.horizontal, 24)
    }
}

struct PicMeGroupPrototypeView: View {
    private let people = ["张三", "李四", "王五", "小美", "飞飞", "阿May"]
    private let kinds = ["people", "warm", "city", "people", "nature", "people", "warm", "city"]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                simpleHeader(title: "合照")
                HStack(spacing: -16) {
                    ForEach(Array(people.prefix(5).enumerated()), id: \.offset) { _, name in
                        PicMeAvatar(name: name, size: 56)
                            .overlay(Circle().stroke(.white, lineWidth: 2))
                            .padding(2)
                            .background(PicMeStyle.gradient, in: Circle())
                    }
                    Text("+1")
                        .font(.system(size: 16, weight: .black))
                        .foregroundColor(PicMeStyle.blue)
                        .frame(width: 60, height: 60)
                        .background(PicMeStyle.blue.opacity(0.14), in: Circle())
                        .overlay(Circle().stroke(.white, lineWidth: 3))
                }
                .padding(.top, 14)
                Text("全员同框")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.top, 16)
                Text("6 人同框 · 8 张合照")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .padding(.top, 6)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                    ForEach(Array(kinds.enumerated()), id: \.offset) { index, kind in
                        ZStack(alignment: .topTrailing) {
                            PicMeStripePlaceholder(seed: kind)
                                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            HStack(spacing: 3) {
                                Image(systemName: "person.2")
                                    .font(.system(size: 10, weight: .bold))
                                Text("\(index == 2 ? 5 : 6)")
                                    .font(.system(size: 9.5, weight: .bold, design: .monospaced))
                            }
                            .foregroundColor(.white)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 4)
                            .background(.black.opacity(0.55), in: Capsule())
                            .padding(6)
                        }
                        .aspectRatio(1, contentMode: .fit)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 22)
                Text("其他常见组合")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.top, 26)
                    .padding(.bottom, 12)
                VStack(spacing: 10) {
                    groupRow("你 和 张三", "2 人同框 · 15 张", ["飞飞", "张三"], seed: "warm")
                    groupRow("三人行", "3 人同框 · 9 张", ["李四", "王五"], seed: "city")
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 28)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
    }

    private func groupRow(_ title: String, _ subtitle: String, _ names: [String], seed: String) -> some View {
        HStack(spacing: 12) {
            ZStack(alignment: .bottomLeading) {
                PicMeStripePlaceholder(seed: seed)
                    .frame(width: 56, height: 56)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .opacity(0.82)
                HStack(spacing: -7) {
                    ForEach(names, id: \.self) { PicMeAvatar(name: $0, size: 20).overlay(Circle().stroke(.white, lineWidth: 1.5)) }
                }
                .padding(5)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text(subtitle)
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .bold))
                .foregroundColor(Color(hex: 0xC7CDD6))
        }
        .padding(10)
        .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .shadow(color: PicMeStyle.ink.opacity(0.04), radius: 12, y: 3)
    }
}

private func simpleHeader(title: String) -> some View {
    HStack {
        PicMeDismissCircleButton()
        Spacer()
        Text(title)
            .font(.system(size: 17, weight: .bold))
            .foregroundColor(PicMeStyle.primaryText)
        Spacer()
        Color.clear.frame(width: 38, height: 38)
    }
    .padding(.horizontal, 16)
    .padding(.top, 50)
    .padding(.bottom, 12)
    .background(PicMeStyle.background.opacity(0.82))
}

private struct PicMeDismissCircleButton: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Button { dismiss() } label: {
            glassIcon("chevron.left")
        }
        .buttonStyle(.plain)
    }
}

private struct PicMeUploadView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var pickerPresented = false
    @State private var pendingAssets: [PHAsset] = []

    private var album: Album? { store.album(id: albumId) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                PicMeTopBar(title: store.isUploading ? "正在上传" : "上传确认", subtitle: album?.name)
                if !pendingAssets.isEmpty && !store.isUploading {
                    uploadSummary(count: pendingAssets.count)
                    PicMePrimaryButton(title: "开始上传", systemImage: "icloud.and.arrow.up") {
                        store.selectAlbum(id: albumId)
                        store.startUploadAssets(pendingAssets)
                        pendingAssets = []
                    }
                } else if store.isUploading {
                    progressCard
                } else {
                    uploadIntro
                    PicMePrimaryButton(title: "选择照片", systemImage: "photo.on.rectangle") {
                        pickerPresented = true
                    }
                }
                Spacer(minLength: 24)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 32)
        }
        .background(PicMeBackground())
        .sheet(isPresented: $pickerPresented) {
            LivePhotoPicker { assets in
                pendingAssets = assets
                pickerPresented = false
            }
        }
        .picMeSwipeBack()
    }

    private var uploadIntro: some View {
        PicMeCard(radius: 22) {
            HStack(spacing: 14) {
                Image(systemName: "sparkles")
                    .font(.title2.weight(.black))
                    .foregroundColor(.white)
                    .frame(width: 52, height: 52)
                    .background(PicMeStyle.gradient, in: Circle())
                VStack(alignment: .leading, spacing: 5) {
                    Text("上传后自动识别人物与合照")
                        .font(.headline.weight(.black))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text("照片上传完成后，AI 会在云端后台识别人脸，并按人物、合照自动归类。")
                        .font(.caption.weight(.semibold))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
            }
            .padding(18)
        }
    }

    private func uploadSummary(count: Int) -> some View {
        PicMeCard(radius: 18) {
            VStack(spacing: 12) {
                metricRow("photo", "\(count) 张照片", "含普通照片与 Live Photo")
                Divider()
                metricRow("icloud", "预计上传 \(max(1, count / 3)) MB", "Wi-Fi 环境可后台继续")
            }
            .padding(16)
        }
    }

    private var progressCard: some View {
        PicMeCard(radius: 22) {
            VStack(spacing: 16) {
                Image(systemName: "icloud.and.arrow.up.fill")
                    .font(.system(size: 42, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 92, height: 92)
                    .background(PicMeStyle.gradient, in: Circle())
                Text("\(Int(((store.uploadProgressFraction ?? 0) * 100).rounded()))%")
                    .font(.system(size: 34, weight: .black))
                    .foregroundColor(PicMeStyle.primaryText)
                ProgressView(value: store.uploadProgressFraction ?? 0)
                    .tint(PicMeStyle.blue)
                Text(store.uploadProgressText.isEmpty ? "正在上传照片，请保持网络连接" : store.uploadProgressText)
                    .font(.caption.weight(.semibold))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .multilineTextAlignment(.center)
                Button("取消上传", role: .destructive) { store.cancelCurrentUpload() }
            }
            .padding(22)
        }
    }
}

struct PicMeShareView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    @State private var invite: AlbumInvite?
    @State private var toast: String?
    @State private var copiedInviteLink = false

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                PicMeTopBar(title: "分享 \(album.name)")
                PicMeCard(radius: 22) {
                    VStack(spacing: 14) {
                        QRPlaceholder()
                            .frame(width: 172, height: 172)
                            .padding(14)
                            .background(.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                        Text("扫码加入「\(album.name)」")
                            .font(.headline.weight(.black))
                        Text("好友提交申请后，需要你审批通过才会加入")
                            .font(.caption.weight(.semibold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    .padding(22)
                }
                copyRow(invite?.shareUrl ?? "正在生成链接…")
                PicMePrimaryButton(title: "分享到微信", systemImage: "square.and.arrow.up") {
                    if let url = URL(string: invite?.shareUrl ?? "") {
                        store.shareableFile = ShareableFile(url: url)
                    } else {
                        toast = "链接生成中"
                    }
                }
                sectionTitle("加入与权限", subtitle: "好友申请通过后，将获得以下权限")
                PermissionList(permissions: invite?.permissions ?? album.memberPermissions)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 34)
        }
        .background(PicMeBackground())
        .task {
            do { invite = try await store.fetchInvite(album: album) } catch { store.statusText = error.sharePhotosNetworkMessage }
        }
        .overlay(alignment: .bottom) {
            if let toast {
                Text(toast).toastStyle().onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { self.toast = nil } }
            }
        }
        .picMeSwipeBack()
    }

    private func copyRow(_ value: String) -> some View {
        Button {
            guard invite?.shareUrl != nil else {
                toast = "链接生成中"
                return
            }
            UIPasteboard.general.string = value
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            copiedInviteLink = true
            toast = "已复制邀请链接"
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
                copiedInviteLink = false
            }
        } label: {
            HStack {
                Image(systemName: "link").foregroundColor(PicMeStyle.blue)
                Text(value).lineLimit(1)
                Spacer()
                Label(copiedInviteLink ? "已复制" : "复制", systemImage: copiedInviteLink ? "checkmark" : "doc.on.doc")
                    .font(.caption.weight(.black))
                    .foregroundColor(PicMeStyle.blue)
            }
            .font(.subheadline.weight(.semibold))
            .foregroundColor(PicMeStyle.primaryText)
            .padding(14)
            .background(.black.opacity(0.04), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

struct PicMeJoinView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    @State var initialCode: String
    @State private var submitted = false

    var body: some View {
        VStack(spacing: 18) {
            PicMeTopBar(title: "加入相册")
            if submitted {
                Spacer()
                Image(systemName: "hourglass")
                    .font(.system(size: 50, weight: .semibold))
                    .foregroundColor(PicMeStyle.orange)
                    .frame(width: 108, height: 108)
                    .background(PicMeStyle.orange.opacity(0.14), in: Circle())
                Text("申请已提交").font(.title2.weight(.black))
                Text("管理员处理后会通过消息通知你。").font(.body.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
                PicMePrimaryButton(title: "知道了") { dismiss() }.padding(.horizontal, 20)
                Spacer()
            } else {
                PicMeCard(radius: 18) {
                    HStack(spacing: 12) {
                        PicMeStripePlaceholder(seed: "join").frame(width: 58, height: 58).clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        VStack(alignment: .leading, spacing: 4) {
                            Text("共享相册").font(.headline.weight(.black))
                            Text("输入邀请码后申请加入").font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
                        }
                        Spacer()
                        picMeBadge("需审批", color: PicMeStyle.orange.opacity(0.16), foreground: PicMeStyle.orange)
                    }
                    .padding(14)
                }
                TextField("相册码", text: $initialCode)
                    .textInputAutocapitalization(.characters)
                    .font(.title3.weight(.black))
                    .multilineTextAlignment(.center)
                    .padding()
                    .background(.white.opacity(0.9), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .padding(.horizontal, 20)
                PicMePrimaryButton(title: "提交申请") {
                    Task {
                        if await store.submitJoinRequest(code: initialCode) {
                            submitted = true
                        }
                    }
                }
                .padding(.horizontal, 20)
                Spacer()
            }
        }
        .background(PicMeBackground())
        .picMeSwipeBack()
    }
}

struct PicMeMessagesView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    @State private var messages: [InboxMessage] = []
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Button { dismiss() } label: { Image(systemName: "chevron.left").font(.headline.weight(.bold)) }
                    Text("通知").font(.system(size: 28, weight: .black))
                    Spacer()
                    Button("全部已读") { Task { await store.markAllMessagesRead(); await reloadMessages() } }
                        .font(.caption.weight(.bold))
                }
                .foregroundColor(PicMeStyle.primaryText)

                if isLoading {
                    ProgressView("正在加载消息")
                        .frame(maxWidth: .infinity, minHeight: 180)
                } else if messages.isEmpty {
                    emptyState(icon: "bell", title: "暂无站内消息", message: "新的加入申请、权限申请和相册动态会显示在这里。")
                } else {
                    VStack(spacing: 12) {
                        ForEach(messages) { message in
                            Button {
                                Task {
                                    await store.openMessage(message)
                                    await reloadMessages()
                                    if message.albumId?.isEmpty == false {
                                        dismiss()
                                    }
                                }
                            } label: {
                                messageRow(message)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(20)
        }
        .background(PicMeBackground())
        .task { await reloadMessages() }
        .picMeSwipeBack()
    }

    private func reloadMessages() async {
        isLoading = true
        messages = await store.loadMessages()
        isLoading = false
    }

    private func messageRow(_ message: InboxMessage) -> some View {
        PicMeCard(radius: 16) {
            HStack(spacing: 12) {
                PicMeAvatar(name: message.title, size: 46)
                VStack(alignment: .leading, spacing: 4) {
                    Text(message.title).font(.subheadline.weight(.black)).foregroundColor(PicMeStyle.primaryText)
                    Text(message.body ?? message.albumName ?? "PicMe 消息").font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText).lineLimit(2)
                    if let albumName = message.albumName, !albumName.isEmpty {
                        Label(albumName, systemImage: "photo.stack")
                            .font(.caption2.weight(.bold))
                            .foregroundColor(PicMeStyle.blue)
                    }
                    if let statusText = message.statusDisplayText {
                        Text(statusText)
                            .font(.caption2.weight(.black))
                            .foregroundColor(message.status == "pending" ? PicMeStyle.blue : PicMeStyle.secondaryText)
                    }
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 8) {
                    if let createdAt = message.createdAt {
                        Text(formatDate(createdAt))
                            .font(.caption2.weight(.bold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    Circle()
                        .fill(message.isRead ? Color.gray.opacity(0.2) : PicMeStyle.blue)
                        .frame(width: 8, height: 8)
                }
            }
            .padding(12)
        }
    }

    private func formatDate(_ timestamp: Int) -> String {
        let date = Date(timeIntervalSince1970: TimeInterval(timestamp))
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    private func emptyState(icon: String, title: String, message: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 28, weight: .bold))
                .foregroundColor(PicMeStyle.blue)
            Text(title)
                .font(.headline.weight(.black))
                .foregroundColor(PicMeStyle.primaryText)
            Text(message)
                .font(.caption.weight(.semibold))
                .foregroundColor(PicMeStyle.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 180)
        .padding(20)
        .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
    }
}

struct PicMeApprovalsView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    var onClose: (() -> Void)?
    @State private var joinRequests: [JoinRequest] = []
    @State private var permissionRequests: [AlbumPermissionRequest] = []

    private var album: Album? { store.album(id: albumId) }
    private var pendingJoinRequests: [JoinRequest] { joinRequests.filter { $0.status == "pending" } }
    private var pendingPermissionRequests: [AlbumPermissionRequest] { permissionRequests.filter { $0.status == "pending" } }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Button { close() } label: { glassIcon("chevron.left") }
                        .buttonStyle(.plain)
                    Spacer()
                    Text("申请审批")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundColor(PicMeStyle.primaryText)
                    Spacer()
                    Color.clear.frame(width: 42, height: 42)
                }
                .padding(.horizontal, 16)
                .padding(.top, 50)

                if let album {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(album.name)
                            .font(.system(size: 28, weight: .bold))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text("\(pendingJoinRequests.count) 个加入申请 · \(pendingPermissionRequests.count) 个权限申请")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    .padding(.horizontal, 20)
                }

                approvalSection(title: "加入申请", isEmpty: pendingJoinRequests.isEmpty, emptyIcon: "person.badge.clock", emptyMessage: "新的申请会从消息通知进入这里。") {
                    ForEach(pendingJoinRequests) { request in
                        approvalCard(
                            name: request.user.nickname,
                            account: "@\(request.user.username)",
                            detail: "申请加入相册",
                            approve: { await reviewJoin(request, approve: true) },
                            reject: { await reviewJoin(request, approve: false) }
                        )
                    }
                }

                approvalSection(title: "权限申请", isEmpty: pendingPermissionRequests.isEmpty, emptyIcon: "lock.shield", emptyMessage: "成员申请上传、下载、分享等权限后会出现在这里。") {
                    ForEach(pendingPermissionRequests) { request in
                        approvalCard(
                            name: request.user.nickname,
                            account: "@\(request.user.username)",
                            detail: "当前：\(permissionSummary(request.currentPermissions))\n申请：\(permissionSummary(request.requestedPermissions))",
                            approve: { await reviewPermission(request, approve: true) },
                            reject: { await reviewPermission(request, approve: false) }
                        )
                    }
                }
            }
            .padding(.bottom, 34)
        }
        .background(PicMeBackground())
        .task { await reload() }
        .picMeSwipeBack()
    }

    private func approvalSection<Content: View>(title: String, isEmpty: Bool, emptyIcon: String, emptyMessage: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle(title, subtitle: nil)
                .padding(.horizontal, 20)
            if isEmpty {
                emptyState(icon: emptyIcon, title: "暂无待审批\(title)", message: emptyMessage)
                    .padding(.horizontal, 20)
            } else {
                VStack(spacing: 12) { content() }
                    .padding(.horizontal, 20)
            }
        }
    }

    private func approvalCard(name: String, account: String, detail: String, approve: @escaping () async -> Void, reject: @escaping () async -> Void) -> some View {
        PicMeCard(radius: 18) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    PicMeAvatar(name: name, size: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(name)
                            .font(.headline.weight(.black))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text(account)
                            .font(.caption.weight(.semibold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                    Spacer()
                }
                Text(detail)
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 10) {
                    Button {
                        Task { await reject() }
                    } label: {
                        Text("拒绝")
                            .font(.subheadline.weight(.black))
                            .foregroundColor(PicMeStyle.red)
                            .frame(maxWidth: .infinity, minHeight: 42)
                            .background(PicMeStyle.red.opacity(0.10), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    Button {
                        Task { await approve() }
                    } label: {
                        Text("批准")
                            .font(.subheadline.weight(.black))
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity, minHeight: 42)
                            .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
                .disabled(store.isBusy)
                .opacity(store.isBusy ? 0.6 : 1)
            }
            .padding(16)
        }
    }

    private func close() {
        if let onClose {
            onClose()
        } else {
            dismiss()
        }
    }

    private func reload() async {
        await store.refreshAlbum(id: albumId)
        guard let album = store.album(id: albumId) else { return }
        joinRequests = await store.loadJoinRequests(album: album)
        permissionRequests = album.canEditMembers ? await store.loadPermissionRequests(album: album) : []
    }

    private func reviewJoin(_ request: JoinRequest, approve: Bool) async {
        guard let album else { return }
        await store.reviewJoinRequest(album: album, request: request, approve: approve)
        await reload()
    }

    private func reviewPermission(_ request: AlbumPermissionRequest, approve: Bool) async {
        guard let album else { return }
        await store.reviewPermissionRequest(album: album, request: request, approve: approve)
        await reload()
    }
}

private struct PicMeMembersView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    @State private var members: [AlbumMember] = []
    @State private var selectedMember: AlbumMember?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                PicMeTopBar(title: "相册成员 · \(members.count)")
                ForEach(members) { member in
                    Button {
                        guard album.canEditMembers && !member.isOwner else { return }
                        selectedMember = member
                    } label: {
                        memberRow(member)
                    }
                    .buttonStyle(.plain)
                    .disabled(!album.canEditMembers || member.isOwner)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 34)
        }
        .background(PicMeBackground())
        .task { members = await store.loadAlbumMembers(album: album) }
        .sheet(item: $selectedMember) { member in
            PicMeMemberPermissionSheet(album: album, member: member) {
                members = await store.loadAlbumMembers(album: album)
            }
            .environmentObject(store)
        }
        .picMeSwipeBack()
    }

    private func memberRow(_ member: AlbumMember) -> some View {
        PicMeCard(radius: 16) {
            HStack(spacing: 12) {
                PicMeAvatar(name: member.user.nickname, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(member.user.nickname + (member.isOwner ? " · 创建者" : ""))
                        .font(.subheadline.weight(.black))
                        .foregroundColor(PicMeStyle.primaryText)
                    Text(permissionSummary(member.effectivePermissions))
                        .font(.caption.weight(.semibold))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
                Spacer()
                if album.canEditMembers && !member.isOwner {
                    Image(systemName: "chevron.right")
                        .foregroundColor(PicMeStyle.secondaryText.opacity(0.55))
                }
            }
            .padding(12)
        }
    }
}

private struct PicMeMemberPermissionSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let album: Album
    let member: AlbumMember
    let onChanged: () async -> Void
    @State private var permissions: AlbumPermissions

    init(album: Album, member: AlbumMember, onChanged: @escaping () async -> Void) {
        self.album = album
        self.member = member
        self.onChanged = onChanged
        _permissions = State(initialValue: member.permissions)
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 16) {
                Capsule().fill(.black.opacity(0.14)).frame(width: 38, height: 5).frame(maxWidth: .infinity)
                HStack(spacing: 12) {
                    PicMeAvatar(name: member.user.nickname, size: 52)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(member.user.nickname)
                            .font(.headline.weight(.black))
                            .foregroundColor(PicMeStyle.primaryText)
                        Text("@\(member.user.username)")
                            .font(.caption.weight(.semibold))
                            .foregroundColor(PicMeStyle.secondaryText)
                    }
                }
                PermissionEditor(permissions: $permissions)
                PicMePrimaryButton(title: store.isBusy ? "保存中" : "保存权限", disabled: store.isBusy) {
                    Task {
                        _ = await store.updateMemberPermissions(album: album, member: member, permissions: permissions)
                        await onChanged()
                        dismiss()
                    }
                }
                Button(role: .destructive) {
                    Task {
                        _ = await store.removeMember(album: album, member: member)
                        await onChanged()
                        dismiss()
                    }
                } label: {
                    Text("移除成员")
                        .font(.headline.weight(.bold))
                        .foregroundColor(PicMeStyle.red)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(PicMeStyle.red.opacity(0.10), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(store.isBusy)
            }
            .padding(22)
        }
        .background(PicMeBackground())
        .picMeSwipeBack()
    }
}

private struct PermissionEditor: View {
    @Binding var permissions: AlbumPermissions

    var body: some View {
        PicMeCard(radius: 16) {
            VStack(spacing: 0) {
                permissionToggle("允许上传照片", icon: "arrow.up.circle", value: $permissions.upload)
                permissionToggle("允许下载照片", icon: "arrow.down.circle", value: $permissions.download)
                permissionToggle("允许分享相册", icon: "square.and.arrow.up", value: $permissions.share)
                permissionToggle("允许删除照片", icon: "trash", value: $permissions.delete, last: true)
            }
            .padding(.horizontal, 14)
        }
    }

    private func permissionToggle(_ title: String, icon: String, value: Binding<Bool>, last: Bool = false) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundColor(PicMeStyle.blue)
                .frame(width: 28, height: 28)
                .background(PicMeStyle.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            Toggle("", isOn: value)
                .labelsHidden()
                .tint(PicMeStyle.blue)
        }
        .frame(height: 54)
        .overlay(alignment: .bottom) {
            if !last { Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5).padding(.leading, 38) }
        }
    }
}

private struct PicMeAlbumSettingsView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let onShare: () -> Void
    @State private var renameOpen = false
    @State private var draftName = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Capsule().fill(.black.opacity(0.14)).frame(width: 38, height: 5).frame(maxWidth: .infinity)
            Text("相册设置").font(.title3.weight(.black)).foregroundColor(PicMeStyle.primaryText)
            Button(action: onShare) { settingsRow("分享与邀请", icon: "square.and.arrow.up") }
            Button {
                draftName = album.name
                renameOpen = true
            } label: {
                settingsRow("重命名相册", icon: "pencil")
            }
            .buttonStyle(.plain)
            sectionTitle("成员默认权限", subtitle: nil)
            PermissionList(permissions: album.memberPermissions)
            Spacer()
        }
        .padding(20)
        .background(PicMeBackground())
        .sheet(isPresented: $renameOpen) {
            PicMeRenameAlbumSheet(album: album, name: $draftName)
                .environmentObject(store)
        }
    }
}

private struct PicMeRenameAlbumSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let album: Album
    @Binding var name: String

    var body: some View {
        VStack(spacing: 18) {
            Capsule().fill(.black.opacity(0.14)).frame(width: 38, height: 5)
            Text("重命名相册")
                .font(.title3.weight(.black))
                .foregroundColor(PicMeStyle.primaryText)
            TextField("相册名称", text: $name)
                .font(.title3.weight(.black))
                .multilineTextAlignment(.center)
                .padding()
                .background(.white, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            PicMePrimaryButton(title: store.isBusy ? "保存中" : "保存", disabled: name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isBusy) {
                Task {
                    await store.renameAlbum(album, name: name)
                    dismiss()
                }
            }
            Button("取消") { dismiss() }
                .font(.subheadline.weight(.bold))
                .foregroundColor(PicMeStyle.secondaryText)
            Spacer()
        }
        .padding(22)
        .background(PicMeBackground())
    }
}

struct PicMeCreateAlbumView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    var onEnterAlbum: (Album) -> Void = { _ in }
    var onShareAlbum: (Album) -> Void = { _ in }
    @State private var name = ""
    @State private var createdAlbum: Album?

    var body: some View {
        ZStack {
            PicMeBackground()
            PicMeCard(radius: 24) {
                VStack(spacing: 18) {
                    if let album = createdAlbum {
                        Image(systemName: "checkmark")
                            .font(.system(size: 38, weight: .black))
                            .foregroundColor(PicMeStyle.green)
                            .frame(width: 72, height: 72)
                            .background(PicMeStyle.green.opacity(0.14), in: Circle())
                        Text("相册创建成功").font(.title3.weight(.black))
                        Text("把「\(album.name)」分享给好友，一起上传照片吧").font(.subheadline.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText).multilineTextAlignment(.center)
                        PicMePrimaryButton(title: "去分享相册", systemImage: "square.and.arrow.up") {
                            onShareAlbum(album)
                            dismiss()
                        }
                        Button("先进入相册") {
                            onEnterAlbum(album)
                            dismiss()
                        }
                        .font(.subheadline.weight(.bold))
                        .foregroundColor(PicMeStyle.secondaryText)
                    } else {
                        Text("新建相册").font(.title3.weight(.black))
                        TextField("相册名称", text: $name)
                            .font(.title3.weight(.black))
                            .multilineTextAlignment(.center)
                            .padding()
                            .background(.white, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        HStack(spacing: 12) {
                            Button("取消") { dismiss() }
                                .font(.headline.weight(.bold))
                                .frame(maxWidth: .infinity, minHeight: 50)
                                .background(.black.opacity(0.05), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            PicMePrimaryButton(title: "创建", disabled: name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) {
                                Task { createdAlbum = await store.createAlbum(name: name) }
                            }
                        }
                    }
                }
                .padding(22)
            }
            .padding(28)
        }
    }
}

private struct MyPhotoItem: Identifiable, Hashable {
    let album: Album
    let photo: Photo

    var id: String { "\(album.id)-\(photo.id)" }
}

struct PicMeMyPhotosView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @State private var mode: Mode = .photos
    @State private var selectedItem: MyPhotoItem?
    @State private var gridColumnCount = 3
    @GestureState private var pinchScale: CGFloat = 1

    private enum Mode: String, CaseIterable, Identifiable {
        case photos, albums
        var id: String { rawValue }
        var title: String { self == .photos ? "照片" : "相册" }
    }

    init(initialMode: String = "photos") {
        _mode = State(initialValue: Mode(rawValue: initialMode) ?? .photos)
    }

    private var effectiveGridColumnCount: Int {
        clampedColumnCount(Int((CGFloat(gridColumnCount) / max(pinchScale, 0.45)).rounded()))
    }

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                myHeader
                segmented
                filterChips
                Group {
                    switch mode {
                    case .photos:
                        if myItems.isEmpty {
                            emptyState(icon: "person.crop.square", title: "还没有识别到你的照片", message: "当相册里识别到你后，真实照片会自动出现在这里。")
                                .padding(.horizontal, 20)
                                .padding(.top, 22)
                        } else {
                            photoGrid
                                .padding(.horizontal, 4)
                                .padding(.top, 14)
                        }
                    case .albums:
                        if myAlbums.isEmpty {
                            emptyState(icon: "rectangle.stack.person.crop", title: "暂无相关相册", message: "你出现过的相册会显示真实封面和照片数量。")
                                .padding(.horizontal, 20)
                                .padding(.top, 22)
                        } else {
                            albumList
                                .padding(.horizontal, 20)
                                .padding(.top, 14)
                        }
                    }
                }
                .padding(.bottom, 34)
            }
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .navigationBarHidden(true)
        .simultaneousGesture(gridZoomGesture)
        .fullScreenCover(item: $selectedItem) { item in
            PicMePhotoPreview(album: item.album, photos: myPhotos(in: item.album), initialPhoto: item.photo)
        }
    }

    private var myHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text("我的照片")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("你出现在 \(myItems.count) 张照片 · 横跨 \(myAlbums.count) 个相册")
                    .font(.system(size: 13))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Button {
                Task {
                    await store.savePhotosToSystemPhotos(myItems.map(\.photo))
                }
            } label: {
                glassIcon("arrow.down")
            }
            .buttonStyle(.plain)
            .disabled(myItems.isEmpty)
            .opacity(myItems.isEmpty ? 0.45 : 1)
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
        .frame(minHeight: 54, alignment: .top)
    }

    private var segmented: some View {
        PicMeSegmentedControl(items: Mode.allCases, selection: $mode) { $0.title }
            .padding(.horizontal, 20)
            .padding(.top, 18)
    }

    private var filterChips: some View {
        HStack(spacing: 8) {
            chip("全部", selected: true) {}
        }
        .padding(.horizontal, 20)
        .padding(.top, 14)
    }

    private var photoGrid: some View {
        let spacing: CGFloat = effectiveGridColumnCount <= 3 ? 4 : 2
        let columns = Array(repeating: GridItem(.flexible(), spacing: spacing), count: effectiveGridColumnCount)
        return LazyVGrid(columns: columns, spacing: spacing) {
            ForEach(myItems) { item in
                Button {
                    selectedItem = item
                } label: {
                    GeometryReader { proxy in
                        ZStack(alignment: .topLeading) {
                            PicMeRemoteImage(url: photoURL(item.photo))
                                .frame(width: proxy.size.width, height: proxy.size.height)
                                .clipped()
                            if item.photo.isLivePhoto {
                                picMeBadge("LIVE", color: .black.opacity(0.45))
                                    .padding(effectiveGridColumnCount <= 4 ? 6 : 3)
                                    .scaleEffect(effectiveGridColumnCount <= 4 ? 1 : 0.78, anchor: .topLeading)
                            }
                        }
                    }
                    .aspectRatio(1, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: gridCornerRadius, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .animation(.spring(response: 0.22, dampingFraction: 0.88), value: effectiveGridColumnCount)
    }

    private var gridZoomGesture: some Gesture {
        MagnificationGesture(minimumScaleDelta: 0.015)
            .updating($pinchScale) { value, state, _ in
                state = value
            }
            .onEnded { value in
                let target = clampedColumnCount(Int((CGFloat(gridColumnCount) / max(value, 0.45)).rounded()))
                guard target != gridColumnCount else { return }
                withAnimation(.spring(response: 0.24, dampingFraction: 0.86)) {
                    gridColumnCount = target
                }
            }
    }

    private var gridCornerRadius: CGFloat {
        switch effectiveGridColumnCount {
        case 0...3: return 8
        case 4: return 6
        default: return 3
        }
    }

    private func clampedColumnCount(_ value: Int) -> Int {
        min(7, max(2, value))
    }

    private var albumList: some View {
        VStack(spacing: 10) {
            ForEach(myAlbums) { album in
                NavigationLink(destination: PicMeAlbumDetailView(albumId: album.id)) {
                    albumListRow(album)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var myItems: [MyPhotoItem] {
        myAlbums.flatMap { album in
            myPhotos(in: album).map { MyPhotoItem(album: album, photo: $0) }
        }
    }

    private var myAlbums: [Album] {
        store.albums.filter { !myPhotos(in: $0).isEmpty }
    }

    private func myPhotos(in album: Album) -> [Photo] {
        let explicit = store.myPhotos(in: album)
        if !explicit.isEmpty { return explicit }
        if let folderId = album.myMatchedFolderId {
            let folderPhotos = album.photos
                .filter { $0.allFolderIds.contains(folderId) || $0.folderId == folderId }
                .sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) }
            if !folderPhotos.isEmpty { return folderPhotos }
        }
        return []
    }

    private func photoURL(_ photo: Photo) -> URL? {
        store.imageURL(photo.tinyUrl ?? photo.thumbnailUrl ?? photo.coverUrl ?? photo.previewUrl ?? photo.imageUrl)
    }
}

struct PicMeTransferView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @State private var filter = "全部"
    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 18) {
                Text("传输")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(PicMeStyle.primaryText)
                    .padding(.horizontal, 20)
                    .padding(.top, 14)

                HStack(spacing: 10) {
                    ForEach(["全部", "上传", "下载"], id: \.self) { item in
                        Button { filter = item } label: {
                            Text(item)
                                .font(.system(size: 14, weight: .bold))
                                .foregroundColor(filter == item ? .white : PicMeStyle.secondaryText)
                                .frame(width: 68, height: 36)
                                .background(filter == item ? PicMeStyle.blue : Color(hex: 0xEEF1F6), in: Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 20)

                if store.isUploading, let album = store.albums.first(where: { $0.id == store.uploadAlbumId }) {
                    transferCard(album)
                        .padding(.horizontal, 20)
                } else {
                    emptyTransferState
                        .padding(.horizontal, 20)
                        .padding(.top, 40)
                }
            }
            .padding(.bottom, 120)
        }
        .background(PicMeStyle.background.ignoresSafeArea())
        .navigationBarHidden(true)
    }

    private var emptyTransferState: some View {
        PicMeCard(radius: 20) {
            VStack(spacing: 12) {
                Image(systemName: "arrow.up.arrow.down.circle.fill")
                    .font(.system(size: 48, weight: .bold))
                    .foregroundColor(PicMeStyle.blue)
                Text("暂无传输任务")
                    .font(.headline.weight(.black))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("上传照片后，这里会显示实时进度并支持取消。")
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(PicMeStyle.secondaryText)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(24)
        }
    }

    private func transferCard(_ album: Album) -> some View {
        PicMeCard(radius: 18) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("上传到「\(album.name)」").font(.headline.weight(.black))
                    Spacer()
                    Button { store.cancelCurrentUpload() } label: { Image(systemName: "xmark.circle.fill").foregroundColor(PicMeStyle.secondaryText) }
                }
                ProgressView(value: store.uploadProgressFraction ?? 0).tint(PicMeStyle.blue)
                Text(store.uploadProgressText.isEmpty ? "上传中 · AI 识别同步进行" : store.uploadProgressText)
                    .font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
            }
            .padding(16)
        }
    }
}

struct PicMeProfileView: View {
    @EnvironmentObject private var store: SharePhotosStore
    var onOpenMyPhotos: () -> Void = {}
    var onOpenMyAlbums: () -> Void = {}

    var body: some View {
        PicMeProfileDashboardView(onOpenMyPhotos: onOpenMyPhotos, onOpenMyAlbums: onOpenMyAlbums)
            .environmentObject(store)
            .navigationBarHidden(true)
    }
}

private struct PermissionList: View {
    let permissions: AlbumPermissions
    var body: some View {
        PicMeCard(radius: 16) {
            VStack(spacing: 0) {
                permission("允许上传照片", permissions.upload)
                permission("允许下载照片", permissions.download)
                permission("允许分享相册", permissions.share)
                permission("允许删除照片", permissions.delete)
            }
            .padding(.horizontal, 14)
        }
    }
}

private struct QRPlaceholder: View {
    var body: some View {
        Canvas { context, size in
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white))
            let cell = size.width / 25
            for row in 0..<25 {
                for col in 0..<25 where ((row * 31 + col * 17 + row * col * 7) % 10) < 5 || isFinder(row, col) {
                    context.fill(Path(CGRect(x: CGFloat(col) * cell, y: CGFloat(row) * cell, width: cell * 0.92, height: cell * 0.92)), with: .color(PicMeStyle.primaryText))
                }
            }
        }
    }
    private func isFinder(_ row: Int, _ col: Int) -> Bool {
        func local(_ br: Int, _ bc: Int) -> Bool {
            let rr = row - br, cc = col - bc
            return rr >= 0 && rr <= 6 && cc >= 0 && cc <= 6 && (rr == 0 || rr == 6 || cc == 0 || cc == 6 || (rr >= 2 && rr <= 4 && cc >= 2 && cc <= 4))
        }
        return local(0, 0) || local(0, 18) || local(18, 0)
    }
}

private func albumCover(_ album: Album, height: CGFloat, radius: CGFloat) -> some View {
    PicMeAlbumCover(album: album, height: height, radius: radius)
}

private struct PicMeAlbumCover: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let height: CGFloat
    let radius: CGFloat

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            PicMeRemoteImage(url: coverURL)
            LinearGradient(colors: [.clear, .black.opacity(0.46)], startPoint: .center, endPoint: .bottom)
            PicMeAvatarStack(names: memberNames(album), size: 22)
                .padding(9)
        }
        .frame(height: height)
        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }

    private var coverURL: URL? {
        if let direct = store.imageURL(album.myCoverUrl ?? album.coverUrl ?? album.heroUrl) {
            return direct
        }
        guard let photo = album.photos.first else { return nil }
        return store.imageURL(photo.tinyUrl ?? photo.thumbnailUrl ?? photo.coverUrl ?? photo.previewUrl ?? photo.imageUrl)
    }
}

private func memberNames(_ album: Album) -> [String] {
    let contributors = album.contributors.filter { !$0.isEmpty }
    if !contributors.isEmpty { return contributors }
    return [album.ownerDisplayName]
}

private func albumListRow(_ album: Album) -> some View {
    PicMeCard(radius: 14) {
        HStack(spacing: 12) {
            albumCover(album, height: 58, radius: 12).frame(width: 58)
            VStack(alignment: .leading, spacing: 3) {
                Text(album.name).font(.subheadline.weight(.black)).foregroundColor(PicMeStyle.primaryText)
                Text("你出现在 \(album.myPhotoCount ?? 0) 张").font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundColor(PicMeStyle.secondaryText.opacity(0.55))
        }
        .padding(10)
    }
}

private func sectionTitle(_ title: String, subtitle: String?) -> some View {
    VStack(alignment: .leading, spacing: 3) {
        Text(title).font(.headline.weight(.black)).foregroundColor(PicMeStyle.primaryText)
        if let subtitle { Text(subtitle).font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText) }
    }
}

private func smallStat(_ icon: String, _ value: String) -> some View {
    HStack(spacing: 4) {
        Image(systemName: icon).font(.caption2.weight(.bold))
        Text(value).font(.caption.weight(.bold))
    }
    .foregroundColor(PicMeStyle.secondaryText)
}

private func picMeBadge(_ text: String, color: Color, foreground: Color = .white) -> some View {
    Text(text).font(.caption2.weight(.black)).foregroundColor(foreground).padding(.horizontal, 8).padding(.vertical, 5).background(color, in: Capsule())
}

private func emptyState(icon: String, title: String, message: String) -> some View {
    VStack(spacing: 10) {
        Image(systemName: icon).font(.system(size: 34, weight: .semibold)).foregroundColor(PicMeStyle.blue)
        Text(title).font(.headline.weight(.black)).foregroundColor(PicMeStyle.primaryText)
        Text(message).font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText).multilineTextAlignment(.center)
    }
    .frame(maxWidth: .infinity)
    .padding(24)
    .background(.white.opacity(0.78), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
}

private func statBlock(_ value: String, _ label: String) -> some View {
    VStack(spacing: 3) {
        Text(value).font(.title2.weight(.black)).foregroundColor(PicMeStyle.primaryText)
        Text(label).font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
    }
    .frame(maxWidth: .infinity)
}

private func statCard(_ value: String, _ label: String) -> some View {
    PicMeCard {
        statBlock(value, label).padding(.vertical, 16)
    }
}

private func metricRow(_ icon: String, _ title: String, _ subtitle: String) -> some View {
    HStack(spacing: 12) {
        Image(systemName: icon).foregroundColor(PicMeStyle.blue).frame(width: 42, height: 42).background(PicMeStyle.blue.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.headline.weight(.black)).foregroundColor(PicMeStyle.primaryText)
            Text(subtitle).font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.secondaryText)
        }
        Spacer()
    }
}

private func infoRow(_ icon: String, _ text: String) -> some View {
    HStack(spacing: 10) {
        Image(systemName: icon).foregroundColor(PicMeStyle.secondaryText).frame(width: 18)
        Text(text).font(.caption.weight(.semibold)).foregroundColor(PicMeStyle.primaryText)
    }
}

private func action(_ icon: String, _ label: String, _ action: @escaping () -> Void) -> some View {
    Button(action: action) {
        VStack(spacing: 5) {
            Image(systemName: icon).font(.title3.weight(.semibold))
            Text(label).font(.caption2.weight(.bold))
        }
        .foregroundColor(.white)
        .frame(maxWidth: .infinity)
    }
}

private func chip(_ text: String, selected: Bool, action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Text(text).font(.caption.weight(.black)).foregroundColor(selected ? .white : PicMeStyle.primaryText).padding(.horizontal, 16).padding(.vertical, 8).background(selected ? AnyShapeStyle(PicMeStyle.gradient) : AnyShapeStyle(Color.black.opacity(0.05)), in: Capsule())
    }
    .buttonStyle(.plain)
}

private func settingsRow(_ title: String, icon: String) -> some View {
    HStack(spacing: 12) {
        Image(systemName: icon).foregroundColor(PicMeStyle.blue).frame(width: 32, height: 32).background(PicMeStyle.blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        Text(title).font(.subheadline.weight(.semibold)).foregroundColor(PicMeStyle.primaryText)
        Spacer()
        Image(systemName: "chevron.right").font(.caption.weight(.bold)).foregroundColor(PicMeStyle.secondaryText.opacity(0.55))
    }
    .padding(14)
}

private func permission(_ title: String, _ on: Bool) -> some View {
    HStack {
        Text(title).font(.subheadline.weight(.semibold)).foregroundColor(PicMeStyle.primaryText)
        Spacer()
        Image(systemName: on ? "checkmark.circle.fill" : "xmark.circle.fill").foregroundColor(on ? PicMeStyle.green : PicMeStyle.secondaryText)
    }
    .padding(.vertical, 12)
}

private func permissionSummary(_ permissions: AlbumPermissions) -> String {
    var parts: [String] = []
    if permissions.upload { parts.append("上传") }
    if permissions.download { parts.append("下载") }
    if permissions.share { parts.append("分享") }
    if permissions.delete { parts.append("删除") }
    return parts.isEmpty ? "仅查看" : parts.joined(separator: " · ")
}

private func formatDate(_ timestamp: Int?) -> String {
    guard let timestamp else { return "照片" }
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyy年M月d日 HH:mm"
    return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(timestamp)))
}

private extension View {
    func toastStyle() -> some View {
        self.font(.subheadline.weight(.black)).foregroundColor(.white).padding(.horizontal, 18).padding(.vertical, 11).background(.black.opacity(0.86), in: Capsule()).padding(.bottom, 34)
    }

    @ViewBuilder
    func refreshableCompat(action: @escaping () async -> Void) -> some View {
        if #available(iOS 15.0, *) {
            self.refreshable { await action() }
        } else {
            self
        }
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
