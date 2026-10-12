enum WorkbenchPermissionState: String {
    case granted
    case denied
    case unknown

    var label: String {
        switch self {
        case .granted: "正常"
        case .denied: "需要处理"
        case .unknown: "未知"
        }
    }
}
