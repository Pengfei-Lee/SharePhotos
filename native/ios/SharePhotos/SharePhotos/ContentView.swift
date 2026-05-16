import Photos
import PhotosUI
import SwiftUI
import UIKit
import AVFoundation

struct AuthGateView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @State private var mode: AuthMode = .login

    var body: some View {
        ZStack {
            if store.isAuthenticated {
                ContentView()
            } else if store.isCheckingAuth {
                AppBackground()
                VStack(spacing: 16) {
                    PicMeLogo(size: 76)
                    ProgressView("正在确认登录状态")
                        .font(.headline.weight(.semibold))
                        .tint(.teal)
                }
            } else {
                switch mode {
                case .login:
                    LoginView {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            mode = .register
                        }
                    }
                case .register:
                    RegisterView {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            mode = .login
                        }
                    }
                }
            }
        }
        .task {
            await store.loadMe()
            if store.isAuthenticated {
                await store.loadAlbums()
            }
        }
        .preferredColorScheme(.light)
        .tint(.teal)
    }
}

private enum AuthMode {
    case login
    case register
}

private struct LoginView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let onCreateAccount: () -> Void
    @State private var username = ""
    @State private var password = ""
    @State private var isPasswordVisible = false

    private var canSubmit: Bool {
        !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !password.isEmpty && !store.isBusy
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                Spacer(minLength: 32)

                VStack(spacing: 14) {
                    PicMeLogo(size: 88)
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text("识我")
                            .font(.system(size: 34, weight: .black))
                            .foregroundColor(.primaryText)
                        Text("PicMe")
                            .font(.system(size: 30, weight: .bold))
                            .foregroundStyle(LinearGradient(colors: [.picmeAqua, .picmeViolet], startPoint: .leading, endPoint: .trailing))
                    }
                    Text("自动找到属于你的旅行照片")
                        .font(.headline)
                        .foregroundColor(.secondaryText)
                }
                .padding(.top, 22)

                VStack(alignment: .leading, spacing: 20) {
                    Text("登录")
                        .font(.system(size: 32, weight: .black))
                        .foregroundColor(.primaryText)

                    AuthInputField(
                        icon: "person",
                        placeholder: "登录账号",
                        text: $username,
                        keyboardType: .asciiCapable,
                        isSecure: false
                    )

                    AuthInputField(
                        icon: "lock",
                        placeholder: "密码",
                        text: $password,
                        keyboardType: .default,
                        isSecure: !isPasswordVisible,
                        trailingIcon: isPasswordVisible ? "eye.slash" : "eye"
                    ) {
                        isPasswordVisible.toggle()
                    }

                    Button("忘记密码？") {}
                        .font(.subheadline.weight(.bold))
                        .foregroundColor(.teal)
                        .frame(maxWidth: .infinity, alignment: .trailing)

                    Button {
                        Task { await store.login(username: username, password: password) }
                    } label: {
                        Text(store.isBusy ? "登录中..." : "登录")
                            .font(.title3.weight(.bold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 18)
                            .background(primaryGradient, in: Capsule())
                            .foregroundColor(.white)
                            .shadow(color: .teal.opacity(0.25), radius: 18, y: 8)
                    }
                    .disabled(!canSubmit)
                    .opacity(canSubmit ? 1 : 0.55)
                    .padding(.top, 18)
                }

                HStack(spacing: 16) {
                    Rectangle().fill(Color.secondary.opacity(0.18)).frame(height: 1)
                    Text("还没有账号？")
                        .font(.subheadline.weight(.semibold))
                        .foregroundColor(.secondaryText)
                    Rectangle().fill(Color.secondary.opacity(0.18)).frame(height: 1)
                }
                .padding(.top, 26)

                Button(action: onCreateAccount) {
                    Text("创建新账号")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 17)
                        .background(.white.opacity(0.72), in: Capsule())
                        .overlay(Capsule().stroke(Color.teal, lineWidth: 1.4))
                        .foregroundColor(.teal)
                }

                Text("登录即代表同意《用户协议》和《隐私政策》")
                    .font(.footnote.weight(.semibold))
                    .foregroundColor(.secondaryText)
                    .padding(.top, 12)

                AuthStatusText()
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 32)
        }
        .background(AppBackground())
    }
}

private struct RegisterView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let onLogin: () -> Void
    @State private var nickname = ""
    @State private var username = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var isPasswordVisible = false
    @State private var isConfirmPasswordVisible = false
    @State private var avatarPickerPresented = false
    @State private var avatarData: Data?
    @State private var avatarImage: UIImage?

    private var canSubmit: Bool {
        !nickname.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && isValidUsername(username)
            && isValidPasswordFormat(password)
            && password == confirmPassword
            && !store.isBusy
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack {
                    Button(action: onLogin) {
                        Image(systemName: "chevron.left")
                            .font(.title2.weight(.semibold))
                            .foregroundColor(.primaryText)
                            .frame(width: 44, height: 44)
                    }
                    Spacer()
                    Text("创建新账号")
                        .font(.title3.weight(.black))
                        .foregroundColor(.primaryText)
                    Spacer()
                    Color.clear.frame(width: 44, height: 44)
                }
                .padding(.top, 16)

                VStack(alignment: .leading, spacing: 8) {
                    Text("推荐上传头像")
                        .font(.title2.weight(.black))
                    Text("上传清晰的头像，有助于我们更准确地识别你，更好地为你匹配专属相册")
                        .font(.subheadline)
                        .foregroundColor(.secondaryText)
                        .lineSpacing(4)
                }

                Button {
                    avatarPickerPresented = true
                } label: {
                    ZStack(alignment: .bottomTrailing) {
                        Group {
                            if let avatarImage {
                                Image(uiImage: avatarImage)
                                    .resizable()
                                    .aspectRatio(contentMode: .fill)
                            } else {
                                ZStack {
                                    Circle()
                                        .fill(Color.teal.opacity(0.12))
                                    Image(systemName: "person.fill")
                                        .font(.system(size: 54, weight: .medium))
                                        .foregroundColor(.teal.opacity(0.45))
                                }
                            }
                        }
                        .frame(width: 140, height: 140)
                        .clipShape(Circle())
                        .overlay(Circle().stroke(.white, lineWidth: 4))
                        .shadow(color: .teal.opacity(0.12), radius: 18, y: 8)

                        Image(systemName: "camera.fill")
                            .font(.title3.weight(.bold))
                            .foregroundColor(.white)
                            .frame(width: 48, height: 48)
                            .background(Color.teal, in: Circle())
                            .overlay(Circle().stroke(.white, lineWidth: 4))
                            .shadow(color: .black.opacity(0.12), radius: 10, y: 5)
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)

                VStack(spacing: 14) {
                    AuthInputField(icon: "person", placeholder: "昵称（将显示在相册中）", text: $nickname, keyboardType: .default, isSecure: false)
                    AuthInputField(icon: "person", placeholder: "登录账号", text: $username, keyboardType: .asciiCapable, isSecure: false)
                    Text("1-20位，支持字母、数字、下划线")
                        .authHelpStyle()
                    AuthInputField(
                        icon: "lock",
                        placeholder: "密码",
                        text: $password,
                        keyboardType: .default,
                        isSecure: !isPasswordVisible,
                        trailingIcon: isPasswordVisible ? "eye.slash" : "eye"
                    ) {
                        isPasswordVisible.toggle()
                    }
                    Text(passwordHelpText)
                        .authHelpStyle(isWarning: !password.isEmpty && !isValidPasswordFormat(password))
                    AuthInputField(
                        icon: "lock",
                        placeholder: "确认密码",
                        text: $confirmPassword,
                        keyboardType: .default,
                        isSecure: !isConfirmPasswordVisible,
                        trailingIcon: isConfirmPasswordVisible ? "eye.slash" : "eye"
                    ) {
                        isConfirmPasswordVisible.toggle()
                    }
                    Text(confirmPasswordHelpText)
                        .authHelpStyle(isWarning: !confirmPassword.isEmpty && password != confirmPassword)
                }

                Button {
                    Task {
                        let didRegister = await store.register(
                            username: username,
                            nickname: nickname,
                            password: password,
                            confirmPassword: confirmPassword,
                            avatarData: avatarData
                        )
                        if didRegister {
                            avatarPickerPresented = false
                        }
                    }
                } label: {
                    Text(store.isBusy ? "注册中..." : "注册")
                        .font(.title3.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 18)
                        .background(primaryGradient, in: Capsule())
                        .foregroundColor(.white)
                        .shadow(color: .teal.opacity(0.25), radius: 18, y: 8)
                }
                .disabled(!canSubmit)
                .opacity(canSubmit ? 1 : 0.55)
                .padding(.top, 8)

                Button(action: onLogin) {
                    HStack(spacing: 5) {
                        Text("已有账号？")
                            .foregroundColor(.secondaryText)
                        Text("立即登录")
                            .foregroundColor(.blue)
                    }
                    .font(.subheadline.weight(.bold))
                    .frame(maxWidth: .infinity)
                }

                AuthStatusText()
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 34)
        }
        .background(AppBackground())
        .sheet(isPresented: $avatarPickerPresented) {
            AvatarImagePicker { image, data in
                avatarImage = image
                avatarData = data
            }
        }
    }

    private func isValidUsername(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (1...20).contains(trimmed.count) else { return false }
        return trimmed.range(of: #"^[A-Za-z0-9_]+$"#, options: .regularExpression) != nil
    }

    private var passwordHelpText: String {
        guard !password.isEmpty else { return "6-20位，可使用数字、字母和英文符号" }
        return isValidPasswordFormat(password) ? "密码格式可用" : "密码需为 6-20 位，且不能包含中文、空格或中文符号"
    }

    private var confirmPasswordHelpText: String {
        guard !confirmPassword.isEmpty else { return "请再次输入密码" }
        guard isValidPasswordFormat(confirmPassword) else { return "确认密码格式不正确" }
        return password == confirmPassword ? "两次密码一致" : "两次输入的密码不一致"
    }

    private func isValidPasswordFormat(_ value: String) -> Bool {
        guard (6...20).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy { (0x21...0x7E).contains($0.value) }
    }
}

