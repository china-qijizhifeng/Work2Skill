import AppKit

public enum HUDDesignTokens {
    public enum Layout {
        public static let compactBreakpoint: CGFloat = 640
        public static let sheetMargin: CGFloat = 24
        public static let desktopMinWidth: CGFloat = 540
        public static let desktopMaxWidth: CGFloat = 580
        public static let desktopHeight: CGFloat = 164
        public static let compactMinWidth: CGFloat = 280
        public static let compactHeight: CGFloat = 176
        public static let inputActionGap: CGFloat = 20
        public static let actionRailWidth: CGFloat = 176
        public static let permissionActionRailWidth: CGFloat = 194
        public static let associationEdgeLength: CGFloat = 74
        public static let associationInset: CGFloat = 42
        public static let handleRadius: CGFloat = 3
        public static let sourceIconSize: CGFloat = 16
    }

    public enum WorkbenchLayout {
        public static let sidebarWidth: CGFloat = 230
        public static let sidebarHorizontalInset: CGFloat = 18
        public static let sidebarContentWidth: CGFloat = sidebarWidth - sidebarHorizontalInset * 2
        public static let sidebarMeterWidth: CGFloat = sidebarContentWidth - 32
        public static let contentInset = NSEdgeInsets(top: 10, left: 46, bottom: 30, right: 28)
        public static let cardHeight: CGFloat = 180
        public static let cardThumbnailWidth: CGFloat = 150
        public static let cardThumbnailHeight: CGFloat = 102
        public static let libraryCardWidth: CGFloat = 570
        public static let libraryCardHeight: CGFloat = 286
        public static let libraryThumbnailHeight: CGFloat = 166
        public static let inspectorWidth: CGFloat = 470
        public static let inspectorInnerWidth: CGFloat = 452
        public static let inspectorMaxScrollHeight: CGFloat = 430
        public static let toolbarHeight: CGFloat = 32
    }

    public enum Prism {
        public static let pearlWhite = NSColor(calibratedRed: 0.97, green: 0.98, blue: 0.98, alpha: 1.0)
        public static let frostedWhite = NSColor(calibratedRed: 0.95, green: 0.97, blue: 0.97, alpha: 1.0)
        public static let mistSilver = NSColor(calibratedRed: 0.90, green: 0.94, blue: 0.95, alpha: 1.0)
        public static let tiffanyBlue = NSColor(calibratedRed: 0.51, green: 0.85, blue: 0.82, alpha: 1.0)
        public static let softAqua = NSColor(calibratedRed: 0.68, green: 0.92, blue: 0.89, alpha: 1.0)
        public static let mintGlass = NSColor(calibratedRed: 0.81, green: 0.96, blue: 0.94, alpha: 1.0)
        public static let iceBlue = NSColor(calibratedRed: 0.87, green: 0.97, blue: 1.0, alpha: 1.0)
        public static let paleSilverBlue = NSColor(calibratedRed: 0.87, green: 0.92, blue: 0.95, alpha: 1.0)
        public static let softLavender = NSColor(calibratedRed: 0.91, green: 0.88, blue: 0.97, alpha: 1.0)
        public static let pinkBlueHint = NSColor(calibratedRed: 0.95, green: 0.92, blue: 0.97, alpha: 1.0)

        public enum Alpha {
            public static let capsuleTop: CGFloat = 0.075
            public static let capsuleRim: CGFloat = 0.072
            public static let capsuleBottom: CGFloat = 0.066
            public static let capsuleViolet: CGFloat = 0.030
            public static let buttonSheen: CGFloat = 0.040
            public static let buttonSheenActive: CGFloat = 0.068
            public static let inputFocus: CGFloat = 0.026
            public static let inputFocusActive: CGFloat = 0.040
            public static let selectionHaze: CGFloat = 0.034
            public static let selectionHazeActive: CGFloat = 0.046
        public static let selectionLine: CGFloat = 1.95
        public static let selectionLineActive: CGFloat = 2.15
        public static let selectionGlow: CGFloat = 0.235
        public static let selectionGlowActive: CGFloat = 0.315
        public static let selectionCorner: CGFloat = 0.430
        public static let selectionCornerActive: CGFloat = 0.500
            public static let refractionLine: CGFloat = 0.018
            public static let refractionLineActive: CGFloat = 0.028
        }
    }

