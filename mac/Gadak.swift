// 가닥 — macOS 앱.
//
// 이 파일은 앱의 겉(창 · Dock 아이콘 · 메뉴)만 맡아요. 화면은 백엔드가 내주는 가닥 창을 그대로 보여 주고,
// 켜지면 백엔드(python -m backend.launch --shell)를 뒤에서 돌리고, 끄면 같이 꺼요.
//
// 만들기: python -m backend.macapp  (README 5-1)
// 어디의 백엔드를 어떤 파이썬으로 돌릴지는 Info.plist의 GadakRoot · GadakPython · GadakPath에 적혀 있어요.
// 환경 변수 GADAK_ROOT · GADAK_PYTHON이 있으면 그쪽이 이겨요(시험할 때).

import Cocoa
import WebKit

let env = ProcessInfo.processInfo.environment

func setting(_ key: String, _ envKey: String) -> String? {
    if let value = env[envKey], !value.isEmpty { return value }
    return Bundle.main.object(forInfoDictionaryKey: key) as? String
}

/// 종이색 바탕 (docs/design/tokens.css의 --bg). 화면이 뜨기 전에 흰색이 번쩍이지 않게 해요.
let paper = NSColor(name: nil) { appearance in
    appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        ? NSColor(srgbRed: 0x16 / 255, green: 0x15 / 255, blue: 0x13 / 255, alpha: 1)
        : NSColor(srgbRed: 0xFA / 255, green: 0xF9 / 255, blue: 0xF6 / 255, alpha: 1)
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate,
                         WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var status: NSTextField!
    var extra: [NSWindow] = []      // 판단 기록처럼 따로 뜬 창

    var backend: Process?
    var heard = ""                  // 백엔드가 한 말. 켜지지 않으면 이걸 보여 줘요
    var url: URL?
    var ours = false                // 이 앱이 켠 백엔드인지. 이미 켜져 있던 가닥에 붙었으면 false
    var quitting = false
    var watch: Timer?               // 붙어 있는 가닥이 살아 있는지 보는 시계
    var misses = 0

    // MARK: 켜기

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        buildWindow()
        startBackend()
    }

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "가닥"
        window.minSize = NSSize(width: 900, height: 600)
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.backgroundColor = paper
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("GadakMain")   // 다음에 켤 때 같은 자리 · 크기로

        let content = window.contentView!
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "gadak")          // 화면이 앱에 부탁하는 길 (복사)
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true  // 판단 기록 창
        webView = WKWebView(frame: content.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.underPageBackgroundColor = paper
        webView.allowsBackForwardNavigationGestures = true
        webView.isHidden = true
        if #available(macOS 13.3, *), env["GADAK_DEBUG"] == "1" { webView.isInspectable = true }
        content.addSubview(webView)

        status = NSTextField(labelWithString: "가닥을 켜는 중이에요…")
        status.font = .systemFont(ofSize: 14)
        status.textColor = .secondaryLabelColor
        status.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(status)
        NSLayoutConstraint.activate([
            status.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            status.centerYAnchor.constraint(equalTo: content.centerYAnchor),
        ])
        window.makeKeyAndOrderFront(nil)
    }

    /// Finder에서 켠 앱은 터미널과 달리 PATH가 짧아서 claude 같은 명령을 못 찾아요.
    /// 만들 때 적어 둔 PATH에 흔한 자리를 더해 백엔드에 넘겨요.
    func searchPath() -> String {
        let home = NSHomeDirectory()
        let baked = (setting("GadakPath", "GADAK_PATH") ?? "").split(separator: ":").map(String.init)
        let common = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        var seen = Set<String>()
        return (baked + common).filter { seen.insert($0).inserted }.joined(separator: ":")
    }

    func startBackend() {
        guard let root = setting("GadakRoot", "GADAK_ROOT"), let python = setting("GadakPython", "GADAK_PYTHON") else {
            return fail("이 앱에 가닥 폴더가 적혀 있지 않아요.", "가닥 폴더에서 ‘가닥 설치.command’를 다시 실행해 주세요.")
        }
        let files = FileManager.default
        guard files.fileExists(atPath: root + "/backend/launch.py"), files.isExecutableFile(atPath: python) else {
            return fail("가닥 폴더를 찾지 못했어요.",
                        "\(root)\n\n폴더를 옮기거나 이름을 바꿨다면, 그 폴더의 ‘가닥 설치.command’를 다시 실행해 주세요.")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        // --parent: 이 앱이 강제로 꺼져도 백엔드가 혼자 남지 않게 해요
        process.arguments = ["-u", "-m", "backend.launch", "--shell", "--parent", String(getpid())]
        process.currentDirectoryURL = URL(fileURLWithPath: root)
        var environment = env
        environment["PATH"] = searchPath()
        environment["PYTHONIOENCODING"] = "utf-8"
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async { self?.listen(text) }
        }
        process.terminationHandler = { [weak self] ended in
            let code = ended.terminationStatus
            // 마지막으로 한 말을 다 들은 다음에 판단해요
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { self?.backendEnded(code) }
        }
        do {
            try process.run()
            backend = process
        } catch {
            fail("파이썬을 실행하지 못했어요.", "\(python)\n\(error.localizedDescription)")
        }
    }

    /// 백엔드는 준비되면 “GADAK_READY <주소>”를, 이미 켜져 있던 가닥이 있으면 뒤에 “attached”를 붙여 말해요.
    func listen(_ text: String) {
        heard = String((heard + text).suffix(4000))
        guard url == nil else { return }
        for line in heard.split(whereSeparator: \.isNewline) where line.hasPrefix("GADAK_READY ") {
            let words = line.split(separator: " ")
            guard words.count >= 2, let address = URL(string: String(words[1])) else { continue }
            url = address
            ours = !(words.count >= 3 && words[2] == "attached")
            webView.load(URLRequest(url: address))
            if !ours { watchAttached() }
            return
        }
    }

    /// 터미널 같은 데서 먼저 켜 둔 가닥에 붙었을 때: 그쪽이 꺼지면 이 앱이 이어서 켜요.
    func watchAttached() {
        watch?.invalidate()
        misses = 0
        watch = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            guard let self = self, let address = self.url, !self.ours, self.backend == nil, !self.quitting else { return }
            var request = URLRequest(url: address.appendingPathComponent("health"))
            request.timeoutInterval = 2
            URLSession.shared.dataTask(with: request) { _, response, _ in
                let alive = (response as? HTTPURLResponse)?.statusCode == 200
                DispatchQueue.main.async { self.attachedAnswered(alive) }
            }.resume()
        }
    }

    func attachedAnswered(_ alive: Bool) {
        misses = alive ? 0 : misses + 1
        guard misses >= 2, backend == nil, !ours, !quitting else { return }
        watch?.invalidate()
        url = nil
        heard = ""
        startBackend()
    }

    func backendEnded(_ code: Int32) {
        backend = nil
        if quitting { return }
        if url != nil && !ours { return }                       // 이미 켜져 있던 가닥에 붙었어요. 알려 주고 끝난 거예요
        if url != nil && code == 0 { return NSApp.terminate(nil) }   // 화면의 ‘끄기’를 눌렀어요
        fail("가닥을 켜지 못했어요.", heard.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    func fail(_ message: String, _ detail: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = message
        alert.informativeText = String(detail.suffix(900))
        alert.addButton(withTitle: "종료")
        alert.runModal()
        NSApp.terminate(nil)
    }

    // MARK: 끄기

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    func windowWillClose(_ note: Notification) {
        guard let closed = note.object as? NSWindow else { return }
        if closed === window { NSApp.terminate(nil) } else { extra.removeAll { $0 === closed } }
    }

    func applicationWillTerminate(_ note: Notification) {
        quitting = true
        watch?.invalidate()
        if ours, let process = backend, process.isRunning { process.terminate() }
    }

    // MARK: 화면 (WKWebView)

    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        if view === webView {
            status.isHidden = true
            webView.isHidden = false
            snapshotIfAsked()
            evalIfAsked()
        } else if let title = view.title, !title.isEmpty {
            view.window?.title = title
        }
    }

    func webView(_ view: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        // 백엔드가 꺼져 있어요(붙어 있던 가닥을 다른 곳에서 끈 경우). 이 앱이 다시 켜요
        guard view === webView, backend == nil, !quitting else { return }
        webView.isHidden = true
        status.isHidden = false
        url = nil
        heard = ""
        startBackend()
    }

    func webViewWebContentProcessDidTerminate(_ view: WKWebView) { view.reload() }

    /// 가닥 창 밖으로 나가는 링크는 기본 브라우저로 열어요.
    func webView(_ view: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let target = action.request.url, let host = target.host, host != url?.host,
           target.scheme == "http" || target.scheme == "https" {
            NSWorkspace.shared.open(target)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    /// window.open(판단 기록)은 창을 하나 더 띄워요.
    func webView(_ view: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        let popup = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable],
                             backing: .buffered, defer: false)
        popup.title = "가닥"
        popup.isReleasedWhenClosed = false
        popup.tabbingMode = .disallowed
        popup.backgroundColor = paper
        popup.delegate = self
        let child = WKWebView(frame: popup.contentView!.bounds, configuration: configuration)
        child.autoresizingMask = [.width, .height]
        child.navigationDelegate = self
        child.uiDelegate = self
        child.underPageBackgroundColor = paper
        popup.contentView!.addSubview(child)
        popup.center()
        popup.makeKeyAndOrderFront(nil)
        extra.append(popup)
        return child
    }

    func webViewDidClose(_ view: WKWebView) { view.window?.close() }

    /// 실행 버튼은 글을 클립보드에 담아요(shared/ui/mark.js의 G.copy). 웹 화면의 복사는 막힐 때가 있어서 앱이 직접 담아요.
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "gadak", let body = message.body as? [String: Any], let text = body["copy"] as? String else { return }
        let board = NSPasteboard.general
        board.clearContents()
        board.setString(text, forType: .string)
    }

    /// 찾은 곳 → 파일 고르기 (<input type="file">)
    func webView(_ view: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: view.window ?? window) { answer in
            completionHandler(answer == .OK ? panel.urls : nil)
        }
    }

    /// 화면 확인용: GADAK_SNAPSHOT=파일.png 로 켜면 화면이 뜬 뒤 그림으로 남겨요. GADAK_SNAPSHOT_QUIT=1 이면 남기고 꺼요.
    func snapshotIfAsked() {
        guard let path = env["GADAK_SNAPSHOT"], !path.isEmpty else { return }
        let wait = Double(env["GADAK_SNAPSHOT_WAIT"] ?? "") ?? 3
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [self] in
            webView.takeSnapshot(with: nil) { image, _ in
                if let tiff = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
                   let png = bitmap.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: path))
                }
                if env["GADAK_SNAPSHOT_QUIT"] == "1" { NSApp.terminate(nil) }
            }
        }
    }

    /// 확인용(GADAK_DEBUG=1): GADAK_EVAL에 적은 자바스크립트를 화면이 뜬 뒤 돌리고 결과를 적어요.
    func evalIfAsked() {
        guard env["GADAK_DEBUG"] == "1", let script = env["GADAK_EVAL"], !script.isEmpty else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [self] in
            webView.evaluateJavaScript(script) { result, error in
                print("GADAK_DEBUG eval \(result ?? "nil") \(error?.localizedDescription ?? "")")
                fflush(stdout)
            }
        }
    }

    // MARK: 메뉴

    @objc func reloadPage(_ sender: Any?) { if url != nil { webView.reload() } }
    @objc func pageBack(_ sender: Any?) { webView.goBack() }
    @objc func pageForward(_ sender: Any?) { webView.goForward() }
    @objc func zoomReset(_ sender: Any?) { webView.pageZoom = 1 }
    @objc func zoomIn(_ sender: Any?) { webView.pageZoom = min(webView.pageZoom + 0.1, 2) }
    @objc func zoomOut(_ sender: Any?) { webView.pageZoom = max(webView.pageZoom - 0.1, 0.6) }

    func buildMenu() {
        let bar = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String = "",
                  _ modifiers: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: key)
            entry.keyEquivalentModifierMask = modifiers
            return entry
        }
        @discardableResult func menu(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let list = NSMenu(title: title)
            items.forEach(list.addItem)
            let top = NSMenuItem()
            top.submenu = list
            bar.addItem(top)
            return list
        }
        menu("가닥", [
            item("가닥에 관하여", #selector(NSApplication.orderFrontStandardAboutPanel(_:))),
            .separator(),
            item("가닥 가리기", #selector(NSApplication.hide(_:)), "h"),
            item("기타 가리기", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("모두 보기", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("가닥 종료", #selector(NSApplication.terminate(_:)), "q"),
        ])
        menu("편집", [
            item("실행 취소", Selector(("undo:")), "z"),
            item("실행 복귀", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("오려두기", #selector(NSText.cut(_:)), "x"),
            item("복사하기", #selector(NSText.copy(_:)), "c"),
            item("붙여넣기", #selector(NSText.paste(_:)), "v"),
            item("전체 선택", #selector(NSText.selectAll(_:)), "a"),
        ])
        menu("보기", [
            item("다시 읽기", #selector(reloadPage(_:)), "r"),
            item("뒤로", #selector(pageBack(_:)), "["),
            item("앞으로", #selector(pageForward(_:)), "]"),
            .separator(),
            item("실제 크기", #selector(zoomReset(_:)), "0"),
            item("확대", #selector(zoomIn(_:)), "+"),
            item("축소", #selector(zoomOut(_:)), "-"),
        ])
        let windows = menu("윈도우", [
            item("최소화", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("확대/축소", #selector(NSWindow.performZoom(_:))),
            .separator(),
            item("닫기", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.mainMenu = bar
        NSApp.windowsMenu = windows
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

// kill로 끄라고 해도 백엔드를 같이 끄고 나가요
signal(SIGTERM, SIG_IGN)
let terminated = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
terminated.setEventHandler { NSApp.terminate(nil) }
terminated.resume()

if env["GADAK_DEBUG"] == "1" {
    // 화면 쪽 요청(새 창 · 파일 고르기 · 바깥 링크)을 이 앱이 받는지 확인해요
    for name in ["webView:createWebViewWithConfiguration:forNavigationAction:windowFeatures:",
                 "webView:runOpenPanelWithParameters:initiatedByFrame:completionHandler:",
                 "webView:decidePolicyForNavigationAction:decisionHandler:",
                 "webView:didFinishNavigation:", "webView:didFailProvisionalNavigation:withError:"] {
        print("GADAK_DEBUG responds \(delegate.responds(to: Selector((name)))) \(name)")
    }
    fflush(stdout)
}
app.run()