private struct AvatarImagePicker: UIViewControllerRepresentable {
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

            if provider.canLoadObject(ofClass: UIImage.self) {
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
            } else {
                dismiss()
            }
        }
    }
}

private struct AuthInputField: View {
    let icon: String
    let placeholder: String
    @Binding var text: String
    let keyboardType: UIKeyboardType
    let isSecure: Bool
    var trailingIcon: String?
    var trailingAction: (() -> Void)?

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.headline.weight(.semibold))
                .foregroundColor(.secondaryText)
                .frame(width: 22)
            Group {
                if isSecure {
                    SecureField(placeholder, text: $text)
                } else {
                    TextField(placeholder, text: $text)
                }
            }
            .keyboardType(keyboardType)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .font(.headline.weight(.semibold))
            .foregroundColor(.primaryText)

            if let trailingIcon, let trailingAction {
                Button(action: trailingAction) {
                    Image(systemName: trailingIcon)
                        .font(.headline.weight(.semibold))
                        .foregroundColor(.secondaryText)
                }
            }
        }
        .padding(.horizontal, 16)
        .frame(height: 60)
        .background(.white.opacity(0.74), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.secondary.opacity(0.2), lineWidth: 1))
    }
}

private struct AuthStatusText: View {
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        if !store.statusText.isEmpty {
            Text(store.statusText)
                .font(.footnote.weight(.semibold))
                .foregroundColor(.secondaryText)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @State private var createAlbumPresented = false

    var body: some View {
        ZStack(alignment: .top) {
            NavigationView {
                HomeView(createAlbumPresented: $createAlbumPresented)
                    .navigationBarHidden(true)
            }
            .navigationViewStyle(.stack)

            if store.showsOperation {
                OperationHUD()
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .zIndex(10)
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.86), value: store.showsOperation)
        .task {
            await store.loadAlbums()
        }
        .sheet(isPresented: $createAlbumPresented) {
            CreateAlbumSheet()
        }
        .sheet(isPresented: $store.isServerSettingsPresented) {
            ServerSettingsSheet()
        }
        .sheet(item: $store.shareableFile) { file in
            ActivityView(items: [file.url])
        }
        .preferredColorScheme(.light)
        .tint(.teal)
    }
}

private struct HomeView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Binding var createAlbumPresented: Bool
    @State private var deletingAlbum: Album?
    @State private var renamingAlbum: Album?

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    HStack(alignment: .top) {
                        BrandHeader()
                        Spacer()
                        AccountMenu()
                    }
                    .padding(.top, 24)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("相册")
                            .font(.system(size: 38, weight: .black))
                        Text(store.albums.isEmpty ? "暂无相册" : "\(store.albums.count) 个一级相册")
                            .font(.headline)
                            .foregroundColor(.secondary)
                    }

                    if store.albums.isEmpty {
                        EmptyAlbumState()
                    } else {
                        VStack(spacing: 16) {
                            ForEach(store.albums) { album in
                                NavigationLink {
                                    AlbumDetailView(albumId: album.id)
                                } label: {
                                    AlbumCard(album: album)
                                }
                                .buttonStyle(.plain)
                                .contextMenu {
                                    Button {
                                        renamingAlbum = album
                                    } label: {
                                        Label("重命名相册", systemImage: "pencil")
                                    }
                                    Button(role: .destructive) {
                                        deletingAlbum = album
                                    } label: {
                                        Label("删除相册", systemImage: "trash")
                                    }
                                }
                            }
                        }
                    }

                    Text(store.statusText)
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    ServerStatusRow()
                        .padding(.bottom, 112)
                }
                .padding(.horizontal, 18)
            }

            Button {
                createAlbumPresented = true
            } label: {
                Label("创建新相册", systemImage: "plus")
                    .font(.headline.weight(.bold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 18)
                    .background(primaryGradient, in: Capsule())
                    .foregroundColor(.white)
                    .shadow(color: .teal.opacity(0.25), radius: 18, y: 8)
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 22)
        }
        .background(AppBackground())
        .alert("删除这个共享相册？", isPresented: Binding(
            get: { deletingAlbum != nil },
            set: { if !$0 { deletingAlbum = nil } }
        )) {
            Button("取消", role: .cancel) { deletingAlbum = nil }
            Button("删除", role: .destructive) {
                if let deletingAlbum {
                    Task { await store.deleteAlbum(deletingAlbum) }
                }
                deletingAlbum = nil
            }
        } message: {
            Text("会删除这个一级相册里的所有照片和分类。")
        }
        .sheet(item: $renamingAlbum) { album in
            RenameAlbumSheet(album: album)
        }
    }
}

private struct ServerStatusRow: View {
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        Button {
            store.isServerSettingsPresented = true
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "wifi.router")
                    .font(.headline)
                    .foregroundColor(.teal)
                VStack(alignment: .leading, spacing: 3) {
                    Text("服务地址")
                        .font(.caption.weight(.bold))
                        .foregroundColor(.secondaryText)
                    Text(store.serverAddress)
                        .font(.footnote.weight(.semibold))
                        .foregroundColor(.primaryText)
                        .lineLimit(1)
                }
                Spacer()
                Text("修改")
                    .font(.footnote.weight(.bold))
                    .foregroundColor(.teal)
            }
            .padding(14)
            .background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(.teal.opacity(0.12)))
        }
        .buttonStyle(.plain)
    }
}

private struct ServerSettingsSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var isSaving = false

    private var trimmedAddress: String {
        address.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 18) {
                Text("手机真机不能访问 Mac 的 localhost。请填写 Mac 当前局域网地址，格式类似 http://192.168.3.25:8000。")
                    .font(.subheadline)
                    .foregroundColor(.secondaryText)
                    .lineSpacing(4)

                TextField("http://192.168.3.25:8000", text: $address)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.body.weight(.semibold))
                    .padding(16)
                    .background(.white, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16).stroke(.teal.opacity(0.18)))

                Button {
                    Task {
                        isSaving = true
                        let didConnect = await store.updateServerAddress(address)
                        isSaving = false
                        if didConnect {
                            dismiss()
                        }
                    }
                } label: {
                    Text(isSaving ? "连接中..." : "保存并重连")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(primaryGradient, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .foregroundColor(.white)
                }
                .disabled(trimmedAddress.isEmpty || isSaving)
                .opacity(trimmedAddress.isEmpty || isSaving ? 0.55 : 1)

                Button {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        UIApplication.shared.open(url)
                    }
                } label: {
                    Label("检查本地网络权限", systemImage: "gearshape")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.teal.opacity(0.1), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .foregroundColor(.teal)
                }

                Text("如果 Safari 能打开同一个地址，但 App 不能连，通常是 iOS 的“本地网络”权限没打开。")
                    .font(.footnote)
                    .foregroundColor(.secondaryText)

                Spacer()
            }
            .padding(20)
            .background(AppBackground())
            .navigationTitle("服务连接")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") { dismiss() }
                }
            }
            .onAppear {
                address = store.serverAddress
            }
        }
    }
}

