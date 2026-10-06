import AppKit

/// An iTerm2 tab running Claude Code, found by matching iTerm2's sessions to `claude` processes by tty.
struct ItermTab: Sendable, Equatable {
    let tty: String     // "/dev/ttys008": the pill key, stable when iTerm2 restarts and restores the tab
    let uuid: String    // iTerm2 session `unique id` (the part after ":" in ITERM_SESSION_ID)
    let title: String   // tab title set by Claude Code, cleaned of the status glyph and " (claude)"
    let cwd: String
}

/// Keeps one pill per iTerm2 tab running Claude Code, including tabs that are idle and have not sent
/// any hook event since Coucou started. Rescans every few seconds while iTerm2 is running; hooks keep
/// driving the live state in between.
@MainActor
final class ItermScanner {
    static let shared = ItermScanner()
    private var timer: Timer?
    private var scanning = false
    private static let interval: TimeInterval = 10

    func start() {
        guard timer == nil else { return }
        scan()
        timer = Timer.scheduledTimer(withTimeInterval: Self.interval, repeats: true) { _ in
            Task { @MainActor in ItermScanner.shared.scan() }
        }
    }

    func scan() {
        guard !scanning else { return }
        let itermRunning = NSWorkspace.shared.runningApplications
            .contains { $0.bundleIdentifier == "com.googlecode.iterm2" }
        guard itermRunning else {
            HookServer.shared.syncItermTabs([])
            return
        }
        scanning = true
        Task.detached(priority: .utility) {
            let tabs = ItermScanner.collect()
            await MainActor.run {
                ItermScanner.shared.scanning = false
                // nil = the scan itself failed (e.g. Automation permission denied): keep the pills we have.
                if let tabs { HookServer.shared.syncItermTabs(tabs) }
            }
        }
    }

    // MARK: - Collection (background)

    nonisolated static func collect() -> [ItermTab]? {
        // 1. claude processes by tty
        guard let ps = run("/bin/ps", ["-axo", "pid=,tty=,comm="]) else { return nil }
        var pidByTty: [String: String] = [:]
        for line in ps.split(separator: "\n") {
            let f = line.split(separator: " ", omittingEmptySubsequences: true)
            guard f.count >= 3, f[1] != "??",
                  (f[2...].joined(separator: " ") as NSString).lastPathComponent == "claude" else { continue }
            pidByTty["/dev/\(f[1])"] = String(f[0])
        }
        guard !pidByTty.isEmpty else { return [] }

        // 2. iTerm2 sessions: window id, tab number, uuid, tty, title.
        //    Windows come front-to-back, so they are re-sorted by id to keep the pill order stable.
        // The separator is set outside the tell block: inside it, `tab` means an iTerm2 tab, not a tab character.
        let script = """
        set out to ""
        set sep to tab
        tell application id "com.googlecode.iterm2"
            repeat with w in windows
                set n to 0
                repeat with t in tabs of w
                    set n to n + 1
                    repeat with s in sessions of t
                        set out to out & (id of w) & sep & n & sep & (unique id of s) & sep & (tty of s) & sep & (name of s) & linefeed
                    end repeat
                end repeat
            end repeat
        end tell
        return out
        """
        guard let sessions = run("/usr/bin/osascript", ["-e", script]) else { return nil }

        // 3. working directory of each claude process
        let cwdByPid = workingDirectories(pids: Array(pidByTty.values))

        var found: [(window: Int, tab: Int, item: ItermTab)] = []
        for line in sessions.split(separator: "\n") {
            let f = line.split(separator: "\t", maxSplits: 4, omittingEmptySubsequences: false).map(String.init)
            guard f.count == 5, let pid = pidByTty[f[3]] else { continue }
            found.append((Int(f[0]) ?? 0, Int(f[1]) ?? 0,
                          ItermTab(tty: f[3], uuid: f[2], title: cleanTitle(f[4]), cwd: cwdByPid[pid] ?? "")))
        }
        return found.sorted { ($0.window, $0.tab) < ($1.window, $1.tab) }.map(\.item)
    }

    /// "✳ Age verification go.cam (claude)" → "Age verification go.cam".
    nonisolated static func cleanTitle(_ raw: String) -> String {
        var t = raw.trimmingCharacters(in: .whitespaces)
        if t.hasSuffix("(claude)") { t = String(t.dropLast("(claude)".count)) }
        // Claude Code prefixes a status glyph (✳ idle, ◐◓◑◒ / braille spinner while working).
        while let c = t.unicodeScalars.first, !CharacterSet.alphanumerics.contains(c),
              !"\"'([«".unicodeScalars.contains(c) {
            t.unicodeScalars.removeFirst()
        }
        t = t.trimmingCharacters(in: .whitespaces)
        return t == "claude" || t == "Claude Code" ? "" : t
    }

    private nonisolated static func workingDirectories(pids: [String]) -> [String: String] {
        guard !pids.isEmpty,
              let out = run("/usr/sbin/lsof", ["-a", "-d", "cwd", "-p", pids.joined(separator: ","), "-Fpn"])
        else { return [:] }
        var result: [String: String] = [:]
        var pid = ""
        for line in out.split(separator: "\n") {
            if line.hasPrefix("p") { pid = String(line.dropFirst()) }
            else if line.hasPrefix("n"), !pid.isEmpty { result[pid] = String(line.dropFirst()) }
        }
        return result
    }

    private nonisolated static func run(_ path: String, _ args: [String]) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        // lsof exits 1 when some pid has gone away but still prints the others.
        guard p.terminationStatus == 0 || path.hasSuffix("lsof") else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
