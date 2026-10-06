// 떠 있는 가닥 버튼(mac/Float.swift)을 앱이 스스로 확인하는 길.
//
// 마우스를 직접 움직일 수 없는 곳(터미널 · 자동 확인)에서 쓰려고 둔 것이에요. 가닥 앱을 GADAK_FLOAT_SNAPSHOT=폴더 로 켜면
// 아래를 차례로 해 보고, 결과를 “GADAK_FLOAT …” 줄로 적고, 그림을 그 폴더에 남긴 뒤 꺼요. 평소에는 돌지 않아요.
// 시험용 포트 · 시험용 기록 폴더로 켜서 써요 (GADAK_PORT · GADAK_HOME — 쓰던 가닥을 건드리지 않게).

import Cocoa
import WebKit

extension FloatController {
    /// 확인을 시작할 때 사용자가 쓰고 있던 앱. ‘다른 앱을 쓰는 중’을 흉내 낼 때 앞자리를 여기에 돌려줘요
    fileprivate static var userApp: NSRunningApplication?

    /// 버튼들이 든 창을 그림으로. backdrop이 있으면 그 색 위에 올리고, 화면 밖으로 나간 쪽(보이지 않는 쪽)은 검게 칠해요
    func picture(over backdrop: NSColor?) -> NSBitmapImageRep? {
        let view = panel.contentView!
        guard let image = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return nil }
        view.cacheDisplay(in: view.bounds, to: image)
        guard let backdrop = backdrop else { return image }
        let size = view.bounds.size, whole = NSRect(origin: .zero, size: size)
        let canvas = NSImage(size: size)
        canvas.lockFocus()
        backdrop.setFill()
        whole.fill()
        image.draw(in: whole, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        let inside = screen.frame.offsetBy(dx: -panel.frame.minX, dy: -panel.frame.minY)
        NSColor.black.setFill()
        for part in [NSRect(x: 0, y: 0, width: max(inside.minX, 0), height: size.height),
                     NSRect(x: inside.maxX, y: 0, width: max(size.width - inside.maxX, 0), height: size.height),
                     NSRect(x: 0, y: 0, width: size.width, height: max(inside.minY, 0)),
                     NSRect(x: 0, y: inside.maxY, width: size.width, height: max(size.height - inside.maxY, 0))] {
            part.fill()
        }
        canvas.unlockFocus()
        return canvas.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0) }
    }

    /// 그림 여러 장을 한 장에 나란히 (칸마다 버튼 창 하나)
    func sheet(_ cells: [NSBitmapImageRep?], columns: Int) -> Data? {
        let rows = (cells.count + columns - 1) / columns, side = floatSide, gap: CGFloat = 6
        let canvas = NSImage(size: NSSize(width: CGFloat(columns) * (side + gap) + gap, height: CGFloat(rows) * (side + gap) + gap))
        canvas.lockFocus()
        NSColor(white: 0.5, alpha: 1).setFill()
        NSRect(origin: .zero, size: canvas.size).fill()
        for (index, cell) in cells.enumerated() {
            let column = CGFloat(index % columns), row = CGFloat(rows - 1 - index / columns)
            cell?.draw(in: NSRect(x: gap + column * (side + gap), y: gap + row * (side + gap), width: side, height: side),
                       from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        }
        canvas.unlockFocus()
        return canvas.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0)?.representation(using: .png, properties: [:]) }
    }

    /// GADAK_FLOAT_SNAPSHOT=폴더 로 켜면 혼자 확인하고 꺼요: 가장자리마다 걸친 모양 · 펼친 모양을 그림으로 남기고, 펼친 버튼이
    /// 화면 안에 있고 서로 겹치지 않는지 재고, 마우스를 흉내 내어 올리기 · 누르기 · 끌기를 순서대로 해 보고,
    /// 버튼은 이 창이 받고 빈 자리는 아래 앱이 받는지 재고, 노선도 창을 그림으로 남겨요.
    func selfTest(_ folder: String) {
        let out = URL(fileURLWithPath: folder)
        func write(_ name: String, _ data: Data?) { try? data?.write(to: out.appendingPathComponent(name)) }
        func note(_ text: String) { print("GADAK_FLOAT \(text)"); fflush(stdout) }
        func later(_ seconds: Double, _ work: @escaping () -> Void) { DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work) }
        let kept = (edge, along, screenIndex)
        let mine = NSRunningApplication.current
        let front = NSWorkspace.shared.frontmostApplication
        FloatController.userApp = front != mine ? front : NSWorkspace.shared.runningApplications.first {
            $0.bundleIdentifier == "com.apple.finder"
        }
        testing = true
        monitors.forEach { NSEvent.removeMonitor($0) }      // 확인하는 동안 진짜 클릭에 접히지 않게
        monitors = []
        let hidden = notch().map { "\(Int($0.lowerBound))…\(Int($0.upperBound))" } ?? "none"
        note("panel level=\(panel.level.rawValue) want=\(NSWindow.Level.statusBar.rawValue) visible=\(panel.isVisible) hidesOnDeactivate=\(panel.hidesOnDeactivate) frame=\(NSStringFromRect(panel.frame)) screen=\(NSStringFromRect(screen.frame)) safeTop=\(screen.safeAreaInsets.top) notch=\(hidden)")

        // 그림: 밝게 · 어둡게, 가장자리마다 걸친 모양(윗줄)과 펼친 모양(아랫줄). 바탕은 어두운 앱과 밝은 앱 둘 다
        setTodo(2)
        for (name, look) in [("dark", NSAppearance.Name.darkAqua), ("light", .aqua)] {
            panel.appearance = NSAppearance(named: look)
            for (ground, backdrop) in [("dark", NSColor(white: 0.13, alpha: 1)), ("light", NSColor(white: 0.96, alpha: 1))] {
                var cells: [NSBitmapImageRep?] = []
                for shape in [Mode.peek, .menu] {
                    for side in FloatEdge.allCases {
                        edge = side; along = 0.3; mode = shape; place(); layout(animated: false)
                        cells.append(picture(over: backdrop))
                    }
                }
                write("buttons-\(name)-on-\(ground).png", sheet(cells, columns: 4))
            }
        }
        panel.appearance = nil
        setTodo(0)

        // 펼친 버튼이 화면 안에 있는지, 서로 겹치지 않는지, 카메라 자리에 가리지 않는지
        var outside = 0, overlap = 0, covered = 0
        for side in FloatEdge.allCases {
            for position in [CGFloat(0), 0.3, 0.5, 1] {
                edge = side; along = position; mode = .menu; place(); layout(animated: false)
                let frame = screen.frame
                let discs: [(NSPoint, CGFloat)] = ((satellites as [DiscView]) + [bubble]).map { view in
                    (NSPoint(x: panel.frame.minX + view.frame.midX, y: panel.frame.minY + view.frame.midY), view.diameter / 2)
                }
                for (middle, radius) in discs {
                    if !frame.insetBy(dx: radius, dy: radius).contains(middle) { outside += 1 }
                    if let gap = notch(), middle.y + radius > frame.maxY - screen.safeAreaInsets.top,
                       middle.x + radius > gap.lowerBound, middle.x - radius < gap.upperBound { covered += 1 }
                }
                for a in discs.indices {
                    for b in discs.indices where b > a {
                        if hypot(discs[a].0.x - discs[b].0.x, discs[a].0.y - discs[b].0.y) < discs[a].1 + discs[b].1 + 4 { overlap += 1 }
                    }
                }
                if side == .top {
                    mode = .peek; layout(animated: false)
                    let at = bubbleCenter()
                    if let gap = notch(), at.x + peekSize / 2 > gap.lowerBound, at.x - peekSize / 2 < gap.upperBound { covered += 1 }
                }
            }
        }
        note("fan edges=4 positions=4 outside=\(outside) overlap=\(overlap) underNotch=\(covered)")
        for (label, point) in [("left", NSPoint(x: screen.frame.minX + 200, y: screen.frame.midY)),
                               ("top", NSPoint(x: screen.frame.midX, y: screen.frame.maxY - 150)),
                               ("bottom", NSPoint(x: screen.frame.maxX - 300, y: screen.frame.minY + 90)),
                               ("right", NSPoint(x: screen.frame.maxX - 60, y: screen.frame.midY))] {
            snap(to: point)
            note("snap want=\(label) got=\(edge.rawValue) along=\(String(format: "%.2f", along)) center=\(NSStringFromPoint(outCenter()))")
        }

        // 마우스를 흉내 내요: 자리는 mouse에 적어 두고, 누르기 · 끌기 · 떼기는 진짜 클릭처럼 앱에 보내요
        (edge, along, screenIndex) = kept
        mode = .peek; place(); layout(animated: false)
        let away = NSPoint(x: screen.frame.midX, y: screen.frame.midY)
        var mouse = away
        pointer = { mouse }
        testing = false
        func send(_ kind: NSEvent.EventType) {
            let local = NSPoint(x: mouse.x - panel.frame.minX, y: mouse.y - panel.frame.minY)
            if let event = NSEvent.mouseEvent(with: kind, location: local, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                              windowNumber: panel.windowNumber, context: nil, eventNumber: 0, clickCount: 1,
                                              pressure: kind == .leftMouseUp ? 0 : 1) {
                NSApp.sendEvent(event)
            }
        }
        func click(_ at: NSPoint) { mouse = at; send(.leftMouseDown); send(.leftMouseUp) }
        func satellite(_ index: Int) -> NSPoint {
            let angle = fanAngles()[index] * .pi / 180, middle = outCenter()
            return NSPoint(x: middle.x + cos(angle) * fanRadius, y: middle.y + sin(angle) * fanRadius)
        }
        func window() -> String { overlay?.isVisible == true ? (shown ?? "?") : "closed" }
        var seen: [String] = []

        mouse = NSPoint(x: bubbleCenter().x + 10, y: bubbleCenter().y)       // 걸쳐 있는 버튼에 올려요
        hovered()
        later(0.7) { [self] in
            seen.append("hover=\(mode)")
            click(outCenter()); seen.append("press=\(window())")
            click(satellite(1)); seen.append("todo=\(window()),\(mode)")
            click(satellite(0)); seen.append("map=\(window())")
            click(outCenter()); seen.append("press=\(window())")
            mouse = away                                                   // 마우스가 떠나요
            later(0.9) { [self] in
                seen.append("leave=\(mode)")
                mouse = NSPoint(x: bubbleCenter().x + 8, y: bubbleCenter().y)   // 걸쳐 있는 버튼을 잡아 위쪽으로 끌어요
                send(.leftMouseDown)
                let target = NSPoint(x: screen.frame.minX + 300, y: screen.frame.maxY - 50)
                mouse = NSPoint(x: (mouse.x + target.x) / 2, y: (mouse.y + target.y) / 2); send(.leftMouseDragged)
                mouse = target; send(.leftMouseDragged)
                let carried = hypot(panel.frame.midX - mouse.x, panel.frame.midY - mouse.y)
                send(.leftMouseUp)
                let landed = hypot(panel.frame.midX - outCenter().x, panel.frame.midY - outCenter().y)
                seen.append("drag=\(edge.rawValue),\(mode) underMouse=\(carried < bubbleSize / 2) landed=\(landed < 1) window=\(window())")
                later(0.4) { [self] in
                    seen.append("rest=\(mode)")
                    mouse = NSPoint(x: outCenter().x, y: outCenter().y - 120)      // 잠깐 나갔다가
                    later(0.25) { [self] in
                        mouse = outCenter()                                    // 다시 올라와요
                        later(0.3) { [self] in
                            seen.append("back=\(mode)")
                            clickedAway(); seen.append("elsewhere=\(mode)")
                            note("acts " + seen.joined(separator: " "))
                            for key in ["GadakFloatEdge", "GadakFloatAlong", "GadakFloatScreen"] { UserDefaults.standard.removeObject(forKey: key) }
                            (edge, along, screenIndex) = kept
                            pointer = { NSEvent.mouseLocation }
                            testing = true
                            mode = .peek; place(); layout(animated: false)
                            open()
                            later(0.8) { [self] in hits(note, write, later) }
                        }
                    }
                }
            }
        }
    }

    /// 눌리는 자리: 버튼 위는 이 창이 받고, 빈 자리는 아래 앱이 받아야 해요 (화면에 그려진 뒤에 재요). 이어서 노선도 창을 그림으로 남겨요
    fileprivate func hits(_ note: @escaping (String) -> Void, _ write: @escaping (String, Data?) -> Void,
                      _ later: @escaping (Double, @escaping () -> Void) -> Void) {
        func mine(_ point: NSPoint) -> Bool { NSWindow.windowNumber(at: point, belowWindowWithWindowNumber: 0) == panel.windowNumber }
        func png(_ image: NSImage?) -> Data? {
            image?.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0)?.representation(using: .png, properties: [:]) }
        }
        let middle = outCenter(), angle = fanAngles()[2] * .pi / 180
        let onSatellite = NSPoint(x: middle.x + cos(angle) * fanRadius, y: middle.y + sin(angle) * fanRadius)
        let between = (fanAngles()[2] + fanAngles()[3]) / 2 * .pi / 180
        let empty = NSPoint(x: middle.x + cos(between) * (bubbleSize / 2 + 12), y: middle.y + sin(between) * (bubbleSize / 2 + 12))
        let corner = NSPoint(x: edge == .right ? panel.frame.minX + 5 : panel.frame.maxX - 5, y: panel.frame.maxY - 5)
        note("hit open bubble=\(mine(middle)) satellite=\(mine(onSatellite)) gap=\(mine(empty)) corner=\(mine(corner)) diameter=\(bubble.diameter)")
        clickedAway()
        later(0.8) { [self] in
            var inward = bubbleCenter()
            switch edge {
            case .left: inward.x += peekSize / 4
            case .right: inward.x -= peekSize / 4
            case .top: inward.y -= peekSize / 4
            case .bottom: inward.y += peekSize / 4
            }
            note("hit peek bubble=\(mine(inward)) whereFanWas=\(mine(onSatellite)) whereBubbleWas=\(mine(middle)) diameter=\(bubble.diameter)")
            showOverlay("todo")
            later(5) { [self] in
                note("overlay todo frame=\(NSStringFromRect(overlay?.frame ?? .zero)) visible=\(overlay?.isVisible == true) height=\(overlayHeight) level=\(overlay?.level.rawValue ?? -1)")
                web?.takeSnapshot(with: nil) { [self] image, _ in
                    write("overlay-todo.png", png(image))
                    showOverlay("map")
                    later(2) { [self] in
                        note("overlay map frame=\(NSStringFromRect(overlay?.frame ?? .zero)) height=\(overlayHeight) todo=\(todo)")
                        web?.takeSnapshot(with: nil) { [self] image, _ in
                            write("overlay-map.png", png(image))
                            // 노선도 창 안을 진짜 클릭처럼 눌러 봐요: 가닥이 앞에 있지 않아도 첫 클릭에 목록이 펴지는지 → 다시 접히는지 →
                            // 역을 누르면 가닥 창이 그 대화의 그 역을 열라는 부탁을 받는지 → ‘접기’로 창이 닫히는지
                            let find = "(function(n){var b=n==='station'?document.querySelector('button.st[data-tid]'):[].slice.call(document.querySelectorAll('button')).filter(function(x){return n==='fold'?x.textContent==='접기':x.className==='ledbtn'})[0];if(!b)return null;var r=b.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2,b.dataset.tid||'']})"
                            func tap(_ name: String, then: @escaping (String) -> Void) {
                                web?.evaluateJavaScript("\(find)('\(name)')") { [self] found, _ in
                                    guard let at = found as? [Any], at.count == 3, let x = (at[0] as? NSNumber)?.doubleValue,
                                          let y = (at[1] as? NSNumber)?.doubleValue, let window = overlay else {
                                        note("overlay button \(name) not found")
                                        return then("")
                                    }
                                    let local = NSPoint(x: x, y: Double(window.frame.height) - y)
                                    for kind in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
                                        if let event = NSEvent.mouseEvent(with: kind, location: local, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                                                                          windowNumber: window.windowNumber, context: nil, eventNumber: 0, clickCount: 1,
                                                                          pressure: kind == .leftMouseUp ? 0 : 1) {
                                            NSApp.sendEvent(event)
                                        }
                                    }
                                    later(1.0) { then(at[2] as? String ?? "") }
                                }
                            }
                            app?.webView.evaluateJavaScript("(function(){var f=window.gadakOpen;window.gadakAsked=null;window.gadakOpen=function(h){window.gadakAsked=h;return f(h)}})()", completionHandler: nil)
                            let before = overlayHeight, keyBefore = overlay?.isKeyWindow == true, activeBefore = NSApp.isActive
                            tap("list") { [self] _ in
                                let first = overlayHeight, keyAfter = overlay?.isKeyWindow == true
                                tap("list") { [self] _ in
                                    let second = overlayHeight
                                    tap("station") { [self] station in
                                        app?.webView.evaluateJavaScript("window.gadakAsked ? window.gadakAsked.turn : ''") { [self] asked, _ in
                                            let opened = !station.isEmpty && (asked as? String) == station
                                            let front = NSApp.isActive && app?.window.isKeyWindow == true
                                            tap("fold") { [self] _ in
                                                note("overlay clicks firstClick=\(first > before + 20) heights=\(before)→\(first)→\(second) key=\(keyBefore)→\(keyAfter) appActive=\(activeBefore) station=\(opened) windowCameFront=\(front) fold=\(overlay?.isVisible != true)")
                                                escape(note, later)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    /// 노선도 창을 다시 띄우고, 누르지 않은 채 Esc만 눌러 봐요: 뜨자마자 글쇠를 이 창이 받고 있어야 닫혀요.
    /// 다른 앱을 쓰는 중에도 그런지 보려고, 먼저 앞자리를 쓰던 앱에 돌려줘요. 가닥이 앞으로 나오면 안 돼요(쓰던 앱이 그대로 앞).
    fileprivate func escape(_ note: @escaping (String) -> Void, _ later: @escaping (Double, @escaping () -> Void) -> Void) {
        func front() -> pid_t? { NSWorkspace.shared.frontmostApplication?.processIdentifier }
        FloatController.userApp?.activate(options: [])
        later(1.2) { [self] in
            let behind = !NSRunningApplication.current.isActive, before = front()
            showOverlay("map")
            later(0.5) { [self] in
                let key = overlay?.isKeyWindow == true && NSApp.keyWindow === overlay
                let stayed = !NSRunningApplication.current.isActive && front() == before && app?.window.isKeyWindow != true
                if let window = overlay, let event = NSEvent.keyEvent(
                    with: .keyDown, location: .zero, modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                    windowNumber: window.windowNumber, context: nil, characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}",
                    isARepeat: false, keyCode: 53) {
                    NSApp.sendEvent(event)
                }
                later(0.5) { [self] in
                    note("overlay esc gadakBehind=\(behind) keyOnOpen=\(key) gadakStayedBehind=\(stayed) closed=\(overlay?.isVisible != true) keyAfter=\(overlay?.isKeyWindow == true) frontAppSame=\(front() == before)")
                    NSApp.terminate(nil)
                }
            }
        }
    }
}