private struct AlbumDetailView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var uploadPresented = false
    @State private var deletingFolder: PhotoFolder?
    @State private var renamingFolder: PhotoFolder?

    var album: Album? { store.album(id: albumId) }

    var body: some View {
        ScrollView {
            if let album {
                VStack(alignment: .leading, spacing: 22) {
                    BackButton { dismiss() }

                    AlbumHero(album: album)

                    MyPhotosRecommendationCard(album: album)

                    VStack(alignment: .leading, spacing: 8) {
                        Text("按人打包带走")
                            .font(.system(size: 32, weight: .black))
                        Text("\(album.folders.count) 个可下载小相册")
                            .font(.headline)
                            .foregroundColor(.secondary)
                    }

                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)], spacing: 14) {
                        ForEach(album.folders) { folder in
                            NavigationLink {
                                FolderDetailView(albumId: album.id, folderId: folder.id)
                            } label: {
                                FolderCard(album: album, folder: folder, compact: true)
                            }
                            .buttonStyle(.plain)
                            .contextMenu {
                                Button {
                                    renamingFolder = folder
                                } label: {
                                    Label("重命名小相册", systemImage: "pencil")
                                }
                                Button {
                                    Task { await store.downloadFolder(album: album, folder: folder) }
                                } label: {
                                    Label("下载照片包", systemImage: "square.and.arrow.down")
                                }
                                Button(role: .destructive) {
                                    deletingFolder = folder
                                } label: {
                                    Label("删除小相册", systemImage: "trash")
                                }
                            }
                            .overlay(alignment: .topTrailing) {
                                FolderMenu(
                                    album: album,
                                    folder: folder,
                                    onRename: { renamingFolder = folder },
                                    onDelete: { deletingFolder = folder }
                                )
                                    .padding(10)
                            }
                        }
                    }
                    if album.folders.isEmpty {
                        EmptyContentState(
                            systemImage: "person.2.crop.square.stack",
                            title: "还没有人物小相册",
                            message: album.photos.isEmpty ? "先上传照片，后台整理完成后会自动生成小相册。" : "照片还在整理中，稍后刷新就能看到人物小相册。"
                        )
                    }

                    Button {
                        store.selectAlbum(id: album.id)
                        uploadPresented = true
                    } label: {
                        Label("上传照片", systemImage: "photo.badge.plus")
                            .font(.headline.weight(.bold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 18)
                            .background(primaryGradient, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                            .foregroundColor(.white)
                    }
                    .disabled(store.isBusy)
                    .opacity(store.isBusy ? 0.55 : 1)

                    NavigationLink {
                        AllPhotosView(albumId: album.id)
                    } label: {
                        VStack(spacing: 6) {
                            Text("查看所有照片")
                                .font(.title3.weight(.bold))
                            Text("\(album.photos.count) 张原始上传，点开看大图")
                                .font(.subheadline.weight(.semibold))
                                .foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 22)
                        .background(.white.opacity(0.85), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.teal.opacity(0.18)))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 18)
            } else {
                ProgressView("正在打开相册")
                    .padding(40)
            }
        }
        .background(AppBackground())
        .navigationBarHidden(true)
        .edgeSwipeBack { dismiss() }
        .task {
            store.selectAlbum(id: albumId)
            await store.refreshAlbum(id: albumId)
        }
        .sheet(isPresented: $uploadPresented) {
            UploadSheet(albumId: albumId)
        }
        .sheet(item: $renamingFolder) { folder in
            if let album {
                RenameFolderSheet(album: album, folder: folder)
            }
        }
        .alert("删除这个小相册？", isPresented: Binding(
            get: { deletingFolder != nil },
            set: { if !$0 { deletingFolder = nil } }
        )) {
            Button("取消", role: .cancel) { deletingFolder = nil }
            Button("删除", role: .destructive) {
                if let album, let deletingFolder {
                    Task { await store.deleteFolder(album: album, folder: deletingFolder) }
                }
                deletingFolder = nil
            }
        } message: {
            Text("会按 H5 规则删除这个子相册里的照片；合照仍会保留在其他人的小相册中。")
        }
    }
}

private struct FolderDetailView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var selectedPhoto: Photo?
    @State private var gridColumnCount = 3
    @State private var gridZoomScale: CGFloat = 1
    @State private var activeFolderId: String
    @State private var isSelecting = false
    @State private var selectedPhotoIds = Set<String>()
    @State private var selectionActionsPresented = false

    init(albumId: String, folderId: String) {
        self.albumId = albumId
        _activeFolderId = State(initialValue: folderId)
    }

    var album: Album? { store.album(id: albumId) }
    var folder: PhotoFolder? { store.folder(albumId: albumId, folderId: activeFolderId) }
    var photos: [Photo] {
        guard let album, let folder else { return [] }
        return store.photos(in: album, folder: folder)
    }
    var selectedPhotos: [Photo] {
        photos.filter { selectedPhotoIds.contains($0.id) }
    }

    var body: some View {
        ZStack {
            ScrollView {
                if let album {
                    VStack(alignment: .leading, spacing: 18) {
                        BackButton { dismiss() }
                            .padding(.horizontal, 18)
                        FolderSwitcher(album: album, currentFolderId: $activeFolderId)
                            .padding(.horizontal, 18)
                        SelectionTopBar(
                            isSelecting: $isSelecting,
                            selectedPhotoIds: $selectedPhotoIds,
                            photos: photos
                        )
                        .padding(.horizontal, 18)
                        Text("\(photos.count) 张照片")
                            .font(.system(size: 42, weight: .black))
                            .foregroundColor(.secondary)
                            .padding(.horizontal, 18)
                        if photos.isEmpty {
                            EmptyContentState(
                                systemImage: "photo",
                                title: "这个小相册暂时为空",
                                message: "照片可能还在整理，或已被移动到其他小相册。"
                            )
                            .padding(.horizontal, 18)
                        } else {
                            PhotoLibraryGrid(
                                album: album,
                                photos: photos,
                                columnCount: $gridColumnCount,
                                zoomScale: gridZoomScale,
                                selectedPhoto: $selectedPhoto,
                                isSelecting: isSelecting,
                                selectedPhotoIds: $selectedPhotoIds
                            )
                        }
                    }
                    .padding(.vertical, 18)
                }
            }

            if let photo = selectedPhoto {
                PhotoViewer(albumId: albumId, photos: photos, initialPhotoId: photo.id) {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.9)) {
                        selectedPhoto = nil
                    }
                }
                .transition(.scale(scale: 0.94, anchor: .center).combined(with: .opacity))
                .zIndex(10)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if isSelecting {
                SelectionBottomBar(
                    count: selectedPhotoIds.count,
                    onDelete: {
                        guard let album else { return }
                        Task {
                            await store.deletePhotos(album: album, photos: selectedPhotos)
                            selectedPhotoIds.removeAll()
                            isSelecting = false
                        }
                    },
                    onMore: { selectionActionsPresented = true }
                )
            }
        }
        .background(AppBackground())
        .navigationBarHidden(true)
        .edgeSwipeBack { dismiss() }
        .photoGridZoom(columnCount: $gridColumnCount, zoomScale: $gridZoomScale)
        .onChange(of: activeFolderId) { _ in
            selectedPhotoIds.removeAll()
            isSelecting = false
        }
        .task {
            await store.refreshAlbum(id: albumId)
            if let album, !album.folders.contains(where: { $0.id == activeFolderId }), let first = album.folders.first {
                activeFolderId = first.id
            }
        }
        .confirmationDialog("操作所选照片", isPresented: $selectionActionsPresented, titleVisibility: .visible) {
            if let album {
                Button("保存到系统相册") {
                    Task { await store.savePhotosToSystemPhotos(selectedPhotos) }
                }
                Button("下载照片包") {
                    Task { await store.downloadSelectedPackage(album: album, photos: selectedPhotos) }
                }
                ForEach(album.folders.filter { $0.id != activeFolderId }) { folder in
                    Button("移动到 \(folder.name)") {
                        Task {
                            await store.movePhotos(album: album, photos: selectedPhotos, targetFolder: folder)
                            selectedPhotoIds.removeAll()
                            isSelecting = false
                        }
                    }
                }
                Button("删除所选", role: .destructive) {
                    Task {
                        await store.deletePhotos(album: album, photos: selectedPhotos)
                        selectedPhotoIds.removeAll()
                        isSelecting = false
                    }
                }
            }
            Button("取消", role: .cancel) {}
        }
    }
}

private struct AllPhotosView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var limit = 16
    @State private var selectedPhoto: Photo?
    @State private var gridColumnCount = 3
    @State private var gridZoomScale: CGFloat = 1
    @State private var isSelecting = false
    @State private var selectedPhotoIds = Set<String>()
    @State private var selectionActionsPresented = false

    var album: Album? { store.album(id: albumId) }
    var visiblePhotos: [Photo] {
        Array((album?.photos.sorted { ($0.createdAt ?? 0) > ($1.createdAt ?? 0) } ?? []).prefix(limit))
    }
    var selectedPhotos: [Photo] {
        visiblePhotos.filter { selectedPhotoIds.contains($0.id) }
    }

    var body: some View {
        ZStack {
            ScrollView {
                if let album {
                    VStack(alignment: .leading, spacing: 18) {
                        BackButton { dismiss() }
                            .padding(.horizontal, 18)
                        SelectionTopBar(
                            isSelecting: $isSelecting,
                            selectedPhotoIds: $selectedPhotoIds,
                            photos: visiblePhotos
                        )
                        .padding(.horizontal, 18)
                        Text("\(album.photos.count) 张照片")
                            .font(.system(size: 42, weight: .black))
                            .foregroundColor(.secondary)
                            .padding(.horizontal, 18)
                        if album.photos.isEmpty {
                            EmptyContentState(
                                systemImage: "photo.stack",
                                title: "还没有上传照片",
                                message: "返回相册详情，点上传照片添加朋友视角。"
                            )
                            .padding(.horizontal, 18)
                        } else {
                            PhotoLibraryGrid(
                                album: album,
                                photos: visiblePhotos,
                                columnCount: $gridColumnCount,
                                zoomScale: gridZoomScale,
                                selectedPhoto: $selectedPhoto,
                                isSelecting: isSelecting,
                                selectedPhotoIds: $selectedPhotoIds
                            )
                        }
                        if limit < album.photos.count {
                            ProgressView()
                                .frame(maxWidth: .infinity)
                                .onAppear {
                                    limit = min(limit + 12, album.photos.count)
                                }
                        }
                    }
                    .padding(.vertical, 18)
                }
            }

            if let photo = selectedPhoto {
                PhotoViewer(albumId: albumId, photos: visiblePhotos, initialPhotoId: photo.id) {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.9)) {
                        selectedPhoto = nil
                    }
                }
                .transition(.scale(scale: 0.94, anchor: .center).combined(with: .opacity))
                .zIndex(10)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if isSelecting {
                SelectionBottomBar(
                    count: selectedPhotoIds.count,
                    onDelete: {
                        guard let album else { return }
                        Task {
                            await store.deletePhotos(album: album, photos: selectedPhotos)
                            selectedPhotoIds.removeAll()
                            isSelecting = false
                        }
                    },
                    onMore: { selectionActionsPresented = true }
                )
            }
        }
        .background(AppBackground())
        .navigationBarHidden(true)
        .edgeSwipeBack { dismiss() }
        .photoGridZoom(columnCount: $gridColumnCount, zoomScale: $gridZoomScale)
        .task { await store.refreshAlbum(id: albumId) }
        .confirmationDialog("操作所选照片", isPresented: $selectionActionsPresented, titleVisibility: .visible) {
            if let album {
                Button("保存到系统相册") {
                    Task { await store.savePhotosToSystemPhotos(selectedPhotos) }
                }
                Button("下载照片包") {
                    Task { await store.downloadSelectedPackage(album: album, photos: selectedPhotos) }
                }
                Button("删除所选", role: .destructive) {
                    Task {
                        await store.deletePhotos(album: album, photos: selectedPhotos)
                        selectedPhotoIds.removeAll()
                        isSelecting = false
                    }
                }
            }
            Button("取消", role: .cancel) {}
        }
    }
}

