import Photos
import PhotosUI
import SwiftUI

struct LivePhotoPicker: UIViewControllerRepresentable {
    let onAssetsPicked: ([PHAsset]) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onAssetsPicked: onAssetsPicked)
    }

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var configuration = PHPickerConfiguration(photoLibrary: .shared())
        configuration.selectionLimit = 0
        configuration.filter = .any(of: [.livePhotos, .images])
        configuration.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: configuration)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onAssetsPicked: ([PHAsset]) -> Void

        init(onAssetsPicked: @escaping ([PHAsset]) -> Void) {
            self.onAssetsPicked = onAssetsPicked
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            let ids = results.compactMap(\.assetIdentifier)
            guard !ids.isEmpty else {
                onAssetsPicked([])
                return
            }

            let fetchResult = PHAsset.fetchAssets(withLocalIdentifiers: ids, options: nil)
            var assets: [PHAsset] = []
            fetchResult.enumerateObjects { asset, _, _ in
                assets.append(asset)
            }
            onAssetsPicked(assets)
        }
    }
}
