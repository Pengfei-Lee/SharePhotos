import SwiftUI

struct PicMeRootExperience: View {
    @EnvironmentObject private var store: SharePhotosStore
    @State private var activeTab: PicMeTab = .albums
    @State private var createPresented = false
    @State private var messagePresented = false
    @State private var tabBarVisible = true
    @State private var myPhotosInitialMode = "photos"
    @State private var pendingHomeAlbumRoute: String?
    @State private var shareAlbum: Album?

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                switch activeTab {
                case .albums:
                    NavigationView {
                        PicMeHomeView(
                            onMessages: { messagePresented = true },
                            onNavigationDepthChanged: { pushed in tabBarVisible = !pushed },
                            pendingAlbumRoute: $pendingHomeAlbumRoute
                        )
                    }
                        .navigationViewStyle(.stack)
                case .mine:
                    NavigationView { PicMeMyPhotosView(initialMode: myPhotosInitialMode) }
                        .navigationViewStyle(.stack)
                case .transfer:
                    NavigationView { PicMeTransferView() }
                        .navigationViewStyle(.stack)
                case .profile:
                    NavigationView {
                        PicMeProfileView(
                            onOpenMyPhotos: {
                                myPhotosInitialMode = "photos"
                                activeTab = .mine
                            },
                            onOpenMyAlbums: {
                                myPhotosInitialMode = "albums"
                                activeTab = .mine
                            }
                        )
                    }
                        .navigationViewStyle(.stack)
                }
            }

            if tabBarVisible {
                PicMeBottomTabBar(activeTab: $activeTab) {
                    createPresented = true
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .background(PicMeBackground())
        .animation(.spring(response: 0.28, dampingFraction: 0.88), value: tabBarVisible)
        .fullScreenCover(isPresented: $createPresented) {
            PicMeCreateAlbumView(
                onEnterAlbum: { album in
                    activeTab = .albums
                    pendingHomeAlbumRoute = album.id
                },
                onShareAlbum: { album in
                    activeTab = .albums
                    shareAlbum = album
                }
            )
        }
        .fullScreenCover(isPresented: $messagePresented) {
            PicMeMessagesView()
        }
        .fullScreenCover(item: $shareAlbum) { album in
            PicMeShareView(album: album)
        }
        .fullScreenCover(item: $store.pendingDeepLink) { deepLink in
            PicMeJoinView(initialCode: deepLink.code)
        }
        .fullScreenCover(item: $store.pendingPushRoute, onDismiss: {
            store.clearPendingPushRoute()
        }) { route in
            if route.destination == "messages" {
                PicMeMessagesView()
            } else if let albumId = route.albumId {
                NavigationView {
                    if route.destination == "join_requests" {
                        PicMeApprovalsView(albumId: albumId) {
                            store.clearPendingPushRoute()
                        }
                    } else {
                        PicMeAlbumDetailView(albumId: albumId) {
                            store.clearPendingPushRoute()
                        }
                    }
                }
                .navigationViewStyle(.stack)
            } else {
                PicMeMessagesView()
            }
        }
        .fullScreenCover(item: $store.permissionRequestDraft) { draft in
            PicMePermissionRequestView(draft: draft)
        }
        .sheet(item: $store.shareableFile) { file in
            PicMeActivityView(items: [file.url])
        }
        .task {
            await store.loadAlbums()
            await store.loadUnreadMessageCount()
        }
    }
}

private enum PicMeTab: String, CaseIterable, Identifiable {
    case albums
    case mine
    case transfer
    case profile

    var id: String { rawValue }

    var title: String {
        switch self {
        case .albums: return "相册"
        case .mine: return "我的照片"
        case .transfer: return "传输"
        case .profile: return "我的"
        }
    }

    var icon: String {
        switch self {
        case .albums: return "photo"
        case .mine: return "square.grid.2x2"
        case .transfer: return "arrow.up.arrow.down"
        case .profile: return "person"
        }
    }

    var selectedIcon: String {
        switch self {
        case .albums: return "photo.fill"
        case .mine: return "square.grid.2x2.fill"
        case .transfer: return "arrow.up.arrow.down"
        case .profile: return "person.fill"
        }
    }
}

private struct PicMeBottomTabBar: View {
    @Binding var activeTab: PicMeTab
    let onCreate: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            tab(.albums)
            tab(.mine)
            Button(action: onCreate) {
                Image(systemName: "plus")
                    .font(.system(size: 26, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 52, height: 52)
                    .background(PicMeStyle.gradient, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .shadow(color: PicMeStyle.blue.opacity(0.45), radius: 16, y: 6)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity)
            tab(.transfer)
            tab(.profile)
        }
        .padding(.horizontal, 6)
        .padding(.top, 8)
        .padding(.bottom, 8)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 28).stroke(.white.opacity(0.7), lineWidth: 0.5))
        .shadow(color: PicMeStyle.ink.opacity(0.10), radius: 24, y: 6)
        .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 2, y: 1)
        .padding(.horizontal, 12)
        .padding(.bottom, 26)
    }

    private func tab(_ tab: PicMeTab) -> some View {
        Button {
            activeTab = tab
        } label: {
            VStack(spacing: 3) {
                Image(systemName: activeTab == tab ? tab.selectedIcon : tab.icon)
                    .font(.system(size: 23, weight: activeTab == tab ? .semibold : .regular))
                Text(tab.title)
                    .font(.system(size: 10, weight: activeTab == tab ? .semibold : .medium))
            }
            .foregroundColor(activeTab == tab ? PicMeStyle.blue : PicMeStyle.secondaryText)
            .frame(width: 62, height: 55)
        }
        .buttonStyle(.plain)
    }
}