private struct MyPhotosView: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var selectedPhoto: Photo?
    @State private var gridColumnCount = 3
    @State private var gridZoomScale: CGFloat = 1
    @State private var isSelecting = false
    @State private var selectedPhotoIds = Set<String>()
    @State private var selectionActionsPresented = false

    var album: Album? { store.album(id: albumId) }
    var photos: [Photo] {
        guard let album else { return [] }
        return store.myPhotos(in: album)
    }
    var selectedPhotos: [Photo] {
        photos.filter { selectedPhotoIds.contains($0.id) }
    }

    var body: some View {
        ZStack {
            ScrollView {
                if let album {
                    VStack(alignment: .leading, spacing: 18) {
                        BackButton { dismiss() }
                            .padding(.horizontal, 18)
                        SelectionTopBar(
                            isSelecting: $isSelecting,
                            selectedPhotoIds: $selectedPhotoIds,
                            photos: photos
                        )
                        .padding(.horizontal, 18)
                        VStack(alignment: .leading, spacing: 6) {
                            Text("我的照片")
                                .font(.system(size: 42, weight: .black))
                                .foregroundColor(.primaryText)
                            Text("\(photos.count) 张由头像匹配到的照片")
                                .font(.headline)
                                .foregroundColor(.secondaryText)
                        }
                        .padding(.horizontal, 18)

                        if photos.isEmpty {
                            EmptyContentState(
                                systemImage: "person.crop.circle.badge.questionmark",
                                title: "暂时没有匹配到你的照片",
                                message: currentUserHasFaceProfile ? "可以稍后刷新，或换一张更清晰的正脸头像重新注册。" : "你还没有可用于识别的人脸头像，所以暂时不能推荐我的照片。"
                            )
                            .padding(.horizontal, 18)
                        } else {
                            PhotoLibraryGrid(
                                album: album,
                                photos: photos,
                                columnCount: $gridColumnCount,
                                zoomScale: gridZoomScale,
                                selectedPhoto: $selectedPhoto,
                                isSelecting: isSelecting,
                                selectedPhotoIds: $selectedPhotoIds
                            )
                        }
                    }
                    .padding(.vertical, 18)
                }
            }

            if let photo = selectedPhoto {
                PhotoViewer(albumId: albumId, photos: photos, initialPhotoId: photo.id) {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.9)) {
                        selectedPhoto = nil
                    }
                }
                .transition(.scale(scale: 0.94, anchor: .center).combined(with: .opacity))
                .zIndex(10)
            }
        }
        .safeAreaInset(edge: .bottom) {
            if isSelecting {
                SelectionBottomBar(
                    count: selectedPhotoIds.count,
                    onDelete: {
                        guard let album else { return }
                        Task {
                            await store.deletePhotos(album: album, photos: selectedPhotos)
                            selectedPhotoIds.removeAll()
                            isSelecting = false
                        }
                    },
                    onMore: { selectionActionsPresented = true }
                )
            }
        }
        .background(AppBackground())
        .navigationBarHidden(true)
        .edgeSwipeBack { dismiss() }
        .photoGridZoom(columnCount: $gridColumnCount, zoomScale: $gridZoomScale)
        .task { await store.refreshAlbum(id: albumId) }
        .confirmationDialog("操作所选照片", isPresented: $selectionActionsPresented, titleVisibility: .visible) {
            if let album {
                Button("保存到系统相册") {
                    Task { await store.savePhotosToSystemPhotos(selectedPhotos) }
                }
                Button("下载照片包") {
                    Task { await store.downloadSelectedPackage(album: album, photos: selectedPhotos) }
                }
                Button("删除所选", role: .destructive) {
                    Task {
                        await store.deletePhotos(album: album, photos: selectedPhotos)
                        selectedPhotoIds.removeAll()
                        isSelecting = false
                    }
                }
            }
            Button("取消", role: .cancel) {}
        }
    }

    private var currentUserHasFaceProfile: Bool {
        store.currentUser?.hasFaceProfile == true
    }
}

private struct CreateAlbumSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 18) {
                Text("这次出游叫什么")
                    .font(.title.weight(.black))
                TextField("例如：重庆周末小队", text: $name)
                    .font(.title3.weight(.semibold))
                    .padding(16)
                    .background(.white, in: RoundedRectangle(cornerRadius: 16))
                Button {
                    Task {
                        if await store.createAlbum(name: name) != nil {
                            dismiss()
                        }
                    }
                } label: {
                    Text("创建")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(primaryGradient, in: RoundedRectangle(cornerRadius: 16))
                        .foregroundColor(.white)
                }
                .disabled(trimmedName.isEmpty || store.isBusy)
                .opacity(trimmedName.isEmpty || store.isBusy ? 0.55 : 1)
                Spacer()
            }
            .padding(22)
            .background(AppBackground())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
        }
    }
}

private struct RenameAlbumSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let album: Album
    @State private var name: String

    init(album: Album) {
        self.album = album
        _name = State(initialValue: album.name)
    }

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        RenameNameSheet(
            title: "重命名相册",
            placeholder: "相册名称",
            name: $name,
            isSavingDisabled: trimmedName.isEmpty || store.isBusy
        ) {
            Task {
                await store.renameAlbum(album, name: name)
                dismiss()
            }
        }
    }
}

private struct RenameFolderSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let album: Album
    let folder: PhotoFolder
    @State private var name: String

    init(album: Album, folder: PhotoFolder) {
        self.album = album
        self.folder = folder
        _name = State(initialValue: folder.name)
    }

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        RenameNameSheet(
            title: "重命名小相册",
            placeholder: "小相册名称",
            name: $name,
            isSavingDisabled: trimmedName.isEmpty || store.isBusy
        ) {
            Task {
                await store.renameFolder(album: album, folder: folder, name: name)
                dismiss()
            }
        }
    }
}

private struct RenameNameSheet: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    let placeholder: String
    @Binding var name: String
    let isSavingDisabled: Bool
    let onSave: () -> Void

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 18) {
                Text(title)
                    .font(.title.weight(.black))
                TextField(placeholder, text: $name)
                    .font(.title3.weight(.semibold))
                    .padding(16)
                    .background(.white, in: RoundedRectangle(cornerRadius: 16))
                Button(action: onSave) {
                    Text("保存")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(primaryGradient, in: RoundedRectangle(cornerRadius: 16))
                        .foregroundColor(.white)
                }
                .disabled(isSavingDisabled)
                .opacity(isSavingDisabled ? 0.55 : 1)
                Spacer()
            }
            .padding(22)
            .background(AppBackground())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
        }
    }
}

private struct UploadSheet: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    @State private var pickerPresented = false

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 20) {
                Text("把手机里的朋友视角加进来")
                    .font(.title.weight(.black))
                TextField("不填写则默认为访客", text: $store.uploader)
                    .padding(16)
                    .background(.white, in: RoundedRectangle(cornerRadius: 16))

                Button {
                    pickerPresented = true
                } label: {
                    Label("从系统相册选择照片或 Live Photo", systemImage: "photo.on.rectangle.angled")
                        .font(.headline.weight(.bold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 18)
                        .background(primaryGradient, in: RoundedRectangle(cornerRadius: 18))
                        .foregroundColor(.white)
                }
                .disabled(store.isBusy)
                .opacity(store.isBusy ? 0.55 : 1)

                if store.uploadSelectedCount > 0 || !store.uploadProgressText.isEmpty {
                    UploadProgressPanel()
                }
                Text("手机上可以一次多选；上传后先入库，再由后台生成预览和人物小相册。")
                    .font(.footnote)
                    .foregroundColor(.secondary)
                Spacer()
            }
            .padding(22)
            .background(AppBackground())
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("完成") { dismiss() }
                        .disabled(store.isBusy)
                }
            }
            .onAppear {
                store.selectAlbum(id: albumId)
            }
            .sheet(isPresented: $pickerPresented) {
                LivePhotoPicker { assets in
                    Task { await store.uploadAssets(assets) }
                }
            }
        }
    }
}

