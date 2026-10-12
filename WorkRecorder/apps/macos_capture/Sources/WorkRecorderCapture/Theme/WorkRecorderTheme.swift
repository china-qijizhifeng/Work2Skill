import AppKit
import WorkRecorderCaptureDesign

enum WorkRecorderTheme {
    // Shared recording-surface palette derived from the WorkRecorder icon.
    static let accent = NSColor(calibratedRed: 0.285, green: 0.555, blue: 0.895, alpha: 1.0)
    static let accentSoft = NSColor(calibratedRed: 0.690, green: 0.830, blue: 0.985, alpha: 1.0)
    static let accentMist = NSColor(calibratedRed: 0.900, green: 0.945, blue: 0.995, alpha: 1.0)
    static let prismViolet = NSColor(calibratedRed: 0.980, green: 0.225, blue: 0.170, alpha: 1.0)
    static let graphite = NSColor(calibratedRed: 0.035, green: 0.055, blue: 0.085, alpha: 1.0)
    static let graphitePanel = NSColor(calibratedRed: 0.975, green: 0.986, blue: 1.000, alpha: 0.98)
    static let graphiteElevated = NSColor(calibratedRed: 0.995, green: 0.998, blue: 1.000, alpha: 0.99)
    static let fieldBackground = NSColor(calibratedRed: 0.935, green: 0.965, blue: 1.000, alpha: 0.96)
    static let panelStroke = NSColor(calibratedRed: 0.105, green: 0.335, blue: 0.665, alpha: 0.15)
    static let hairline = NSColor(calibratedRed: 0.105, green: 0.335, blue: 0.665, alpha: 0.16)
    static let focusRing = accent.withAlphaComponent(0.44)
    static let success = NSColor(calibratedRed: 0.105, green: 0.335, blue: 0.665, alpha: 1.0)
    static let warning = NSColor(calibratedRed: 0.790, green: 0.115, blue: 0.085, alpha: 1.0)
    static let mutedText = NSColor(calibratedRed: 0.405, green: 0.455, blue: 0.535, alpha: 1.0)
    static let secondaryText = NSColor(calibratedRed: 0.220, green: 0.275, blue: 0.365, alpha: 1.0)
    static let primaryText = graphite
    static let amber = warning

    enum Prism {
        static let pearlWhite = NSColor(calibratedRed: 0.965, green: 0.980, blue: 1.000, alpha: 1.0)
        static let frostedWhite = NSColor(calibratedRed: 0.985, green: 0.992, blue: 1.000, alpha: 1.0)
        static let mistSilver = WorkRecorderTheme.accentMist
        static let tiffanyBlue = WorkRecorderTheme.accent
        static let softAqua = WorkRecorderTheme.accentSoft
        static let mintGlass = WorkRecorderTheme.accentMist
        static let iceBlue = WorkRecorderTheme.accentSoft
        static let paleSilverBlue = NSColor(calibratedRed: 0.875, green: 0.930, blue: 0.995, alpha: 1.0)
        static let softLavender = WorkRecorderTheme.accentSoft
        static let pinkBlueHint = WorkRecorderTheme.prismViolet.withAlphaComponent(0.42)

