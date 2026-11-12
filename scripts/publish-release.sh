#!/usr/bin/env bash
#
# Publishes the version in app/Resources/Info.plist as a GitHub release.
#
# Usage:  scripts/publish-release.sh "Release notes shown on GitHub"
#
# The release carries the DMG and an appcast.xml signed with the
# "ios-activity-monitor" Sparkle key from your login keychain. Installed copies
# read the appcast from the latest release to find updates.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="joshuaswanson/ios-activity-monitor"
SPARKLE_VERSION="2.10.1"
SPARKLE_TOOLS="$ROOT/build/sparkle-$SPARKLE_VERSION"
notes="${1:?usage: scripts/publish-release.sh \"release notes\"}"

if [[ ! -x "$SPARKLE_TOOLS/bin/generate_appcast" ]]; then
    mkdir -p "$SPARKLE_TOOLS"
    curl -fsSL "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz" \
        | tar -xJ -C "$SPARKLE_TOOLS"
fi

version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$ROOT/app/Resources/Info.plist")"
tag="v$version"
"$ROOT/scripts/package-dmg.sh"

staging="$ROOT/build/release-$version"
rm -rf "$staging"
mkdir -p "$staging"
cp "$ROOT/build/iOS-Activity-Monitor-$version.dmg" "$staging/"
"$SPARKLE_TOOLS/bin/generate_appcast" \
    --account ios-activity-monitor \
    --download-url-prefix "https://github.com/$REPO/releases/download/$tag/" \
    --full-release-notes-url "https://github.com/$REPO/releases/tag/$tag" \
    "$staging"

gh release create "$tag" "$staging/iOS-Activity-Monitor-$version.dmg" "$staging/appcast.xml" \
    --repo "$REPO" --target main --title "iOS Activity Monitor $version" --notes "$notes"