private struct UploadProgressPanel: View {
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                UploadMetric(title: "已选择", value: "\(store.uploadSelectedCount)")
                UploadMetric(title: "已准备", value: "\(store.uploadPreparedCount)")
                UploadMetric(title: "已上传", value: "\(store.uploadUploadedCount)")
            }

            if let progress = store.uploadProgressFraction {
                ProgressView(value: progress)
                    .tint(.blue)
            }

            Text(store.uploadProgressText)
                .font(.subheadline.weight(.semibold))
                .foregroundColor(.primary)

            if store.uploadLivePhotoCount > 0 || store.uploadIgnoredCount > 0 {
                HStack(spacing: 10) {
                    if store.uploadLivePhotoCount > 0 {
                        Label("\(store.uploadLivePhotoCount) 张 Live Photo", systemImage: "livephoto")
                    }
                    if store.uploadIgnoredCount > 0 {
                        Label("忽略 \(store.uploadIgnoredCount) 个非照片文件", systemImage: "exclamationmark.circle")
                    }
                }
                .font(.caption.weight(.semibold))
                .foregroundColor(.secondary)
            }
        }
        .padding(16)
        .background(.white.opacity(0.86), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.teal.opacity(0.12)))
    }
}

private struct UploadMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundColor(.secondary)
            Text(value)
                .font(.title3.weight(.black))
                .foregroundColor(.primary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct AlbumCard: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 14) {
                    ForEach(album.folders.prefix(6)) { folder in
                        VStack(spacing: 8) {
                            if let coverURL = store.folderCoverURL(album: album, folder: folder) {
                                RemoteImage(url: coverURL, mode: .fill)
                                    .frame(width: 64, height: 88)
                                    .clipShape(Capsule())
                                    .overlay(Capsule().stroke(.white, lineWidth: 3))
                                    .shadow(color: .black.opacity(0.12), radius: 10, y: 5)
                            } else {
                                Capsule()
                                    .fill(.teal.opacity(0.12))
                                    .frame(width: 64, height: 88)
                                    .overlay(Image(systemName: "person.crop.circle").foregroundColor(.teal))
                            }
                            Text(folder.name)
                                .font(.caption.weight(.bold))
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            Text(album.name)
                .font(.system(size: 30, weight: .black))
            Text("\(album.photos.count) 张朋友视角 · \(album.contributors.count) 位参与者")
                .font(.headline)
                .foregroundColor(.secondary)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white.opacity(0.92), in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(.teal.opacity(0.12)))
        .shadow(color: .orange.opacity(0.08), radius: 20, y: 10)
    }
}

private struct AlbumHero: View {
    let album: Album

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(album.name)
                .font(.system(size: 42, weight: .black))
            HStack(spacing: 10) {
                StatPill(text: "\(album.photos.count) 张朋友视角")
                StatPill(text: "\(album.folders.count) 个小相册")
                StatPill(text: "\(album.contributors.count) 位参与者")
            }
        }
        .padding(.vertical, 14)
    }
}

private struct MyPhotosRecommendationCard: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album

    private var count: Int {
        album.myPhotoCount ?? album.myPhotoIds?.count ?? 0
    }

    var body: some View {
        NavigationLink {
            MyPhotosView(albumId: album.id)
        } label: {
            HStack(spacing: 14) {
                ZStack {
                    if let cover = album.myCoverUrl, let url = store.imageURL(cover) {
                        RemoteImage(url: url, mode: .fill)
                    } else if let avatarUrl = store.currentUser?.avatarUrl, let url = store.imageURL(avatarUrl) {
                        RemoteImage(url: url, mode: .fill)
                    } else {
                        Circle()
                            .fill(Color.teal.opacity(0.12))
                            .overlay(Image(systemName: "person.crop.circle").font(.title).foregroundColor(.teal))
                    }
                }
                .frame(width: 64, height: 64)
                .clipShape(Circle())
                .overlay(Circle().stroke(.white, lineWidth: 3))
                .shadow(color: .teal.opacity(0.14), radius: 12, y: 6)

                VStack(alignment: .leading, spacing: 5) {
                    Text("我的照片")
                        .font(.title3.weight(.black))
                        .foregroundColor(.primaryText)
                    Text(cardMessage)
                        .font(.subheadline.weight(.semibold))
                        .foregroundColor(.secondaryText)
                        .lineLimit(2)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.headline.weight(.bold))
                    .foregroundColor(.teal)
            }
            .padding(16)
            .background(.white.opacity(0.86), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(.teal.opacity(0.14)))
        }
        .buttonStyle(.plain)
    }

    private var cardMessage: String {
        if count > 0 {
            return "已为你匹配到 \(count) 张照片"
        }
        if store.currentUser?.hasFaceProfile == true {
            return "暂时没有匹配结果，点开查看空态"
        }
        return "上传带人脸头像后，会自动推荐你的照片"
    }
}

private struct FolderCard: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let folder: PhotoFolder
    let compact: Bool

    private var photoCount: Int {
        store.photos(in: album, folder: folder).count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let coverURL = store.folderCoverURL(album: album, folder: folder) {
                RemoteImage(url: coverURL, mode: .fill)
                    .frame(height: compact ? 132 : 190)
                    .clipped()
            } else {
                Rectangle()
                    .fill(.teal.opacity(0.10))
                    .frame(height: compact ? 132 : 190)
                    .overlay(Image(systemName: "person.2.crop.square.stack").font(.title).foregroundColor(.teal))
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(folder.name)
                    .font(.title3.weight(.black))
                    .lineLimit(1)
                Text("\(photoCount) 张 · 最近 \(folder.updatedAt.map(formatDate) ?? "--")")
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.secondary)
            }
            .padding(14)
        }
        .background(.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.teal.opacity(0.12)))
    }
}

private struct FolderSwitcher: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    @Binding var currentFolderId: String

    var orderedFolders: [PhotoFolder] {
        guard let current = album.folders.first(where: { $0.id == currentFolderId }) else { return album.folders }
        return [current] + album.folders.filter { $0.id != currentFolderId }
    }

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                ForEach(orderedFolders) { folder in
                    Button {
                        withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
                            currentFolderId = folder.id
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(folder.name)
                                .font(.title2.weight(.black))
                            Text("\(store.photos(in: album, folder: folder).count) 张照片")
                                .font(.headline)
                                .foregroundColor(.secondary)
                        }
                        .frame(width: 150, alignment: .leading)
                        .padding(16)
                        .background(folder.id == currentFolderId ? Color.teal.opacity(0.12) : Color.white, in: RoundedRectangle(cornerRadius: 18))
                        .overlay(RoundedRectangle(cornerRadius: 18).stroke(folder.id == currentFolderId ? Color.teal : Color.gray.opacity(0.18), lineWidth: folder.id == currentFolderId ? 2 : 1))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

private struct PhotoLibraryGrid: View {
    let album: Album
    let photos: [Photo]
    @Binding var columnCount: Int
    let zoomScale: CGFloat
    @Binding var selectedPhoto: Photo?
    let isSelecting: Bool
    @Binding var selectedPhotoIds: Set<String>

    private let tileSpacing: CGFloat = 1
    private let minColumns = 2
    private let maxColumns = 6

    private var metrics: PhotoGridMetrics {
        PhotoGridMetrics(
            width: UIScreen.main.bounds.width,
            photoCount: photos.count,
            baseColumnCount: columnCount,
            zoomScale: zoomScale,
            spacing: tileSpacing,
            minColumns: minColumns,
            maxColumns: maxColumns
        )
    }

    var body: some View {
        let metrics = metrics

        ZStack(alignment: .topLeading) {
            ForEach(Array(photos.enumerated()), id: \.element.id) { index, photo in
                let position = metrics.position(for: index)
                PhotoLibraryTile(
                    album: album,
                    photo: photo,
                    tileSide: metrics.tileSide,
                    displayColumnCount: metrics.displayColumnCount,
                    selectedPhoto: $selectedPhoto,
                    isSelecting: isSelecting,
                    selectedPhotoIds: $selectedPhotoIds
                )
                .frame(width: metrics.tileSide, height: metrics.tileSide)
                .position(x: position.x, y: position.y)
            }
        }
        .frame(width: metrics.width, height: metrics.height, alignment: .topLeading)
        .clipped()
        .animation(.interactiveSpring(response: 0.22, dampingFraction: 0.9), value: columnCount)
    }
}

private struct PhotoGridMetrics {
    let width: CGFloat
    let photoCount: Int
    let baseColumnCount: Int
    let zoomScale: CGFloat
    let spacing: CGFloat
    let minColumns: Int
    let maxColumns: Int

    var displayColumnCount: Int {
        let count = (width + spacing) / (rawTileSide + spacing)
        return min(max(Int(count.rounded()), minColumns), maxColumns)
    }

    var tileSide: CGFloat {
        min(width, rawTileSide)
    }

    var height: CGFloat {
        guard photoCount > 0 else { return 0 }
        let rowCount = Int(ceil(Double(photoCount) / Double(displayColumnCount)))
        return CGFloat(rowCount) * tileSide + CGFloat(max(0, rowCount - 1)) * spacing
    }

    private var clampedZoomScale: CGFloat {
        min(max(zoomScale, 0.58), 1.75)
    }

    private var baseTileSide: CGFloat {
        let availableWidth = width - CGFloat(baseColumnCount - 1) * spacing
        return availableWidth / CGFloat(baseColumnCount)
    }

    private var rawTileSide: CGFloat {
        max(48, baseTileSide * clampedZoomScale)
    }

    func position(for index: Int) -> CGPoint {
        let row = index / displayColumnCount
        let column = index % displayColumnCount
        return CGPoint(
            x: CGFloat(column) * (tileSide + spacing) + tileSide / 2,
            y: CGFloat(row) * (tileSide + spacing) + tileSide / 2
        )
    }
}

private struct PhotoLibraryTile: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let photo: Photo
    let tileSide: CGFloat
    let displayColumnCount: Int
    @Binding var selectedPhoto: Photo?
    let isSelecting: Bool
    @Binding var selectedPhotoIds: Set<String>

    private var isSelected: Bool {
        selectedPhotoIds.contains(photo.id)
    }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Button {
                if isSelecting {
                    if isSelected {
                        selectedPhotoIds.remove(photo.id)
                    } else {
                        selectedPhotoIds.insert(photo.id)
                    }
                } else {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.9)) {
                        selectedPhoto = photo
                    }
                }
            } label: {
                ZStack(alignment: .bottomLeading) {
                    RemoteImage(url: store.imageURL(photo.thumbnailUrl ?? photo.previewUrl ?? photo.imageUrl), mode: .fill)
                        .frame(width: tileSide, height: tileSide)
                        .clipped()

                    if photo.isLivePhoto {
                        LiveBadge(showText: displayColumnCount <= 3)
                            .padding(displayColumnCount <= 3 ? 8 : 5)
                    }
                }
                .frame(width: tileSide, height: tileSide)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isSelecting {
                SelectionCheckmark(isSelected: isSelected)
                    .padding(displayColumnCount >= 5 ? 4 : 8)
            }
        }
        .frame(width: tileSide, height: tileSide)
        .clipped()
    }
}

