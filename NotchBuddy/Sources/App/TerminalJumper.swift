import AppKit

/// Brings a session's terminal to the front.
/// iTerm2 sessions jump to their exact window and tab (from ITERM_SESSION_ID);
/// anything else activates the first terminal app that is running.
@MainActor
enum TerminalJumper {
    static let terminalBundleIds = ["com.apple.Terminal", "com.googlecode.iterm2",
                                    "net.kovidgoyal.kitty", "com.mitchellh.ghostty"]

    /// Returns false when no terminal was brought forward.
    @discardableResult
    static func open(_ task: AgentTask?, launchTerminalIfNone: Bool = false) -> Bool {
        if let sid = task?.terminalSessionId, focusItermSession(sid) { return true }
        if let hit = terminalBundleIds.compactMap({ id in
            NSWorkspace.shared.runningApplications.first { $0.bundleIdentifier == id }
        }).first {
            hit.activate(options: .activateIgnoringOtherApps)
            return true
        }
        if launchTerminalIfNone {
            NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"))
            return true
        }
        return false
    }

    /// The key is the tab's tty ("/dev/ttys008") or, for older events, ITERM_SESSION_ID ("w0t3p0:15A23CA3-…",
    /// whose part after the colon is iTerm2's AppleScript `unique id`).
    private static func focusItermSession(_ key: String) -> Bool {
        guard NSWorkspace.shared.runningApplications.contains(where: { $0.bundleIdentifier == "com.googlecode.iterm2" })
        else { return false }
        let match: String
        if key.hasPrefix("/dev/ttys"), key.dropFirst(9).allSatisfy(\.isNumber) {
            match = "tty of s is \"\(key)\""
        } else if let uuid = key.split(separator: ":").last, !uuid.isEmpty,
                  uuid.allSatisfy({ $0.isHexDigit || $0 == "-" }) {
            match = "unique id of s is \"\(uuid)\""
        } else {
            return false
        }
        let source = """
        tell application id "com.googlecode.iterm2"
            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if \(match) then
                            select w
                            select t
                            select s
                            activate
                            return true
                        end if
                    end repeat
                end repeat
            end repeat
        end tell
        return false
        """
        var error: NSDictionary?
        let result = NSAppleScript(source: source)?.executeAndReturnError(&error)
        if let error {
            NSLog("[Coucou] iTerm2 jump failed: \(error[NSAppleScript.errorMessage] ?? "unknown")")
            return false
        }
        return result?.booleanValue == true
    }
}
