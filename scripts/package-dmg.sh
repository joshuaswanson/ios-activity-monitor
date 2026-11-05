#!/usr/bin/env bash
#
# Builds the app and packages it as build/iOS-Activity-Monitor-<version>.dmg,
# with an Applications shortcut so people can drag the app into place.
#
# Release builds are signed ad-hoc. An Apple Development signature would publish
# the certificate's name and email without helping anyone open the app.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="iOS Activity Monitor"
APP="$ROOT/build/$APP_NAME.app"

SIGN_IDENTITY=- "$ROOT/scripts/build-app.sh"

version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
dmg="$ROOT/build/iOS-Activity-Monitor-$version.dmg"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

ditto "$APP" "$staging/$APP_NAME.app"
ln -s /Applications "$staging/Applications"
rm -f "$dmg"
hdiutil create -quiet -volname "$APP_NAME" -srcfolder "$staging" -fs APFS -format ULMO "$dmg"
codesign --force --timestamp=none --sign - "$dmg"
echo "packaged $dmg"