private struct SelectionTopBar: View {
    @Binding var isSelecting: Bool
    @Binding var selectedPhotoIds: Set<String>
    let photos: [Photo]

    private var allSelected: Bool {
        !photos.isEmpty && photos.allSatisfy { selectedPhotoIds.contains($0.id) }
    }

    var body: some View {
        HStack {
            Button(allSelected ? "取消全选" : "全选") {
                if allSelected {
                    selectedPhotoIds.removeAll()
                } else {
                    selectedPhotoIds = Set(photos.map(\.id))
                }
            }
            .disabled(!isSelecting || photos.isEmpty)
            .opacity(isSelecting ? 1 : 0)

            Spacer()

            Button(isSelecting ? "取消" : "选择") {
                withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
                    if isSelecting {
                        selectedPhotoIds.removeAll()
                    }
                    isSelecting.toggle()
                }
            }
            .font(.headline.weight(.bold))
            .foregroundColor(.blue)
        }
        .font(.headline.weight(.semibold))
    }
}

private struct SelectionCheckmark: View {
    let isSelected: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(isSelected ? Color.blue : Color.black.opacity(0.2))
            Circle()
                .stroke(.white, lineWidth: 2)
            if isSelected {
                Image(systemName: "checkmark")
                    .font(.caption.weight(.black))
                    .foregroundColor(.white)
            }
        }
        .frame(width: 26, height: 26)
    }
}

private struct SelectionBottomBar: View {
    let count: Int
    let onDelete: () -> Void
    let onMore: () -> Void

    var body: some View {
        HStack {
            Button(role: .destructive, action: onDelete) {
                Image(systemName: "trash")
                    .font(.title3.weight(.bold))
            }
            .disabled(count == 0)

            Spacer()

            Text("已选择 \(count) 项")
                .font(.headline.weight(.semibold))
                .foregroundColor(.primary)

            Spacer()

            Button(action: onMore) {
                Image(systemName: "ellipsis.circle.fill")
                    .font(.title.weight(.bold))
            }
            .disabled(count == 0)
        }
        .padding(.horizontal, 26)
        .padding(.vertical, 14)
        .background(.ultraThinMaterial)
    }
}

private struct LiveBadge: View {
    let showText: Bool

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "livephoto")
            if showText {
                Text("LIVE")
            }
        }
        .font(.caption2.weight(.black))
        .foregroundColor(.white)
        .padding(.horizontal, showText ? 7 : 5)
        .padding(.vertical, 4)
        .background(.black.opacity(0.38), in: Capsule())
        .shadow(color: .black.opacity(0.2), radius: 4, y: 2)
    }
}

private struct PhotoViewer: View {
    @EnvironmentObject private var store: SharePhotosStore
    @Environment(\.dismiss) private var dismiss
    let albumId: String
    let photos: [Photo]
    let initialPhotoId: String
    var onClose: (() -> Void)?
    @State private var selectedPhotoId: String

    init(albumId: String, photos: [Photo], initialPhotoId: String, onClose: (() -> Void)? = nil) {
        self.albumId = albumId
        self.photos = photos
        self.initialPhotoId = initialPhotoId
        self.onClose = onClose
        _selectedPhotoId = State(initialValue: initialPhotoId)
    }

    private var currentPhoto: Photo? {
        photos.first(where: { $0.id == selectedPhotoId }) ?? photos.first
    }
    private var album: Album? {
        store.album(id: albumId)
    }
    private func close() {
        if let onClose {
            onClose()
        } else {
            dismiss()
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            if let currentPhoto {
                HStack {
                    Button {
                        close()
                    } label: {
                        Label("返回", systemImage: "chevron.left")
                            .labelStyle(.titleAndIcon)
                            .font(.headline.weight(.semibold))
                            .foregroundColor(.blue)
                    }
                    Spacer()
                    VStack(spacing: 2) {
                        Text(formatViewerDate(currentPhoto.createdAt))
                            .font(.headline.weight(.bold))
                        Text(formatViewerTime(currentPhoto.createdAt))
                            .font(.caption.weight(.semibold))
                            .foregroundColor(.secondary)
                    }
                    .foregroundColor(.primary)
                    Spacer()
                    ViewerMenu(album: album, photo: currentPhoto, onClose: close)
                }
                .padding(.horizontal, 18)
                .padding(.top, 10)
                .padding(.bottom, 10)
                .background(Color.white)
            }

            TabView(selection: $selectedPhotoId) {
                ForEach(photos) { photo in
                    PhotoViewerPage(photo: photo)
                        .tag(photo.id)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            PhotoViewerFilmstrip(photos: photos, selectedPhotoId: $selectedPhotoId)

            if let currentPhoto {
                SavePhotoButton(photo: currentPhoto)
                    .padding(.horizontal, 20)
                    .padding(.top, 10)
                    .padding(.bottom, 28)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white.ignoresSafeArea())
        .preferredColorScheme(.light)
        .edgeSwipeBack { close() }
    }
}

private struct ViewerMenu: View {
    let album: Album?
    let photo: Photo
    let onClose: () -> Void
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        Menu {
            Button {
                Task { await store.saveToSystemPhotos(photo) }
            } label: {
                Label(photo.isLivePhoto ? "保存 Live Photo" : "保存照片", systemImage: "square.and.arrow.down")
            }
            if let album {
                Button(role: .destructive) {
                    Task {
                        await store.deletePhoto(album: album, photo: photo)
                        onClose()
                    }
                } label: {
                    Label("删除", systemImage: "trash")
                }
            }
        } label: {
            Image(systemName: "ellipsis.circle")
                .font(.title2.weight(.bold))
                .foregroundColor(.blue)
        }
    }
}

private struct PhotoViewerFilmstrip: View {
    @EnvironmentObject private var store: SharePhotosStore
    let photos: [Photo]
    @Binding var selectedPhotoId: String

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(photos) { photo in
                        Button {
                            selectedPhotoId = photo.id
                        } label: {
                            RemoteImage(url: store.imageURL(photo.thumbnailUrl ?? photo.previewUrl ?? photo.imageUrl), mode: .fill)
                                .frame(width: 46, height: 46)
                                .clipped()
                                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(photo.id == selectedPhotoId ? Color.blue : Color.clear, lineWidth: 2)
                                )
                        }
                        .buttonStyle(.plain)
                        .id(photo.id)
                    }
                }
                .padding(.horizontal, 20)
            }
            .frame(height: 58)
            .background(Color.white)
            .onAppear {
                proxy.scrollTo(selectedPhotoId, anchor: .center)
            }
            .onChange(of: selectedPhotoId) { newValue in
                withAnimation(.easeOut(duration: 0.18)) {
                    proxy.scrollTo(newValue, anchor: .center)
                }
            }
        }
    }
}

private struct PhotoViewerPage: View {
    @EnvironmentObject private var store: SharePhotosStore
    let photo: Photo

