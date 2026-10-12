// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "WorkRecorderCapture",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "WorkRecorderCapture", targets: ["WorkRecorderCapture"])
    ],
    targets: [
        .target(
            name: "WorkRecorderCaptureDesign",
            path: "Sources/WorkRecorderCaptureDesign"
        ),
        .executableTarget(
            name: "WorkRecorderCapture",
            dependencies: ["WorkRecorderCaptureDesign"],
            path: "Sources/WorkRecorderCapture"
        ),
        .executableTarget(
            name: "WorkRecorderRecordingE2E",
            path: "Sources/WorkRecorderRecordingE2E"
        ),
        .testTarget(
            name: "WorkRecorderCaptureTests",
            dependencies: ["WorkRecorderCapture"],
            path: "Tests/WorkRecorderCaptureTests"
        )
    ]
)
