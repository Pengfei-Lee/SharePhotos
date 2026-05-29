import SwiftUI

@main
struct SharePhotosApp: App {
    @StateObject private var store = SharePhotosStore(
        api: SharePhotosAPI(baseURL: Self.defaultServerURL)
    )

    private static var defaultServerURL: URL {
        URL(string: "https://picme.me")!
    }

    var body: some Scene {
        WindowGroup {
            AuthGateView()
                .environmentObject(store)
                .onOpenURL { url in
                    store.handleIncomingURL(url)
                }
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    if let url = activity.webpageURL {
                        store.handleIncomingURL(url)
                    }
                }
        }
    }
}
