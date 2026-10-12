import AppKit
import Testing
@testable import WorkRecorderCapture

struct GeometryTests {
    @MainActor
    @Test func overlayCancelCallbackIsDeferredAndSingleShot() async throws {
        let screen = try #require(NSScreen.main)
        var cancelCount = 0
        let view = CaptureOverlayView(
            screen: screen,
            completion: { _ in },
            cancel: { cancelCount += 1 }
        )

        view.cancelCapture()
        view.cancelCapture()

        #expect(cancelCount == 0)
        try await Task.sleep(nanoseconds: 20_000_000)
        #expect(cancelCount == 1)
    }

    @Test func normalizedRectHandlesReverseDrag() {
        let rect = Geometry.normalizedRect(from: CGPoint(x: 420, y: 300), to: CGPoint(x: 120, y: 140))
        #expect(rect.origin.x == 120)
        #expect(rect.origin.y == 140)
        #expect(rect.width == 300)
        #expect(rect.height == 160)
    }

    @Test func recordingOverlayStaysInsideVisibleFrame() {
        let sheet = Geometry.recordingOverlayFrame(
            anchor: CGRect(x: 1180, y: 12, width: 200, height: 120),
            panelSize: CGSize(width: 440, height: 174),
            visibleFrame: CGRect(x: 0, y: 0, width: 1440, height: 900)
        )
        #expect(sheet.minX >= 0)
        #expect(sheet.maxX <= 1440)
        #expect(sheet.minY >= 0)
        #expect(sheet.maxY <= 900)
    }

    @Test func recordingOverlayPrefersBelowSelectionWhenSpaceAllows() {
        let anchor = CGRect(x: 320, y: 520, width: 260, height: 160)
        let placement = Geometry.recordingOverlayPlacement(
            anchor: anchor,
            panelSize: CGSize(width: 456, height: 148),
            visibleFrame: CGRect(x: 0, y: 0, width: 1440, height: 900)
        )
        let sheet = placement.frame
        #expect(sheet.maxY < anchor.minY)
        #expect(placement.edge == .below)
    }

    @Test func recordingOverlayFallsBackAboveSelectionNearBottom() {
        let anchor = CGRect(x: 320, y: 28, width: 260, height: 120)
        let placement = Geometry.recordingOverlayPlacement(
            anchor: anchor,
            panelSize: CGSize(width: 456, height: 148),
            visibleFrame: CGRect(x: 0, y: 0, width: 1440, height: 900)
        )
        let sheet = placement.frame
        #expect(sheet.minY > anchor.maxY)
        #expect(placement.edge == .above)
    }

    @Test func recordingOverlayFallsBackRightWhenVerticalSpaceIsConstrained() {
        let anchor = CGRect(x: 180, y: 170, width: 260, height: 180)
        let placement = Geometry.recordingOverlayPlacement(
            anchor: anchor,
            panelSize: CGSize(width: 360, height: 220),
            visibleFrame: CGRect(x: 0, y: 0, width: 920, height: 520)
        )

        #expect(placement.edge == .right)
        #expect(placement.frame.minX > anchor.maxX)
        #expect(placement.associationPoint.x == placement.frame.minX)
    }

    @Test func recordingOverlayClampsInsideNarrowVisibleFrame() {
        let sheet = Geometry.recordingOverlayFrame(
            anchor: CGRect(x: 260, y: 420, width: 80, height: 120),
            panelSize: CGSize(width: 366, height: 132),
            visibleFrame: CGRect(x: 0, y: 0, width: 390, height: 844)
        )
        #expect(sheet.minX >= 10)
        #expect(sheet.maxX <= 380)
        #expect(sheet.minY >= 10)
        #expect(sheet.maxY <= 834)
    }

    @Test func compactSheetUsesBottomHudToAvoidCoveringSmallScreens() {
        let panelSize = CGSize(width: 354, height: 132)
        let placement = Geometry.recordingOverlayPlacement(
            anchor: CGRect(x: 24, y: 492, width: 150, height: 210),
            panelSize: panelSize,
            visibleFrame: CGRect(x: 0, y: 0, width: 390, height: 844)
        )
        let sheet = placement.frame
        #expect(placement.edge == .bottomHud)
        #expect(sheet.minY <= 16)
        #expect(sheet.minX >= 10)
        #expect(sheet.maxX <= 380)
    }