    var body: some View {
        ZStack {
            Color.white
            if photo.isLivePhoto {
                LivePhotoPlaybackView(photo: photo)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            } else {
                RemoteImage(url: store.imageURL(photo.previewUrl ?? photo.imageUrl), mode: .fit)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }
}

private struct SavePhotoButton: View {
    @EnvironmentObject private var store: SharePhotosStore
    let photo: Photo

    var body: some View {
        Button {
            Task { await store.saveToSystemPhotos(photo) }
        } label: {
            Label(photo.isLivePhoto ? "保存 Live Photo" : "保存照片", systemImage: "square.and.arrow.down")
                .font(.headline.weight(.bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .foregroundColor(.blue)
        }
    }
}

private struct PhotoMenu: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let photo: Photo
    var compact = false

    var body: some View {
        Menu {
            Button {
                Task { await store.saveToSystemPhotos(photo) }
            } label: {
                Label(photo.isLivePhoto ? "下载 Live Photo" : "下载照片", systemImage: "square.and.arrow.down")
            }
            Menu("移动到") {
                ForEach(album.folders.filter { !$0.photoIds.orEmpty.contains(photo.id) }) { folder in
                    Button(folder.name) {
                        Task { await store.movePhoto(album: album, photo: photo, targetFolder: folder) }
                    }
                }
            }
            Button(role: .destructive) {
                Task { await store.deletePhoto(album: album, photo: photo) }
            } label: {
                Label("删除", systemImage: "trash")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font((compact ? Font.caption : Font.headline).weight(.bold))
                .padding(compact ? 7 : 10)
                .background(.regularMaterial, in: Circle())
                .foregroundColor(.primary)
        }
    }
}

private struct LivePhotoPlaybackView: View {
    @EnvironmentObject private var store: SharePhotosStore
    let photo: Photo
    private let previewAspectRatio: CGFloat = 3.0 / 4.0
    @State private var livePhoto: PHLivePhoto?
    @State private var videoURL: URL?
    @State private var playbackToken = 0
    @State private var isMotionPlaying = false
    @State private var isLoading = false
    @State private var errorText: String?

    var body: some View {
        GeometryReader { proxy in
            let previewSize = fittedPreviewSize(in: proxy.size)

            ZStack {
                ZStack {
                    if let livePhoto {
                        SystemLivePhotoView(livePhoto: livePhoto, playbackToken: playbackToken)
                    } else {
                        RemoteImage(url: store.imageURL(photo.previewUrl ?? photo.imageUrl), mode: .fit)
                            .overlay(.black.opacity(0.18))
                    }

                    if let videoURL, isMotionPlaying {
                        LiveMotionVideoView(videoURL: videoURL, isPlaying: $isMotionPlaying)
                            .transition(.opacity)
                    }
                }
                .frame(width: previewSize.width, height: previewSize.height)
                .clipped()

                VStack {
                    HStack {
                        Button {
                            Task { await playLiveMotion() }
                        } label: {
                            Label("LIVE", systemImage: "livephoto")
                                .font(.caption.weight(.black))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(.black.opacity(0.5), in: Capsule())
                                .foregroundColor(.white)
                        }
                        .disabled(isLoading)
                        Spacer()
                    }
                    Spacer()
                }
                .padding(14)

                if isLoading {
                    VStack(spacing: 12) {
                        ProgressView()
                            .tint(.white)
                        Text("正在加载 Live Photo")
                            .font(.headline)
                            .foregroundColor(.white)
                    }
                    .padding(18)
                    .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 18))
                }

                if let errorText {
                    VStack(spacing: 10) {
                        Image(systemName: "livephoto.slash")
                            .font(.largeTitle)
                        Text(errorText)
                            .font(.headline)
                            .multilineTextAlignment(.center)
                    }
                    .foregroundColor(.white)
                    .padding(18)
                    .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 18))
                }
            }
            .frame(width: previewSize.width, height: previewSize.height)
            .clipped()
            .position(x: proxy.size.width / 2, y: proxy.size.height / 2)
        }
    }

    private func fittedPreviewSize(in availableSize: CGSize) -> CGSize {
        guard availableSize.width > 0, availableSize.height > 0 else {
            return .zero
        }

        let widthFittingHeight = availableSize.height * previewAspectRatio
        if widthFittingHeight <= availableSize.width {
            return CGSize(width: widthFittingHeight, height: availableSize.height)
        }

        return CGSize(width: availableSize.width, height: availableSize.width / previewAspectRatio)
    }

    private func ensureLiveResources() async -> Bool {
        if videoURL != nil || livePhoto != nil {
            return true
        }
        isLoading = true
        errorText = nil
        defer { isLoading = false }
        do {
            videoURL = try await store.livePhotoVideo(for: photo)
            livePhoto = nil
            return true
        } catch {
            errorText = "Live Photo 预览失败\n\(error.localizedDescription)"
            return false
        }
    }

    private func playLiveMotion() async {
        guard await ensureLiveResources() else { return }
        if livePhoto != nil {
            playbackToken += 1
        }
        guard videoURL != nil else { return }
        isMotionPlaying = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
            isMotionPlaying = true
        }
    }

    private func requestLivePhoto(imageURL: URL, videoURL: URL) async throws -> PHLivePhoto {
        try await withCheckedThrowingContinuation { continuation in
            let gate = LivePhotoContinuationGate()
            PHLivePhoto.request(
                withResourceFileURLs: [imageURL, videoURL],
                placeholderImage: nil,
                targetSize: .zero,
                contentMode: .aspectFit
            ) { livePhoto, info in
                if let livePhoto {
                    gate.resume {
                        continuation.resume(returning: livePhoto)
                    }
                } else if let error = info[PHLivePhotoInfoErrorKey] as? Error {
                    gate.resume {
                        continuation.resume(throwing: error)
                    }
                } else {
                    gate.resume {
                        continuation.resume(throwing: LivePhotoPreviewError.failed)
                    }
                }
            }
        }
    }
}

private final class LivePhotoContinuationGate {
    private let lock = NSLock()
    private var hasResumed = false

    func resume(_ body: () -> Void) {
        lock.lock()
        defer { lock.unlock() }
        guard !hasResumed else { return }
        hasResumed = true
        body()
    }
}

private struct SystemLivePhotoView: UIViewRepresentable {
    let livePhoto: PHLivePhoto
    let playbackToken: Int

    func makeUIView(context: Context) -> LivePhotoContainerView {
        let view = LivePhotoContainerView()
        view.livePhotoView.livePhoto = livePhoto
        DispatchQueue.main.async {
            view.livePhotoView.startPlayback(with: .full)
        }
        return view
    }

    func updateUIView(_ uiView: LivePhotoContainerView, context: Context) {
        uiView.livePhotoView.livePhoto = livePhoto
        guard context.coordinator.lastPlaybackToken != playbackToken else { return }
        context.coordinator.lastPlaybackToken = playbackToken
        DispatchQueue.main.async {
            uiView.livePhotoView.startPlayback(with: .full)
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    final class Coordinator {
        var lastPlaybackToken = -1
    }
}

private final class LivePhotoContainerView: UIView {
    let livePhotoView = PHLivePhotoView()

    override init(frame: CGRect) {
        super.init(frame: frame)
        clipsToBounds = true
        livePhotoView.translatesAutoresizingMaskIntoConstraints = false
        livePhotoView.contentMode = .scaleAspectFit
        livePhotoView.clipsToBounds = true
        addSubview(livePhotoView)
        NSLayoutConstraint.activate([
            livePhotoView.leadingAnchor.constraint(equalTo: leadingAnchor),
            livePhotoView.trailingAnchor.constraint(equalTo: trailingAnchor),
            livePhotoView.topAnchor.constraint(equalTo: topAnchor),
            livePhotoView.bottomAnchor.constraint(equalTo: bottomAnchor)
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var intrinsicContentSize: CGSize {
        .zero
    }
}

private struct LiveMotionVideoView: UIViewRepresentable {
    let videoURL: URL
    @Binding var isPlaying: Bool

    func makeUIView(context: Context) -> PlayerLayerView {
        let view = PlayerLayerView()
        view.playerLayer.videoGravity = .resizeAspect
        return view
    }

    func updateUIView(_ uiView: PlayerLayerView, context: Context) {
        if context.coordinator.videoURL != videoURL {
            context.coordinator.videoURL = videoURL
            context.coordinator.player = AVPlayer(url: videoURL)
            uiView.playerLayer.player = context.coordinator.player
        }

        guard isPlaying else {
            context.coordinator.player?.pause()
            return
        }

        context.coordinator.onFinished = {
            isPlaying = false
        }
        context.coordinator.play()
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    final class Coordinator: NSObject {
        var videoURL: URL?
        var player: AVPlayer?
        var observer: Any?
        var onFinished: (() -> Void)?

        func play() {
            guard let player else { return }
            player.seek(to: .zero)
            observer.map { NotificationCenter.default.removeObserver($0) }
            observer = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime,
                object: player.currentItem,
                queue: .main
            ) { [weak self] _ in
                self?.onFinished?()
            }
            player.play()
        }

        deinit {
            observer.map { NotificationCenter.default.removeObserver($0) }
        }
    }
}

private final class PlayerLayerView: UIView {
    override class var layerClass: AnyClass {
        AVPlayerLayer.self
    }

    var playerLayer: AVPlayerLayer {
        layer as! AVPlayerLayer
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        playerLayer.frame = bounds
        playerLayer.videoGravity = .resizeAspect
    }
}

private enum LivePhotoPreviewError: LocalizedError {
    case failed

    var errorDescription: String? {
        "无法还原 Live Photo"
    }
}

private struct FolderMenu: View {
    @EnvironmentObject private var store: SharePhotosStore
    let album: Album
    let folder: PhotoFolder
    let onRename: () -> Void
    let onDelete: () -> Void

    var body: some View {
        Menu {
            Button {
                onRename()
            } label: {
                Label("重命名小相册", systemImage: "pencil")
            }
            Button {
                Task { await store.downloadFolder(album: album, folder: folder) }
            } label: {
                Label("下载照片包", systemImage: "square.and.arrow.down")
            }
            Button(role: .destructive) {
                onDelete()
            } label: {
                Label("删除小相册", systemImage: "trash")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.headline.weight(.bold))
                .padding(12)
                .background(.ultraThinMaterial, in: Circle())
                .foregroundColor(.primary)
        }
    }
}

private struct RemoteImage: View {
    let url: URL?
    let mode: ContentMode
    @State private var state: RemoteImageState = .loading

    var body: some View {
        Group {
            switch state {
            case .loading:
                Rectangle().fill(.teal.opacity(0.08)).overlay(ProgressView())
            case .success(let image):
                Image(uiImage: image).resizable().aspectRatio(contentMode: mode)
            case .failure:
                Rectangle().fill(.gray.opacity(0.12)).overlay(Image(systemName: "photo").foregroundColor(.secondary))
            }
        }
        .task(id: url) {
            await load()
        }
    }

    private func load() async {
        guard let url else {
            state = .failure
            return
        }
        state = .loading
        do {
            let image = try await PhotoDiskCache.shared.dataImage(for: url)
            guard !Task.isCancelled else { return }
            state = .success(image)
        } catch {
            guard !Task.isCancelled else { return }
            state = .failure
        }
    }
}

private enum RemoteImageState {
    case loading
    case success(UIImage)
    case failure
}

private struct BrandHeader: View {
    var body: some View {
        HStack(spacing: 14) {
            PicMeLogo(size: 64)
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("识我")
                        .font(.system(size: 30, weight: .black))
                        .foregroundColor(.primaryText)
                    Text("PicMe")
                        .font(.system(size: 23, weight: .bold))
                        .foregroundStyle(LinearGradient(colors: [.picmeAqua, .picmeViolet], startPoint: .leading, endPoint: .trailing))
                }
                Text("自动找到属于你的旅行照片")
                    .font(.headline)
                    .foregroundColor(.secondaryText)
            }
        }
    }
}

private struct AccountMenu: View {
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        Menu {
            if let user = store.currentUser {
                Text(user.nickname)
                Text("@\(user.username)")
            }
            Button(role: .destructive) {
                Task { await store.logout() }
            } label: {
                Label("退出登录", systemImage: "rectangle.portrait.and.arrow.right")
            }
        } label: {
            ZStack {
                if let avatarUrl = store.currentUser?.avatarUrl, let url = store.imageURL(avatarUrl) {
                    RemoteImage(url: url, mode: .fill)
                } else {
                    Circle()
                        .fill(Color.teal.opacity(0.12))
                        .overlay(Image(systemName: "person.fill").foregroundColor(.teal))
                }
            }
            .frame(width: 46, height: 46)
            .clipShape(Circle())
            .overlay(Circle().stroke(.white, lineWidth: 2))
            .shadow(color: .black.opacity(0.10), radius: 10, y: 5)
        }
    }
}

private struct PicMeLogo: View {
    let size: CGFloat

    var body: some View {
        Image("PicMeLogo")
            .resizable()
            .scaledToFit()
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
        .shadow(color: .picmeInk.opacity(0.12), radius: 16, x: 0, y: 10)
    }
}

private struct SelfPointerSymbol: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let cx = rect.midX
        let headRadius = rect.width * 0.16
        path.addEllipse(in: CGRect(x: cx - headRadius, y: rect.minY + rect.height * 0.05, width: headRadius * 2, height: headRadius * 2))
        path.move(to: CGPoint(x: rect.minX + rect.width * 0.2, y: rect.maxY * 0.92))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - rect.width * 0.2, y: rect.maxY * 0.92),
            control: CGPoint(x: cx, y: rect.height * 0.52)
        )
        path.move(to: CGPoint(x: rect.minX + rect.width * 0.13, y: rect.height * 0.62))
        path.addQuadCurve(
            to: CGPoint(x: cx + rect.width * 0.14, y: rect.height * 0.73),
            control: CGPoint(x: rect.minX + rect.width * 0.43, y: rect.height * 0.53)
        )
        return path
    }
}

