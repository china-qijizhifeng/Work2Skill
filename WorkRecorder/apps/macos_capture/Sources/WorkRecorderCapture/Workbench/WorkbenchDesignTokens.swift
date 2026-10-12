import AppKit
import WorkRecorderCaptureDesign

enum WorkbenchDesignTokens {
    enum Color {
        // Palette sampled from the WorkRecorder recorder icon: cool paper,
        // sky blue, saturated device blue, black ink and a recording-red dot.
        static let brandSky = NSColor(calibratedRed: 0.690, green: 0.830, blue: 0.985, alpha: 1.0)
        static let brandBlue = NSColor(calibratedRed: 0.285, green: 0.555, blue: 0.895, alpha: 1.0)
        static let brandBlueStrong = NSColor(calibratedRed: 0.105, green: 0.335, blue: 0.665, alpha: 1.0)
        static let brandInk = NSColor(calibratedRed: 0.035, green: 0.055, blue: 0.085, alpha: 1.0)
        static let recordingRed = NSColor(calibratedRed: 0.980, green: 0.225, blue: 0.170, alpha: 1.0)
        static let recordingRedStrong = NSColor(calibratedRed: 0.790, green: 0.115, blue: 0.085, alpha: 1.0)

        static let canvas = NSColor(calibratedRed: 0.950, green: 0.970, blue: 0.995, alpha: 1.0)
        static let sidebar = NSColor(calibratedRed: 0.900, green: 0.945, blue: 0.995, alpha: 0.97)
        static let sidebarSelected = NSColor(calibratedRed: 0.820, green: 0.900, blue: 0.995, alpha: 0.94)
        static let panel = NSColor(calibratedRed: 0.975, green: 0.986, blue: 1.000, alpha: 0.96)
        static let panelElevated = NSColor(calibratedRed: 0.995, green: 0.998, blue: 1.000, alpha: 0.99)
        static let panelSoft = NSColor(calibratedRed: 0.885, green: 0.935, blue: 0.995, alpha: 0.88)
        static let panelWarm = NSColor(calibratedRed: 0.925, green: 0.958, blue: 1.000, alpha: 0.92)
        static let evidenceNote = NSColor(calibratedRed: 0.895, green: 0.942, blue: 1.000, alpha: 0.88)
        static let evidenceNoteSoft = NSColor(calibratedRed: 0.935, green: 0.966, blue: 1.000, alpha: 0.82)
        static let inspectorWell = NSColor(calibratedRed: 0.920, green: 0.952, blue: 0.992, alpha: 0.92)

        // Keep the established semantic names so all recording/review views
        // automatically inherit the same WorkRecorder blue family.
        static let tiffany = brandBlue
        static let tiffanySoft = brandSky
        static let tiffanyStrong = brandBlueStrong
        static let prismViolet = recordingRed
        static let success = brandBlueStrong
        static let warning = recordingRedStrong
        static let muted = NSColor(calibratedRed: 0.405, green: 0.455, blue: 0.535, alpha: 1.0)
        static let secondaryText = NSColor(calibratedRed: 0.220, green: 0.275, blue: 0.365, alpha: 1.0)
        static let primaryText = brandInk
        static let hairline = brandBlueStrong.withAlphaComponent(0.15)
        static let neutralHairline = brandBlueStrong.withAlphaComponent(0.13)
        static let locked = NSColor(calibratedRed: 0.430, green: 0.515, blue: 0.625, alpha: 1.0)
    }

    enum Radius {
        static let panel: CGFloat = 14
        static let hero: CGFloat = 18
        static let control: CGFloat = 10
        static let badge: CGFloat = 12
        static let thumbnail: CGFloat = 12
    }

    enum Spacing {
        static let xs: CGFloat = 6
        static let sm: CGFloat = 10
        static let md: CGFloat = 14
        static let lg: CGFloat = 20
        static let xl: CGFloat = 28
        static let xxl: CGFloat = 36
        static let pageInset = NSEdgeInsets(top: 32, left: 40, bottom: 40, right: 34)
    }

    @MainActor
    enum Font {
        static let pageTitle = HUDDesignTokens.WorkbenchTypography.pageTitle
        static let pageSubtitle = HUDDesignTokens.WorkbenchTypography.pageSubtitle
        static let sectionTitle = HUDDesignTokens.WorkbenchTypography.sectionTitle
        static let cardTitle = HUDDesignTokens.WorkbenchTypography.cardTitle
        static let body = HUDDesignTokens.WorkbenchTypography.body
        static let caption = HUDDesignTokens.WorkbenchTypography.caption
        static let action = HUDDesignTokens.WorkbenchTypography.action
        static let micro = HUDDesignTokens.WorkbenchTypography.micro
    }

    enum Shadow {
        static func applyPanelShadow(to layer: CALayer?) {
            layer?.shadowColor = Color.brandBlueStrong.withAlphaComponent(0.11).cgColor
            layer?.shadowOpacity = 1
            layer?.shadowRadius = 18
            layer?.shadowOffset = CGSize(width: 0, height: -7)
        }

        static func applyHeroShadow(to layer: CALayer?) {
            layer?.shadowColor = Color.brandBlue.withAlphaComponent(0.16).cgColor
            layer?.shadowOpacity = 1
            layer?.shadowRadius = 28
            layer?.shadowOffset = CGSize(width: 0, height: -10)
        }
    }
}
