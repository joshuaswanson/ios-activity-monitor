import Foundation

/// Runs the bundled Python engine and exchanges JSON lines with it over pipes.
@MainActor
final class EngineClient {
    private static let restartDelay: Duration = .seconds(2)
    private static let stoppedEvent =
        #"{"type":"status","state":"error","message":"The monitoring engine stopped. Restarting it."}"#

    private var intervalMs = 1000
    private let onEvent: @MainActor (String) -> Void
    private var input: FileHandle?

    init(onEvent: @escaping @MainActor (String) -> Void) {
        self.onEvent = onEvent
    }

    func start(intervalMs: Int) {
        self.intervalMs = intervalMs
        launch()
    }

    func setSampleInterval(_ ms: Int) {
        intervalMs = ms
        try? input?.write(contentsOf: Data("{\"cmd\":\"set_sample_interval\",\"ms\":\(ms)}\n".utf8))
    }

    private func launch() {
        guard let engineRoot = Bundle.main.resourceURL?.appending(path: "engine") else { return }
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let process = Process()
        process.executableURL = engineRoot.appending(path: "bin/python3.12")
        process.arguments = ["-I", "-B", "-m", "ios_activity_monitor.engine", String(intervalMs)]
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = Self.openLogFile() ?? FileHandle.nullDevice

        let lines = LineSplitter()
        outputPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            for line in lines.append(handle.availableData) {
                Task { @MainActor in self?.onEvent(line) }
            }
        }
        process.terminationHandler = { [weak self] _ in
            outputPipe.fileHandleForReading.readabilityHandler = nil
            Task { @MainActor in self?.handleExit() }
        }

        do {
            try process.run()
            input = inputPipe.fileHandleForWriting
        } catch {
            handleExit()
        }
    }

    private func handleExit() {
        input = nil
        onEvent(Self.stoppedEvent)
        Task {
            try? await Task.sleep(for: Self.restartDelay)
            launch()
        }
    }

    private static func openLogFile() -> FileHandle? {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Logs/iOS Activity Monitor")
        let file = directory.appending(path: "engine.log")
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: file.path, contents: nil)
        return try? FileHandle(forWritingTo: file)
    }
}

private final class LineSplitter: @unchecked Sendable {
    private var buffer = Data()

    /// Called only from the pipe's serial readability handler.
    func append(_ data: Data) -> [String] {
        buffer.append(data)
        var lines: [String] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            lines.append(String(decoding: buffer[buffer.startIndex..<newline], as: UTF8.self))
            buffer = Data(buffer[(newline + 1)...])
        }
        return lines
    }
}
