import SwiftUI
import UIKit
import UserNotifications

extension Notification.Name {
    static let picmeDidRegisterAPNSDeviceToken = Notification.Name("picmeDidRegisterAPNSDeviceToken")
    static let picmeDidReceivePushRoute = Notification.Name("picmeDidReceivePushRoute")
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        NotificationCenter.default.post(name: .picmeDidRegisterAPNSDeviceToken, object: token)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        print("PicMe APNs 注册失败: \(error.localizedDescription)")
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        NotificationCenter.default.post(
            name: .picmeDidReceivePushRoute,
            object: response.notification.request.content.userInfo
        )
        completionHandler()
    }
}

@main
struct SharePhotosApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
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
