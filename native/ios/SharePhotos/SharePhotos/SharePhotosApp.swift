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
        // 真机测试时这里要填 Mac 的局域网 IP，不能用 localhost。
        URL(string: "http://192.168.3.25:8000")!
        #endif
    }

    var body: some Scene {
        WindowGroup {
            AuthGateView()
                .environmentObject(store)
        }
    }
}
