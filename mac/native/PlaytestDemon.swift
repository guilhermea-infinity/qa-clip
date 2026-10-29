import AppKit
@preconcurrency import WebKit
import UniformTypeIdentifiers

@main
struct PlaytestDemon {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var process: Process?
    var logHandle: FileHandle?
    var loaded = false
    var quitting = false
    var attempts = 0
    var port = 8800
    var inbox = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Desktop/QA-Inbox")
    var testMode = false
    var uiTestMode = false
    var logURL: URL!
    var feedbackDownloads: [ObjectIdentifier: (temporary: URL, destination: URL)] = [:]
    var deskURL: URL { URL(string: "http://127.0.0.1:\(port)")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = ProcessInfo.processInfo.arguments
        testMode = args.contains("--smoke-test")
        uiTestMode = args.contains("--ui-smoke-test")
        if let i = args.firstIndex(of: "--inbox"), i + 1 < args.count { inbox = URL(fileURLWithPath: args[i + 1]).standardizedFileURL }
        if let i = args.firstIndex(of: "--port"), i + 1 < args.count, let value = Int(args[i + 1]), (1024...65535).contains(value) { port = value }
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Playtest Demon")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        logURL = logs.appendingPathComponent((testMode || uiTestMode) ? "smoke-test.log" : "desk.log")
        makeMenus()
        makeWindow()
        if !testMode { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
        checkExisting()
    }

    func makeWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1360, height: 900), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Playtest Demon"
        window.minSize = NSSize(width: 760, height: 600)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        window.backgroundColor = NSColor(red: 13/255, green: 20/255, blue: 27/255, alpha: 1)
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        web = WKWebView(frame: window.contentView!.bounds, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window.contentView = web
        web.loadHTMLString("<body style='background:#0d141b;color:#edf5f6;font:17px -apple-system;display:grid;place-content:center;height:95vh'><div><h1 style='color:#c2a0ff'>😈 Playtest Demon</h1><p>Starting your playtest workspace…</p></div></body>", baseURL: nil)
    }

