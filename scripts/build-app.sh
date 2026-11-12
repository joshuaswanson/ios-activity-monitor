#!/usr/bin/env bash
#
# Builds "build/iOS Activity Monitor.app": the SwiftUI app plus a private copy
# of Python holding the device engine.
#
# Needs Xcode, uv, and librsvg (brew install librsvg).
#
# Signs with your Apple Development or Developer ID identity when one exists.
# Set SIGN_IDENTITY to override it, for example SIGN_IDENTITY=- for ad-hoc.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/build/iOS Activity Monitor.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
ENGINE="$RESOURCES/engine"
PYTHON_VERSION="3.12"

build_swift() {
    local bin_path
    swift build --package-path "$ROOT/app" -c release --arch arm64
    bin_path="$(swift build --package-path "$ROOT/app" -c release --arch arm64 --show-bin-path)"
    mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Frameworks" "$RESOURCES"
    cp "$bin_path/IOSActivityMonitor" "$CONTENTS/MacOS/iOS Activity Monitor"
    ditto "$bin_path/Sparkle.framework" "$CONTENTS/Frameworks/Sparkle.framework"
    cp "$ROOT/app/Resources/Info.plist" "$CONTENTS/Info.plist"
    cp -R "$ROOT/app/Resources/ui" "$RESOURCES/ui"
    cp "$ROOT/assets/logo.svg" "$RESOURCES/ui/logo.svg"
}

build_icon() {
    local work iconset icon_svg
    work="$(mktemp -d)"
    iconset="$work/AppIcon.iconset"
    icon_svg="$work/icon.svg"
    mkdir "$iconset"
    # macOS icons sit on a 1024 canvas with a 100pt transparent margin. The
    # Dock draws no shadow of its own, so the margin holds a baked one matching
    # Apple's template.
    {
        printf '%s' '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1024 1024">'
        printf '%s' '<defs><filter id="shadow" x="-25%" y="-25%" width="150%" height="150%">'
        printf '%s' '<feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#000000" flood-opacity="0.2"/>'
        printf '%s' '</filter></defs>'
        printf '<image x="100" y="100" width="824" height="824" filter="url(#shadow)" xlink:href="data:image/svg+xml;base64,%s"/></svg>' \
            "$(base64 < "$ROOT/assets/logo.svg" | tr -d '\n')"
    } > "$icon_svg"
    for size in 16 32 128 256 512; do
        rsvg-convert -w "$size" -h "$size" "$icon_svg" -o "$iconset/icon_${size}x${size}.png"
        rsvg-convert -w "$((size * 2))" -h "$((size * 2))" "$icon_svg" -o "$iconset/icon_${size}x${size}@2x.png"
    done
    iconutil --convert icns "$iconset" --output "$RESOURCES/AppIcon.icns"
    rm -rf "$work"
}

build_engine() {
    local python_root requirements
    uv python install --quiet "$PYTHON_VERSION"
    python_root="$("$(uv python find --managed-python "$PYTHON_VERSION")" -c 'import sys; print(sys.base_prefix)')"
    cp -RL "$python_root" "$ENGINE"
    requirements="$(mktemp)"
    uv export --project "$ROOT" --frozen --no-dev --no-emit-project --no-hashes --quiet --output-file "$requirements"
    uv pip install --quiet --python "$ENGINE/bin/python$PYTHON_VERSION" --break-system-packages \
        --requirement "$requirements" "$ROOT"
    rm -f "$requirements"

    local stdlib="$ENGINE/lib/python$PYTHON_VERSION"
    rm -rf "$ENGINE/include" "$ENGINE/share" "$ENGINE"/lib/pkgconfig "$ENGINE"/lib/tcl* "$ENGINE"/lib/tk* \
        "$ENGINE"/lib/itcl* "$ENGINE"/lib/thread* "$ENGINE"/lib/libtcl* "$ENGINE"/lib/libtk* \
        "$stdlib/test" "$stdlib/idlelib" "$stdlib/tkinter" "$stdlib/turtledemo" "$stdlib/ensurepip" \
        "$stdlib"/config-* "$stdlib/site-packages/pip"* 
    find "$ENGINE/bin" -type f ! -name "python$PYTHON_VERSION" -delete
    find "$ENGINE/bin" -type l -delete
    find "$ENGINE" -type d -name __pycache__ -prune -exec rm -rf {} +
    find "$ENGINE" -type f \( -name '*.a' -o -name '*.pyi' \) -delete
    "$ENGINE/bin/python$PYTHON_VERSION" -I -m compileall -q -j 0 "$stdlib" >/dev/null
}

collect_licenses() {
    local licenses="$RESOURCES/Licenses" site_packages="$ENGINE/lib/python$PYTHON_VERSION/site-packages"
    mkdir -p "$licenses"
    cp "$ROOT/LICENSE" "$licenses/iOS Activity Monitor.txt"
    cp "$ENGINE/lib/python$PYTHON_VERSION/LICENSE.txt" "$licenses/Python.txt"
    for dist_info in "$site_packages"/*.dist-info; do
        local name
        name="$(basename "$dist_info" .dist-info)"
        mkdir -p "$licenses/$name"
        find "$dist_info" -type f \( -iname 'licen[cs]e*' -o -iname 'copying*' -o -iname 'notice*' \) \
            -exec cp {} "$licenses/$name/" \;
        if [[ -z "$(ls -A "$licenses/$name")" ]]; then
            # Some wheels ship no license file, so record the license their metadata declares.
            grep -E '^(Name|Version|License|License-Expression|Home-page|Project-URL):|^Classifier: License ::' \
                "$dist_info/METADATA" > "$licenses/$name/LICENSE-METADATA.txt"
        fi
    done
}

sign() {
    local identity log
    identity="${SIGN_IDENTITY:-$(security find-identity -v -p codesigning | awk -F'"' '/Apple Development|Developer ID Application/ {print $2; exit}')}"
    identity="${identity:--}"
    log="$(mktemp)"
    find "$ENGINE" -type f \( -name '*.so' -o -name '*.dylib' -o -name "python$PYTHON_VERSION" \) -print0 \
        | xargs -0 -n 16 -P 8 codesign --force --timestamp=none --sign "$identity" > "$log" 2>&1 \
        || { cat "$log"; exit 1; }
    rm -f "$log"
    codesign --force --timestamp=none --sign "$identity" "$APP" 2>/dev/null
    codesign --verify --strict "$APP"
    echo "signed with: $identity"
}

rm -rf "$APP"
mkdir -p "$RESOURCES"
build_swift
build_icon
build_engine
collect_licenses
sign
du -sh "$APP"
echo "built $APP"
