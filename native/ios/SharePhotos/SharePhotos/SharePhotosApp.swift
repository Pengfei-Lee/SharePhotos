import SwiftUI

@main
struct SharePhotosApp: App {
    @StateObject private var store = SharePhotosStore(
        api: SharePhotosAPI(baseURL: Self.defaultServerURL)
    )

    private static var defaultServerURL: URL {
        #if targetEnvironment(simulator)
        URL(string: "http://localhost:8000")!
        #else
        URL(string: "https://picme.me")!
        #endif
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
