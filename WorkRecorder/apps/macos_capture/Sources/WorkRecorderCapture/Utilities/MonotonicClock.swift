import Foundation

func monotonicMilliseconds() -> Int {
    Int((ProcessInfo.processInfo.systemUptime * 1000).rounded())
}
