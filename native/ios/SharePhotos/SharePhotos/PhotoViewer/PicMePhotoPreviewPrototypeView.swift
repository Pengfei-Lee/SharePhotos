import SwiftUI

struct PicMePhotoPreviewPrototypeView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var currentIndex = 3
    @State private var liked = false
    @State private var infoOpen = false
    @State private var saved = false
    private let film = ["people", "warm", "city", "nature", "food", "cool", "people", "night", "warm", "city", "people", "nature"]

    var body: some View {
        ZStack {
            PicMeStyle.background.ignoresSafeArea()
            VStack(spacing: 0) {
                topBar
                photoStage
                bottomPanel
            }
            if saved {
                toast
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.22), value: infoOpen)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: saved)
    }

    private var topBar: some View {
        HStack {
            Button { dismiss() } label: {
                glassIcon("chevron.left")
            }
            .buttonStyle(.plain)
            Spacer()
            VStack(spacing: 2) {
                Text("2025年5月20日")
                    .font(.system(size: 14.5, weight: .semibold))
                    .foregroundColor(PicMeStyle.primaryText)
                Text("\(currentIndex + 1) / \(film.count) · 16:34")
                    .font(.system(size: 11.5))
                    .foregroundColor(PicMeStyle.secondaryText)
            }
            Spacer()
            glassIcon("paperplane")
        }
        .padding(.horizontal, 14)
        .padding(.top, 50)
        .padding(.bottom, 8)
    }

    private var photoStage: some View {
        PicMeStripePlaceholder(seed: film[currentIndex])
            .overlay {
                if film[currentIndex] == "people" {
                    Text("人物 · 飞飞")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(PicMeStyle.ink.opacity(0.5))
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: infoOpen ? 250 : 482)
            .clipped()
    }

    private var bottomPanel: some View {
        VStack(spacing: 0) {
            if infoOpen {
                infoPanel
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
                    .padding(.bottom, 4)
            }
            filmstrip
            HStack(spacing: 4) {
                previewAction("heart", liked ? "已喜欢" : "喜欢", active: liked, color: PicMeStyle.red) { liked.toggle() }
                previewAction("square.and.arrow.down", saved ? "已保存" : "下载", active: saved, color: PicMeStyle.green) {
                    saved = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { saved = false }
                }
                previewAction("person.2", "人物", active: infoOpen, color: PicMeStyle.blue) { infoOpen.toggle() }
                previewAction("ellipsis", "更多", active: false, color: PicMeStyle.primaryText) { infoOpen.toggle() }
            }
            .padding(.horizontal, 14)
            .padding(.top, 6)
            .padding(.bottom, 26)
        }
        .background(PicMeStyle.background)
        .overlay(alignment: .top) {
            Rectangle().fill(PicMeStyle.hairline).frame(height: 0.5)
        }
    }

    private var infoPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            infoLine("clock", "2025年5月20日 16:34")
            infoLine("camera", "iPhone 15 Pro · 主摄")
            infoLine("person", "上传者 张三")
            Text("出现人物")
                .font(.system(size: 12))
                .foregroundColor(PicMeStyle.secondaryText)
                .padding(.top, 2)
                .padding(.bottom, 9)
            HStack(spacing: 16) {
                ForEach(["飞飞", "张三", "李四", "王五"], id: \.self) { name in
                    VStack(spacing: 4) {
                        PicMeAvatar(name: name, size: 40)
                            .overlay(Circle().stroke(.white, lineWidth: 2))
                        Text(name)
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
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) {
                ForEach(Array(film.enumerated()), id: \.offset) { index, seed in
                    PicMeStripePlaceholder(seed: seed)
                        .frame(width: index == currentIndex ? 52 : 34, height: index == currentIndex ? 52 : 44)
                        .clipShape(RoundedRectangle(cornerRadius: index == currentIndex ? 6 : 3, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: index == currentIndex ? 6 : 3).stroke(index == currentIndex ? PicMeStyle.blue : .clear, lineWidth: 2))
                        .opacity(index == currentIndex ? 1 : 0.5)
                        .onTapGesture { currentIndex = index }
                }
            }
            .padding(.horizontal, 172)
            .padding(.vertical, 12)
        }
    }

    private var toast: some View {
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

    private func infoLine(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 11) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .regular))
                .foregroundColor(PicMeStyle.secondaryText)
                .frame(width: 18)
            Text(text)
                .font(.system(size: 13))
                .foregroundColor(PicMeStyle.primaryText)
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
