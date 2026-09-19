// One-shot, read-only desktop visibility probe. No network, screenshots,
// Accessibility, notifications, timers or sleep-prevention assertions.
import AppKit
import CoreGraphics

func visibilitySnapshot() -> [String: Bool]? {
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any],
          let onConsole = session[kCGSessionOnConsoleKey as String] as? Bool else {
        return nil
    }
    let locked = session["CGSSessionScreenIsLocked"] as? Bool ?? false
    var count: UInt32 = 0
    guard CGGetOnlineDisplayList(0, nil, &count) == .success else { return nil }
    var displays = [CGDirectDisplayID](repeating: 0, count: Int(max(count, 1)))
    guard CGGetOnlineDisplayList(UInt32(displays.count), &displays, &count) == .success else { return nil }
    let awake = displays.prefix(Int(count)).filter {
        CGDisplayIsActive($0) != 0 && CGDisplayIsAsleep($0) == 0
    }

    // Process existence alone is insufficient: modern screen savers can stay
    // resident as wallpaper. Inspect on-screen window metadata, never pixels
    // or window titles (which would need Screen Recording permission).
    guard let windows = CGWindowListCopyWindowInfo(
        [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
    ) as? [[String: Any]] else { return nil }
    let saverLevel = Int(CGWindowLevelForKey(.screenSaverWindow))
    let saver = windows.contains { window in
        guard let layer = window[kCGWindowLayer as String] as? Int,
              layer >= saverLevel,
              let bounds = window[kCGWindowBounds as String] as? NSDictionary,
              let rect = CGRect(dictionaryRepresentation: bounds),
              (window[kCGWindowAlpha as String] as? Double ?? 1) > 0 else { return false }
        // Also catches third-party screen savers. Small floating panels at the
        // same level do not hide a whole display and must not pause refresh.
        return awake.contains { id in
            let display = CGDisplayBounds(id)
            let intersection = rect.intersection(display)
            return !intersection.isNull && display.width > 0 && display.height > 0
                && intersection.width * intersection.height >= display.width * display.height * 0.95
        }
    }
    return ["session_active": onConsole, "locked": locked,
            "display_awake": !awake.isEmpty, "screensaver": saver,
            "menu_bar_visible": NSMenu.menuBarVisible()]
}

if let snapshot = visibilitySnapshot(),
   let data = try? JSONSerialization.data(withJSONObject: snapshot, options: [.sortedKeys]),
   let text = String(data: data, encoding: .utf8) {
    print(text)
} else {
    print("{}") // The caller pauses polling when the desktop cannot be verified.
}