private struct BackButton: View {
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text("返回")
                .font(.headline.weight(.bold))
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
                .background(Color.teal.opacity(0.12), in: Capsule())
                .foregroundColor(.teal)
        }
    }
}

private struct StatPill: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(.white.opacity(0.9), in: RoundedRectangle(cornerRadius: 14))
    }
}

private struct EmptyAlbumState: View {
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "photo.stack")
                .font(.system(size: 44))
                .foregroundColor(.teal)
            Text("暂无相册")
                .font(.title2.weight(.black))
                .foregroundColor(.primaryText)
            Text("点下面的创建新相册，先开一个朋友照片局。")
                .font(.subheadline)
                .foregroundColor(.secondaryText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 52)
        .background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 24))
    }
}

private struct EmptyContentState: View {
    let systemImage: String
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 38))
                .foregroundColor(.teal)
            Text(title)
                .font(.headline.weight(.black))
                .foregroundColor(.primaryText)
                .multilineTextAlignment(.center)
            Text(message)
                .font(.subheadline)
                .foregroundColor(.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
        .padding(.horizontal, 18)
        .background(.white.opacity(0.82), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(.teal.opacity(0.12)))
    }
}

private struct OperationHUD: View {
    @EnvironmentObject private var store: SharePhotosStore

    var body: some View {
        HStack(spacing: 12) {
            if let progress = store.operationProgress {
                ZStack {
                    Circle()
                        .stroke(.teal.opacity(0.18), lineWidth: 5)
                    Circle()
                        .trim(from: 0, to: CGFloat(max(0, min(progress, 1))))
                        .stroke(.teal, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    Text("\(Int(progress * 100))")
                        .font(.caption2.weight(.black))
                        .foregroundColor(.teal)
                }
                .frame(width: 38, height: 38)
            } else {
                ProgressView()
                    .tint(.teal)
                    .frame(width: 38, height: 38)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(store.operationTitle)
                    .font(.headline.weight(.bold))
                    .foregroundColor(.primaryText)
                Text(store.operationMessage)
                    .font(.caption.weight(.semibold))
                    .foregroundColor(.secondaryText)
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.white.opacity(0.96), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(.teal.opacity(0.15)))
        .shadow(color: .black.opacity(0.12), radius: 18, y: 8)
    }
}

private struct AppBackground: View {
    var body: some View {
        LinearGradient(colors: [Color(red: 0.99, green: 0.98, blue: 0.94), Color(red: 0.92, green: 0.98, blue: 0.97), Color(red: 1.0, green: 0.94, blue: 0.88)], startPoint: .topLeading, endPoint: .bottomTrailing)
            .ignoresSafeArea()
    }
}

private struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

private struct EdgeSwipeBackModifier: ViewModifier {
    let action: () -> Void

    func body(content: Content) -> some View {
        content
            .simultaneousGesture(
                DragGesture(minimumDistance: 18, coordinateSpace: .global)
                    .onEnded { value in
                        let beganAtLeftEdge = value.startLocation.x <= 28
                        let isRightSwipe = value.translation.width > 80
                        let isMostlyHorizontal = abs(value.translation.height) < 70
                        if beganAtLeftEdge && isRightSwipe && isMostlyHorizontal {
                            action()
                        }
                    }
            )
    }
}

private struct PhotoGridZoomModifier: ViewModifier {
    @Binding var columnCount: Int
    @Binding var zoomScale: CGFloat

    func body(content: Content) -> some View {
        content
            .simultaneousGesture(
                MagnificationGesture()
                    .onChanged { value in
                        zoomScale = min(max(value, 0.58), 1.75)
                    }
                    .onEnded { value in
                        withAnimation(.spring(response: 0.28, dampingFraction: 0.82)) {
                            let targetColumns = Int((CGFloat(columnCount) / min(max(value, 0.58), 1.75)).rounded())
                            columnCount = min(max(targetColumns, 2), 6)
                            zoomScale = 1
                        }
                    }
            )
    }
}

private extension View {
    func edgeSwipeBack(_ action: @escaping () -> Void) -> some View {
        modifier(EdgeSwipeBackModifier(action: action))
    }

    func photoGridZoom(columnCount: Binding<Int>, zoomScale: Binding<CGFloat>) -> some View {
        modifier(PhotoGridZoomModifier(columnCount: columnCount, zoomScale: zoomScale))
    }

    func authHelpStyle(isWarning: Bool = false) -> some View {
        self
            .font(.footnote.weight(.semibold))
            .foregroundColor(isWarning ? .red : .secondaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10)
            .padding(.top, -8)
    }
}

private func formatDate(_ timestamp: Int?) -> String {
    guard let timestamp else { return "--" }
    let formatter = DateFormatter()
    formatter.dateFormat = "MM/dd HH:mm"
    return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(timestamp)))
}

private func formatViewerDate(_ timestamp: Int?) -> String {
    guard let timestamp else { return "照片" }
    let formatter = DateFormatter()
    formatter.dateFormat = "yyyy年M月d日"
    return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(timestamp)))
}

private func formatViewerTime(_ timestamp: Int?) -> String {
    guard let timestamp else { return "" }
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm"
    return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(timestamp)))
}

private let primaryGradient = LinearGradient(
    colors: [.teal, Color(red: 0.0, green: 0.42, blue: 0.36)],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
)

private extension Color {
    static let primaryText = Color(red: 0.07, green: 0.10, blue: 0.12)
    static let secondaryText = Color(red: 0.38, green: 0.46, blue: 0.50)
    static let picmeMist = Color(red: 0.98, green: 0.99, blue: 1.00)
    static let picmeGlassBlue = Color(red: 0.87, green: 0.96, blue: 0.98)
    static let picmeLavender = Color(red: 0.86, green: 0.88, blue: 0.97)
    static let picmeInk = Color(red: 0.19, green: 0.34, blue: 0.43)
    static let picmeAqua = Color(red: 0.29, green: 0.66, blue: 0.78)
    static let picmeViolet = Color(red: 0.46, green: 0.39, blue: 0.86)
}

private extension Optional where Wrapped == [String] {
    var orEmpty: [String] { self ?? [] }
}