    func makeMenus() {
        let bar = NSMenu()
        let appItem = NSMenuItem(); bar.addItem(appItem)
        let menu = NSMenu(title: "Playtest Demon"); appItem.submenu = menu
        menu.addItem(withTitle: "About Playtest Demon", action: #selector(about), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Show Workspace", action: #selector(showWindow), keyEquivalent: "1")
        let importItem = menu.addItem(withTitle: "Import Recording…", action: #selector(importClip), keyEquivalent: "o"); importItem.target = self
        menu.addItem(withTitle: "Open in Browser", action: #selector(openBrowser), keyEquivalent: "")
        menu.addItem(withTitle: "Open Inbox", action: #selector(openInbox), keyEquivalent: "")
        menu.addItem(withTitle: "Open Logs", action: #selector(openLogs), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Hide Playtest Demon", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        menu.addItem(withTitle: "Quit Playtest Demon", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for item in menu.items where [#selector(about), #selector(showWindow), #selector(openBrowser), #selector(openInbox), #selector(openLogs)].contains(item.action) { item.target = self }
        let editItem = NSMenuItem(); bar.addItem(editItem)
        let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let viewItem = NSMenuItem(); bar.addItem(viewItem)
        let view = NSMenu(title: "View"); viewItem.submenu = view
        let reload = view.addItem(withTitle: "Reload Workspace", action: #selector(reloadPage), keyEquivalent: "r"); reload.target = self
        let back = view.addItem(withTitle: "Back", action: #selector(backPage), keyEquivalent: "["); back.target = self
        let windowItem = NSMenuItem(); bar.addItem(windowItem)
        let windows = NSMenu(title: "Window"); windowItem.submenu = windows
        windows.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windows.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        NSApp.windowsMenu = windows
        NSApp.mainMenu = bar
    }

    func request(_ path: String, completion: @escaping (Data?, HTTPURLResponse?, Error?) -> Void) {
        var req = URLRequest(url: deskURL.appendingPathComponent(path))
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { data, response, error in
            DispatchQueue.main.async { completion(data, response as? HTTPURLResponse, error) }
        }.resume()
    }

    func checkExisting() {
        request("api/health") { data, response, error in
            if error != nil { self.startService(); return }
            guard response?.statusCode == 200,
                  let data = data, let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  info["app"] as? String == "playtest-demon",
                  info["inbox"] as? String == self.inbox.resolvingSymlinksInPath().path else {
                self.fail("Port \(self.port) is occupied by another desk or application. Quit the old Terminal-launched desk once, then reopen Playtest Demon.")
                return
            }
            self.ready()
        }
    }

    func startService() {
        guard let resource = Bundle.main.resourceURL else { fail("The app’s resources are missing. Reinstall the app."); return }
        let executable = resource.appendingPathComponent("service/PlaytestDemonService")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else { fail("The bundled service is missing. Reinstall the app."); return }
        let previous = logURL.deletingLastPathComponent().appendingPathComponent("desk.previous.log")
        if !testMode && !uiTestMode, let attrs = try? FileManager.default.attributesOfItem(atPath: logURL.path), let size = attrs[.size] as? NSNumber, size.intValue > 5_000_000 {
            try? FileManager.default.removeItem(at: previous)
            try? FileManager.default.moveItem(at: logURL, to: previous)
        }
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        do {
            let handle = try FileHandle(forWritingTo: logURL); handle.seekToEndOfFile(); logHandle = handle
            let child = Process(); child.executableURL = executable
            child.arguments = ["--inbox", inbox.path, "--port", String(port), "--no-open"]
            if testMode || uiTestMode { child.arguments! += ["--no-inbox", "--paused"] }
            var env = ProcessInfo.processInfo.environment
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            env["PATH"] = [home + "/.local/bin", home + "/.npm-global/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin", env["PATH"] ?? ""].joined(separator: ":")
            env["PYTHONUNBUFFERED"] = "1"
            env["PLAYTEST_DEMON_APP_PID"] = String(ProcessInfo.processInfo.processIdentifier)
            child.environment = env
            child.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
            child.standardInput = FileHandle.nullDevice
            child.standardOutput = handle; child.standardError = handle
            child.terminationHandler = { p in DispatchQueue.main.async {
                if !self.quitting { self.fail("The desk stopped (exit \(p.terminationStatus)). Open Logs for details, then reopen the app.") }
            }}
            try child.run(); process = child
            attempts = 0; waitForService()
        } catch { fail("Could not start the desk: \(error.localizedDescription)") }
    }

    func waitForService() {
        guard !quitting else { return }
        request("api/health") { data, response, _ in
            if response?.statusCode == 200, let data = data,
               let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any], info["app"] as? String == "playtest-demon",
               info["inbox"] as? String == self.inbox.resolvingSymlinksInPath().path { self.ready(); return }
            self.attempts += 1
            if self.attempts == 100 {
                self.web.loadHTMLString("<body style='background:#0d141b;color:#edf5f6;font:17px -apple-system;padding:60px'><h1>Waiting for macOS access…</h1><p>If macOS asks, allow Playtest Demon to access your Desktop folder so it can open your inbox.</p><p>Keep this window open. Setup continues automatically after permission is granted.</p></body>", baseURL: nil)
            }
            if self.attempts > 1000 { self.fail("The desk is still waiting after several minutes. Approve any macOS folder-access prompt, then reopen the app. Open Logs for details."); return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitForService() }
        }
    }

    func ready() {
        loaded = true
        if testMode {
            print("APP_SMOKE_OK: bundled service healthy; no Terminal or source checkout required")
            NSApp.terminate(nil); return
        }
        web.load(URLRequest(url: URL(string: deskURL.absoluteString + "/?native=1#videos")!))
    }

    func fail(_ message: String) {
        guard !quitting else { return }
        if testMode || uiTestMode { fputs("APP_SMOKE_FAILED: \(message)\n", stderr); shutdown(); exit(1) }
        let alert = NSAlert(); alert.messageText = "Playtest Demon needs attention"; alert.informativeText = message
        alert.addButton(withTitle: "Open Logs"); alert.addButton(withTitle: "Quit")
        if alert.runModal() == .alertFirstButtonReturn { openLogs() }
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if testMode || uiTestMode || !loaded { return .terminateNow }
        web.evaluateJavaScript("typeof dirty !== 'undefined' && (Object.keys(dirty).length > 0 || !!upload)") { value, _ in
            self.request("api/state") { data, _, _ in
                let state = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
                let runs = state?["runs"] as? [[String: Any]] ?? []
                let busy = (state?["working"] as? [String: Any]) != nil || runs.contains { ["preparing", "fixing", "testing", "publishing"].contains($0["status"] as? String ?? "") }
                if value as? Bool == true || (busy && self.process != nil) {
                    let alert = NSAlert(); alert.messageText = "Quit Playtest Demon?"
                    alert.informativeText = "There are unsaved edits, an upload, or work in progress. Keep the app open to finish. Interrupted analysis resumes on launch; coding runs need recovery."
                    alert.addButton(withTitle: "Keep Open"); alert.addButton(withTitle: "Quit")
                    NSApp.reply(toApplicationShouldTerminate: alert.runModal() == .alertSecondButtonReturn)
                } else { NSApp.reply(toApplicationShouldTerminate: true) }
            }
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { shutdown() }
    func shutdown() {
        quitting = true
        guard let child = process, child.isRunning else { return }
        child.terminate()
        let until = Date().addingTimeInterval(7)
        while child.isRunning && Date() < until { Thread.sleep(forTimeInterval: 0.05) }
        // qa-desk handles SIGTERM and cleans up receiver / provider processes.
        if child.isRunning { kill(child.processIdentifier, SIGKILL) }
        try? logHandle?.close()
    }

    @objc func showWindow() { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    @objc func importClip() { if loaded { showWindow(); web.evaluateJavaScript("openImport()", completionHandler: nil) } }
    @objc func openBrowser() { NSWorkspace.shared.open(deskURL) }
    @objc func openInbox() { try? FileManager.default.createDirectory(at: inbox, withIntermediateDirectories: true); NSWorkspace.shared.open(inbox) }
    @objc func openLogs() { NSWorkspace.shared.open(logURL.deletingLastPathComponent()) }
    @objc func about() { NSApp.orderFrontStandardAboutPanel(options: [.applicationName: "Playtest Demon", .applicationVersion: "0.7.0", .credits: NSAttributedString(string: "Infinity Games · Speak. Review. Ship. Repeat.")]) }
    @objc func backPage() { if web.canGoBack { web.goBack() } }
    @objc func reloadPage() {
        web.evaluateJavaScript("typeof dirty !== 'undefined' && Object.keys(dirty).length > 0") { value, _ in
            if value as? Bool == true {
                let alert = NSAlert(); alert.messageText = "You have unsaved changes"; alert.informativeText = "Wait for changes to save before reloading."
                alert.addButton(withTitle: "Keep Editing"); alert.runModal(); return
            }
            self.web.reload()
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host == "127.0.0.1" && url.port == port && url.scheme == "http" {
            decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow); return
        }
        if url.scheme == "about" { decisionHandler(.allow); return }
        if ["https", "http"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if let response = navigationResponse.response as? HTTPURLResponse,
           response.url?.host == "127.0.0.1", response.url?.port == port,
           response.value(forHTTPHeaderField: "Content-Disposition")?.hasPrefix("attachment;") == true {
            decisionHandler(.download); return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              response.mimeType == "application/zip" else {
            completionHandler(nil); shareNotice("Could not export feedback. Reopen Share feedback and retry."); return
        }
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.allowedContentTypes = [.zip]; panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let destination = panel.url else {
                completionHandler(nil); self.shareNotice("Export cancelled. Your feedback is unchanged."); return
            }
            // WebKit requires a new destination. Stage the download before replacing an older export.
            let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("playtest-feedback-\(UUID().uuidString).zip")
            self.feedbackDownloads[ObjectIdentifier(download)] = (temporary, destination)
            completionHandler(temporary)
        }
    }
    func downloadDidFinish(_ download: WKDownload) {
        guard let paths = feedbackDownloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        do {
            if FileManager.default.fileExists(atPath: paths.destination.path) {
                _ = try FileManager.default.replaceItemAt(paths.destination, withItemAt: paths.temporary)
            } else {
                try FileManager.default.moveItem(at: paths.temporary, to: paths.destination)
            }
            shareNotice("ZIP saved. Attach it to your Slack message.")
        } catch {
            try? FileManager.default.removeItem(at: paths.temporary)
            shareNotice("Could not save the ZIP. Try another location: " + error.localizedDescription)
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let paths = feedbackDownloads.removeValue(forKey: ObjectIdentifier(download)) { try? FileManager.default.removeItem(at: paths.temporary) }
        if (error as NSError).code != NSURLErrorCancelled { shareNotice("Export failed. Try again: " + error.localizedDescription) }
    }
    func shareNotice(_ message: String) {
        guard let data = try? JSONSerialization.data(withJSONObject: [message]), let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("document.querySelector('#shareStatus').textContent = \(json)[0]", completionHandler: nil)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.canChooseDirectories = parameters.allowsDirectories; panel.canChooseFiles = true; panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard uiTestMode, webView.url?.host == "127.0.0.1" else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            self.web.evaluateJavaScript("JSON.stringify({title:document.title,views:document.querySelectorAll('nav button').length,online:document.querySelector('#deskConnection')?.textContent})") { value, error in
                if let error = error { self.fail(error.localizedDescription); return }
                guard let text = value as? String, text.contains("Playtest Demon"), text.contains("online") else { self.fail("UI did not become ready: \(String(describing: value))"); return }
                print("APP_UI_SMOKE_OK: \(text)"); NSApp.terminate(nil)
            }
        }
    }
}