    @Test func recordingOverlayUsesBottomHudOnlyWhenNoHorizontalRoomRemains() {
        let sheet = Geometry.recordingOverlayFrame(
            anchor: CGRect(x: 24, y: 492, width: 150, height: 210),
            panelSize: CGSize(width: 290, height: 132),
            visibleFrame: CGRect(x: 0, y: 0, width: 310, height: 844)
        )
        #expect(sheet.minY <= 16)
        #expect(sheet.minX >= 10)
        #expect(sheet.maxX <= 300)
    }

    @Test func intBoxPreservesNegativeMacOSGlobalCoordinates() {
        let box = Geometry.intBox(
            from: CGRect(x: -880, y: 120, width: 300, height: 160),
            coordinateSpace: "macos_global"
        )
        #expect(box.x == -880)
        #expect(box.y == 120)
    }

    @Test func overlayRectMapsGlobalScreenRectToFlippedLocalRect() {
        let rect = Geometry.overlayRect(
            for: CGRect(x: -820, y: 260, width: 300, height: 140),
            screenFrame: CGRect(x: -900, y: 0, width: 900, height: 600)
        )
        #expect(rect.origin.x == 80)
        #expect(rect.origin.y == 200)
        #expect(rect.width == 300)
        #expect(rect.height == 140)
    }

    @Test @MainActor func appKitScreenRectMapsFlippedOverlayCoordinates() {
        let window = NSWindow(contentRect: CGRect(x: 0, y: 0, width: 1440, height: 900), styleMask: [], backing: .buffered, defer: true)
        let rect = Geometry.appKitScreenRect(for: CGRect(x: 120, y: 140, width: 520, height: 280), in: window)
        #expect(rect.origin.x == 120)
        #expect(rect.origin.y == 480)
        #expect(rect.width == 520)
        #expect(rect.height == 280)
    }

    @Test func displayPixelRectUsesDisplayLocalCoordinatesForRightSideScreen() {
        let rect = Geometry.displayPixelRect(
            from: CGRect(x: 1_520, y: 560, width: 240, height: 120),
            screenFrame: CGRect(x: 1_440, y: 0, width: 1_440, height: 900),
            backingScaleFactor: 2
        )
        #expect(rect.origin.x == 160)
        #expect(rect.origin.y == 440)
        #expect(rect.width == 480)
        #expect(rect.height == 240)
    }

    @Test func displayPixelRectPreservesNegativeDisplayOrigins() {
        let rect = Geometry.displayPixelRect(
            from: CGRect(x: -820, y: 260, width: 300, height: 140),
            screenFrame: CGRect(x: -900, y: 0, width: 900, height: 600),
            backingScaleFactor: 1
        )
        #expect(rect.origin.x == 80)
        #expect(rect.origin.y == 200)
        #expect(rect.width == 300)
        #expect(rect.height == 140)
    }

    @Test func displayPixelRectClipsToDisplayBoundsBeforeScaling() {
        let rect = Geometry.displayPixelRect(
            from: CGRect(x: 1_380, y: 820, width: 180, height: 120),
            screenFrame: CGRect(x: 0, y: 0, width: 1_440, height: 900),
            backingScaleFactor: 2
        )
        #expect(rect.origin.x == 2_760)
        #expect(rect.origin.y == 0)
        #expect(rect.width == 120)
        #expect(rect.height == 160)
    }

    @Test func cgWindowBoundsUseGlobalReferenceForUpperDisplays() {
        let rect = WindowResolver.appKitRect(
            fromCGBounds: CGRect(x: 120, y: -220, width: 300, height: 140),
            referenceMaxY: 900
        )
        #expect(rect.origin.x == 120)
        #expect(rect.origin.y == 980)
        #expect(rect.width == 300)
        #expect(rect.height == 140)
    }

    @Test func cgWindowBoundsUseGlobalReferenceForLowerDisplays() {
        let rect = WindowResolver.appKitRect(
            fromCGBounds: CGRect(x: 120, y: 1_520, width: 300, height: 140),
            referenceMaxY: 900
        )
        #expect(rect.origin.x == 120)
        #expect(rect.origin.y == -760)
        #expect(rect.width == 300)
        #expect(rect.height == 140)
    }
}