        enum Alpha {
            static let capsuleTop = HUDDesignTokens.Prism.Alpha.capsuleTop
            static let capsuleRim = HUDDesignTokens.Prism.Alpha.capsuleRim
            static let capsuleBottom = HUDDesignTokens.Prism.Alpha.capsuleBottom
            static let capsuleViolet = HUDDesignTokens.Prism.Alpha.capsuleViolet
            static let buttonSheen = HUDDesignTokens.Prism.Alpha.buttonSheen
            static let buttonSheenActive = HUDDesignTokens.Prism.Alpha.buttonSheenActive
            static let inputFocus = HUDDesignTokens.Prism.Alpha.inputFocus
            static let inputFocusActive = HUDDesignTokens.Prism.Alpha.inputFocusActive
            static let selectionHaze = HUDDesignTokens.Prism.Alpha.selectionHaze
            static let selectionHazeActive = HUDDesignTokens.Prism.Alpha.selectionHazeActive
            static let selectionLine = HUDDesignTokens.Prism.Alpha.selectionLine
            static let selectionLineActive = HUDDesignTokens.Prism.Alpha.selectionLineActive
            static let selectionGlow = HUDDesignTokens.Prism.Alpha.selectionGlow
            static let selectionGlowActive = HUDDesignTokens.Prism.Alpha.selectionGlowActive
            static let selectionCorner = HUDDesignTokens.Prism.Alpha.selectionCorner
            static let selectionCornerActive = HUDDesignTokens.Prism.Alpha.selectionCornerActive
            static let refractionLine = HUDDesignTokens.Prism.Alpha.refractionLine
            static let refractionLineActive = HUDDesignTokens.Prism.Alpha.refractionLineActive
        }
    }

    enum Material {
        static let panelGlassTop = WorkRecorderTheme.graphiteElevated
        static let panelGlassMid = WorkRecorderTheme.graphitePanel
        static let panelGlassBottom = WorkRecorderTheme.accentMist
        static let panelRim = WorkRecorderTheme.panelStroke
        static let inputFillTop = WorkRecorderTheme.graphiteElevated
        static let inputFillBottom = WorkRecorderTheme.fieldBackground
        static let inputStroke = WorkRecorderTheme.panelStroke
        static let inputStrokeActive = WorkRecorderTheme.focusRing
        static let placeholder = WorkRecorderTheme.mutedText
    }

    enum Satin {
        static let silverHighlight = NSColor.white
        static let coolGraphiteReflection = WorkRecorderTheme.graphite
        static let coatingBlue = WorkRecorderTheme.accent
        static let membraneAlpha = HUDDesignTokens.Satin.membraneAlpha
        static let edgeCoatingAlpha = HUDDesignTokens.Satin.edgeCoatingAlpha
        static let rimAlpha = HUDDesignTokens.Satin.rimAlpha
        static let handleFillAlpha = HUDDesignTokens.Satin.handleFillAlpha
        static let handleHighlightAlpha = HUDDesignTokens.Satin.handleHighlightAlpha
        static let statusCoreAlpha = HUDDesignTokens.Satin.statusCoreAlpha
    }

    @MainActor
    enum Font {
        static let title = NSFont.systemFont(ofSize: 13.3, weight: .semibold)
        static let brand = NSFont.systemFont(ofSize: 11.5, weight: .semibold)
        static let chip = NSFont.systemFont(ofSize: 11, weight: .medium)
        static let label = NSFont.systemFont(ofSize: 11.0, weight: .medium)
        static let input = NSFont.systemFont(ofSize: 13.5, weight: .regular)
        static let hint = NSFont.systemFont(ofSize: 10.5, weight: .regular)
        static let action = NSFont.systemFont(ofSize: 13.0, weight: .semibold)
        static let metadata = NSFont.systemFont(ofSize: 11.3, weight: .regular)
    }

    static func roundedRectPath(_ rect: CGRect, radius: CGFloat) -> NSBezierPath {
        NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    }

    static func isLightMode(_ appearance: NSAppearance) -> Bool {
        true
    }

    static func panelColor(for appearance: NSAppearance) -> NSColor {
        graphitePanel
    }

    static func elevatedColor(for appearance: NSAppearance) -> NSColor {
        graphiteElevated
    }

    static func fieldColor(for appearance: NSAppearance) -> NSColor {
        fieldBackground
    }

    static func strokeColor(for appearance: NSAppearance) -> NSColor {
        panelStroke
    }

    static func primaryTextColor(for appearance: NSAppearance) -> NSColor {
        primaryText
    }

    static func secondaryTextColor(for appearance: NSAppearance) -> NSColor {
        secondaryText
    }

    static func mutedTextColor(for appearance: NSAppearance) -> NSColor {
        mutedText
    }
}
