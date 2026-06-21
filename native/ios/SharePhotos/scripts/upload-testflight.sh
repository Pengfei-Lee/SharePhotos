#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/upload-testflight.sh [BUILD_NUMBER]

Examples:
  scripts/upload-testflight.sh
  scripts/upload-testflight.sh 2026062001

When BUILD_NUMBER is omitted, the script uses the local machine date:
  YYYYMMDD01 on a new day, or increments the existing YYYYMMDDNN build.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IOS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_PATH="$IOS_DIR/SharePhotos.xcodeproj"
SCHEME="SharePhotos"
CONFIGURATION="Release"
INFO_PLIST="$IOS_DIR/Info.plist"
PROJECT_YML="$IOS_DIR/project.yml"
EXPORT_OPTIONS="$IOS_DIR/ExportOptions-TestFlight.plist"
BUILD_ROOT="$IOS_DIR/build/TestFlight"
LOG_DIR="$BUILD_ROOT/logs"

current_build="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INFO_PLIST")"
today_prefix="$(date +%Y%m%d)"
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 64
fi

if [[ $# -eq 1 ]]; then
  build_number="$1"
else
  if [[ ! "$current_build" =~ ^[0-9]+$ ]]; then
    echo "Current CFBundleVersion is not numeric: $current_build" >&2
    exit 65
  fi
  if [[ "$current_build" == "$today_prefix"* ]]; then
    build_number="$((current_build + 1))"
  else
    build_number="${today_prefix}01"
    if (( build_number <= current_build )); then
      build_number="$((current_build + 1))"
    fi
  fi
fi

if [[ ! "$build_number" =~ ^[0-9]+$ ]]; then
  echo "BUILD_NUMBER must be numeric: $build_number" >&2
  exit 65
fi

archive_path="$BUILD_ROOT/PicMe-$build_number.xcarchive"
export_path="$BUILD_ROOT/PicMe-$build_number-export"
archive_log="$LOG_DIR/archive-$build_number.log"
upload_log="$LOG_DIR/upload-$build_number.log"

if [[ -e "$archive_path" ]]; then
  echo "Archive already exists: $archive_path" >&2
  echo "Pass a newer build number or remove the old archive intentionally." >&2
  exit 66
fi

mkdir -p "$BUILD_ROOT" "$LOG_DIR"

echo "==> Setting CFBundleVersion to $build_number"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $build_number" "$INFO_PLIST"
perl -0pi -e "s/CFBundleVersion: \"[0-9]+\"/CFBundleVersion: \"$build_number\"/" "$PROJECT_YML"

echo "==> Validating Info.plist"
plutil -lint "$INFO_PLIST"

echo "==> Archiving PicMe $build_number"
xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -destination "generic/platform=iOS" \
  -archivePath "$archive_path" \
  archive 2>&1 | tee "$archive_log"

echo "==> Uploading PicMe $build_number to TestFlight"
xcodebuild \
  -exportArchive \
  -archivePath "$archive_path" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -exportPath "$export_path" \
  -allowProvisioningUpdates 2>&1 | tee "$upload_log"

if ! grep -q "Upload succeeded" "$upload_log"; then
  echo "Upload command finished, but success marker was not found in $upload_log" >&2
  exit 67
fi

echo "==> Uploaded TestFlight build $build_number"
echo "Archive: $archive_path"
echo "Archive log: $archive_log"
echo "Upload log: $upload_log"