    public enum Material {
        public static let hudPanel = NSColor(calibratedRed: 0.928, green: 0.976, blue: 0.982, alpha: 0.995)
        public static let hudElevated = NSColor(calibratedRed: 0.904, green: 0.958, blue: 0.968, alpha: 0.982)
        public static let hudField = NSColor(calibratedRed: 0.958, green: 0.990, blue: 0.992, alpha: 0.998)
        public static let panelStroke = NSColor(calibratedRed: 0.12, green: 0.46, blue: 0.51, alpha: 0.72)
        public static let panelGlassTop = NSColor(calibratedRed: 0.968, green: 0.996, blue: 0.998, alpha: 1.0)
        public static let panelGlassMid = NSColor(calibratedRed: 0.926, green: 0.978, blue: 0.984, alpha: 1.0)
        public static let panelGlassBottom = NSColor(calibratedRed: 0.882, green: 0.944, blue: 0.956, alpha: 1.0)
        public static let panelRim = NSColor(calibratedRed: 0.12, green: 0.46, blue: 0.51, alpha: 0.72)
        public static let inputFillTop = NSColor(calibratedRed: 0.982, green: 0.998, blue: 0.998, alpha: 1.0)
        public static let inputFillBottom = NSColor(calibratedRed: 0.952, green: 0.986, blue: 0.990, alpha: 1.0)
        public static let inputStroke = NSColor(calibratedRed: 0.32, green: 0.72, blue: 0.72, alpha: 0.34)
        public static let inputStrokeActive = NSColor(calibratedRed: 0.20, green: 0.76, blue: 0.75, alpha: 0.58)
        public static let placeholder = NSColor(calibratedRed: 0.52, green: 0.60, blue: 0.62, alpha: 1.0)
    }

    public enum WorkbenchMaterial {
        public static let canvas = NSColor(calibratedRed: 0.963, green: 0.980, blue: 0.985, alpha: 1.0)
        public static let sidebar = NSColor(calibratedRed: 0.918, green: 0.952, blue: 0.964, alpha: 0.92)
        public static let sidebarSelected = NSColor(calibratedRed: 0.872, green: 0.966, blue: 0.968, alpha: 0.84)
        public static let panel = NSColor(calibratedRed: 0.968, green: 0.991, blue: 0.992, alpha: 0.88)
        public static let panelElevated = NSColor(calibratedRed: 0.986, green: 0.997, blue: 0.996, alpha: 0.92)
        public static let panelSoft = NSColor(calibratedRed: 0.925, green: 0.972, blue: 0.976, alpha: 0.64)
        public static let panelWarm = NSColor(calibratedRed: 0.998, green: 0.976, blue: 0.932, alpha: 0.88)
        public static let evidenceNote = NSColor(calibratedRed: 0.934, green: 0.982, blue: 0.980, alpha: 0.80)
        public static let evidenceNoteSoft = NSColor(calibratedRed: 0.950, green: 0.974, blue: 0.976, alpha: 0.58)
        public static let inspectorWell = NSColor(calibratedRed: 0.962, green: 0.986, blue: 0.988, alpha: 0.82)
        public static let hairline = NSColor(calibratedRed: 0.36, green: 0.62, blue: 0.64, alpha: 0.105)
        public static let neutralHairline = NSColor(calibratedRed: 0.50, green: 0.57, blue: 0.59, alpha: 0.090)
        public static let primaryText = NSColor(calibratedRed: 0.105, green: 0.140, blue: 0.155, alpha: 1.0)
        public static let secondaryText = NSColor(calibratedRed: 0.34, green: 0.42, blue: 0.44, alpha: 1.0)
        public static let mutedText = NSColor(calibratedRed: 0.47, green: 0.54, blue: 0.56, alpha: 1.0)
        public static let actionText = NSColor(calibratedRed: 0.10, green: 0.38, blue: 0.41, alpha: 1.0)
        public static let success = NSColor(calibratedRed: 0.13, green: 0.52, blue: 0.40, alpha: 1.0)
        public static let warning = NSColor(calibratedRed: 0.66, green: 0.42, blue: 0.18, alpha: 1.0)
    }

    public enum WorkbenchTypography {
        public static var pageTitle: NSFont { NSFont.systemFont(ofSize: 22.5, weight: .semibold) }
        public static var pageSubtitle: NSFont { NSFont.systemFont(ofSize: 12.6, weight: .regular) }
        public static var sectionTitle: NSFont { NSFont.systemFont(ofSize: 13.6, weight: .semibold) }
        public static var cardTitle: NSFont { NSFont.systemFont(ofSize: 13.0, weight: .semibold) }
        public static var body: NSFont { NSFont.systemFont(ofSize: 12.2, weight: .regular) }
        public static var caption: NSFont { NSFont.systemFont(ofSize: 11.0, weight: .regular) }
        public static var action: NSFont { NSFont.systemFont(ofSize: 12.4, weight: .semibold) }
        public static var micro: NSFont { NSFont.systemFont(ofSize: 10.4, weight: .medium) }
    }

    public enum Satin {
        public static let silverHighlight = NSColor(calibratedRed: 0.965, green: 0.982, blue: 0.985, alpha: 1.0)
        public static let coolGraphiteReflection = NSColor(calibratedRed: 0.42, green: 0.53, blue: 0.56, alpha: 1.0)
        public static let coatingBlue = NSColor(calibratedRed: 0.73, green: 0.93, blue: 0.92, alpha: 1.0)
        public static let membraneAlpha: CGFloat = 0.045
        public static let edgeCoatingAlpha: CGFloat = 0.070
        public static let rimAlpha: CGFloat = 0.060
        public static let handleFillAlpha: CGFloat = 0.58
        public static let handleHighlightAlpha: CGFloat = 0.72
        public static let statusCoreAlpha: CGFloat = 0.86
    }
}
