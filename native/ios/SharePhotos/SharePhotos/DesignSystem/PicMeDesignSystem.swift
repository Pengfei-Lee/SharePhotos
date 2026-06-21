import SwiftUI
import UIKit

enum PicMeStyle {
    static let blue = Color(hex: 0x4F7CFF)
    static let violet = Color(hex: 0x6A5CFF)
    static let green = Color(hex: 0x22C55E)
    static let orange = Color(hex: 0xF59E0B)
    static let red = Color(hex: 0xFF4757)
    static let background = Color(hex: 0xF2F4F7)
    static let card = Color.white
    static let ink = Color(hex: 0x0F1115)
    static let gray = Color(hex: 0x8E9AA3)
    static let hairline = Color.black.opacity(0.08)
    static let primaryText = ink
    static let secondaryText = gray
    static let gradient = LinearGradient(colors: [blue, violet], startPoint: .topLeading, endPoint: .bottomTrailing)
    static let softGradient = LinearGradient(colors: [blue.opacity(0.14), violet.opacity(0.16)], startPoint: .topLeading, endPoint: .bottomTrailing)
}

struct PicMeBackground: View {
    var body: some View {
        PicMeStyle.background.ignoresSafeArea()
    }
}

struct PicMeCard<Content: View>: View {
    var radius: CGFloat = 16
    @ViewBuilder let content: Content

    var body: some View {
        content
            .background(PicMeStyle.card, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .shadow(color: PicMeStyle.ink.opacity(0.05), radius: 16, y: 4)
    }
}

struct PicMePrimaryButton: View {
    let title: String
    var systemImage: String?
    var disabled = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if let systemImage {
                    Label(title, systemImage: systemImage)
                } else {
                    Text(title)
                }
            }
            .font(.headline.weight(.black))
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background(disabled ? AnyShapeStyle(Color(hex: 0xE7EAF0)) : AnyShapeStyle(PicMeStyle.gradient), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .foregroundColor(disabled ? Color(hex: 0xA7B0BD) : .white)
            .shadow(color: disabled ? .clear : PicMeStyle.blue.opacity(0.35), radius: 20, y: 8)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(1)
    }
}

struct PicMeSectionHeader: View {
    let title: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(PicMeStyle.primaryText)
            Spacer()
            if let actionTitle, let action {
                Button(action: action) {
                    HStack(spacing: 2) {
                        Text(actionTitle)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    .font(.system(size: 13.5, weight: .medium))
                    .foregroundColor(PicMeStyle.secondaryText)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

struct PicMeSegmentedControl<Item: Identifiable & Hashable>: View {
    let items: [Item]
    @Binding var selection: Item
    let title: (Item) -> String
    var dark = false

    var body: some View {
        HStack(spacing: 22) {
            ForEach(items) { item in
                Button {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
                        selection = item
                    }
                } label: {
                    VStack(spacing: 0) {
                        Text(title(item))
                            .font(.system(size: 15, weight: selection == item ? .bold : .medium))
                            .foregroundColor(textColor(for: item))
                            .padding(.bottom, 12)
                        Capsule()
                            .fill(selection == item ? AnyShapeStyle(PicMeStyle.gradient) : AnyShapeStyle(Color.clear))
                            .frame(height: 3)
                    }
                    .fixedSize()
                }
                .buttonStyle(.plain)
            }
            Spacer(minLength: 0)
        }
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(dark ? Color.white.opacity(0.12) : PicMeStyle.hairline)
                .frame(height: 0.5)
        }
    }

    private func textColor(for item: Item) -> Color {
        if dark {
            return selection == item ? .white : .white.opacity(0.55)
        }
        return selection == item ? PicMeStyle.primaryText : PicMeStyle.secondaryText
    }
}

struct PicMeTopBar: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    var subtitle: String?
    var trailing: AnyView?

    var body: some View {
        HStack(spacing: 10) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.headline.weight(.bold))
                    .frame(width: 38, height: 38)
                    .background(.white.opacity(0.78), in: Circle())
                    .foregroundColor(PicMeStyle.primaryText)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.headline.weight(.black))
                    .foregroundColor(PicMeStyle.primaryText)
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption.weight(.semibold))
                        .foregroundColor(PicMeStyle.secondaryText)
                }
            }
            Spacer()
            trailing
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}

struct PicMeAvatar: View {
    let name: String
    var size: CGFloat = 44

    var body: some View {
        Circle()
            .fill(avatarGradient)
            .frame(width: size, height: size)
            .overlay(Text(String(name.prefix(1))).font(.system(size: size * 0.42, weight: .black)).foregroundColor(.white))
    }

    private var avatarGradient: LinearGradient {
        let palettes: [[Color]] = [
            [.pink.opacity(0.75), .orange.opacity(0.78)],
            [PicMeStyle.blue.opacity(0.75), PicMeStyle.violet.opacity(0.85)],
            [.green.opacity(0.7), .mint.opacity(0.8)],
            [.purple.opacity(0.7), .indigo.opacity(0.84)]
        ]
        return LinearGradient(colors: palettes[abs(name.hashValue) % palettes.count], startPoint: .topLeading, endPoint: .bottomTrailing)
    }
}

