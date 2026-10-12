import Foundation

struct RunnerArguments {
    let outputDirectory: URL
    let durationMilliseconds: Int

    static func parse(_ rawArguments: [String]) throws -> RunnerArguments {
        var outputDirectory: URL?
        var durationMilliseconds = 3_200
        var iterator = rawArguments.dropFirst().makeIterator()
        while let argument = iterator.next() {
            switch argument {
            case "--output-dir":
                guard let value = iterator.next(), !value.isEmpty else {
                    throw FixtureError.invalidArguments("--output-dir requires a path")
                }
                outputDirectory = URL(fileURLWithPath: value, isDirectory: true)
            case "--duration-ms":
                guard let value = iterator.next(), let parsed = Int(value), parsed >= 1_000 else {
                    throw FixtureError.invalidArguments("--duration-ms requires an integer >= 1000")
                }
                durationMilliseconds = parsed
            default:
                throw FixtureError.invalidArguments("unknown argument \(argument)")
            }
        }
        guard let outputDirectory else {
            throw FixtureError.invalidArguments("--output-dir is required")
        }
        return RunnerArguments(outputDirectory: outputDirectory, durationMilliseconds: durationMilliseconds)
    }
}
