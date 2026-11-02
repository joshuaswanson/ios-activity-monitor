// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "IOSActivityMonitor",
    platforms: [.macOS(.v15)],
    targets: [
        .executableTarget(name: "IOSActivityMonitor", path: "Sources")
    ]
)