struct PicMeAvatarStack: View {
    let names: [String]
    var size: CGFloat = 24
    var limit = 3

    var body: some View {
        HStack(spacing: -8) {
            ForEach(Array(names.prefix(limit).enumerated()), id: \.offset) { _, name in
                PicMeAvatar(name: name, size: size)
                    .overlay(Circle().stroke(.white, lineWidth: 1.8))
            }
            if names.count > limit {
                Text("+\(names.count - limit)")
                    .font(.system(size: size * 0.36, weight: .black))
                    .foregroundColor(.white)
                    .frame(width: size, height: size)
                    .background(.black.opacity(0.38), in: Circle())
                    .overlay(Circle().stroke(.white.opacity(0.82), lineWidth: 1.5))
            }
        }
    }
}

struct PicMeLogoMark: View {
    let size: CGFloat

    var body: some View {
        Image("PicMeLogo")
            .resizable()
            .scaledToFit()
            .frame(width: size * 1.14, height: size * 1.14)
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.24, style: .continuous))
            .shadow(color: PicMeStyle.blue.opacity(0.28), radius: 16, y: 6)
    }
}

struct PicMeStripePlaceholder: View {
    let seed: String

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let height = proxy.size.height
            Canvas { context, size in
                context.fill(Path(CGRect(origin: .zero, size: size)), with: .linearGradient(Gradient(colors: palette), startPoint: .zero, endPoint: CGPoint(x: size.width, y: size.height)))
                for index in stride(from: -height, through: width + height, by: 18) {
                    var path = Path()
                    path.move(to: CGPoint(x: index, y: height))
                    path.addLine(to: CGPoint(x: index + height, y: 0))
                    context.stroke(path, with: .color(.white.opacity(0.22)), lineWidth: 9)
                }
            }
        }
    }

    private var palette: [Color] {
        let palettes: [[Color]] = [
            [Color(red: 0.78, green: 0.84, blue: 0.94), Color(red: 0.62, green: 0.71, blue: 0.86)],
            [Color(red: 0.91, green: 0.82, blue: 0.74), Color(red: 0.83, green: 0.69, blue: 0.58)],
            [Color(red: 0.78, green: 0.88, blue: 0.79), Color(red: 0.58, green: 0.76, blue: 0.63)],
            [Color(red: 0.86, green: 0.80, blue: 0.92), Color(red: 0.74, green: 0.65, blue: 0.86)]
        ]
        return palettes[abs(seed.hashValue) % palettes.count]
    }
}

struct PicMeRemoteImage: View {
    let url: URL?
    @State private var state: PicMeRemoteImageState = .loading

    private var loadKey: String {
        guard let url else { return "" }
        if var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.query = nil
            components.fragment = nil
            if let normalized = components.string, !normalized.isEmpty {
                return normalized
            }
        }
        return url.absoluteString
    }

    var body: some View {
        Group {
            switch state {
            case .loading:
                PicMeStripePlaceholder(seed: url?.absoluteString ?? "picme")
            case .success(let image):
                Image(uiImage: image).resizable().scaledToFill()
            case .failure:
                PicMeStripePlaceholder(seed: url?.absoluteString ?? "picme")
                    .overlay(Image(systemName: "photo").foregroundColor(PicMeStyle.gray.opacity(0.72)))
            }
        }
        .task(id: loadKey) {
            await load()
        }
    }

    private func load() async {
        guard let url else {
            state = .failure
            return
        }
        if let cached = await PhotoDiskCache.shared.cachedImage(for: url) {
            guard !Task.isCancelled else { return }
            state = .success(cached)
            return
        }
        if !state.isSuccess {
            state = .loading
        }
        do {
            let image = try await PhotoDiskCache.shared.dataImage(for: url)
            guard !Task.isCancelled else { return }
            state = .success(image)
        } catch {
            guard !Task.isCancelled else { return }
            if !state.isSuccess {
                state = .failure
            }
        }
    }
}

private enum PicMeRemoteImageState {
    case loading
    case success(UIImage)
    case failure

    var isSuccess: Bool {
        if case .success = self {
            return true
        }
        return false
    }
}

func glassIcon(_ name: String, dark: Bool = false) -> some View {
    Image(systemName: name)
        .font(.system(size: name == "ellipsis" ? 18 : 17, weight: .semibold))
        .foregroundColor(dark ? .white : PicMeStyle.primaryText)
        .frame(width: 38, height: 38)
        .background(.ultraThinMaterial, in: Circle())
        .background((dark ? Color.black.opacity(0.30) : Color.white.opacity(0.50)), in: Circle())
        .overlay(Circle().stroke(dark ? Color.white.opacity(0.16) : Color.white.opacity(0.7), lineWidth: 0.5))
        .shadow(color: dark ? .black.opacity(0.35) : .black.opacity(0.07), radius: dark ? 16 : 10, y: dark ? 6 : 3)
}

extension Color {
    init(hex: UInt, alpha: Double = 1) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }
}
