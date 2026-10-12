import Foundation

@main
struct WorkRecorderRecordingE2E {
    static func main() async {
        do {
            let arguments = try RunnerArguments.parse(CommandLine.arguments)
            let result = try await RecordingFixtureRunner(arguments: arguments).run()
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(result)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("WorkRecorderRecordingE2E failed: \(error)\n".utf8))
            Foundation.exit(1)
        }
    }
}
