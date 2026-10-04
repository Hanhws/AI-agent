// 떠 있는 가닥 버튼 (요청 UI 10/4 · screenshots/요청 UI.png).
//
// 1. 평소: 화면 가장자리에 반쯤 걸쳐 있어요. 다른 앱을 쓰는 동안에도 그 위에 떠 있어요.
// 2. 마우스를 올리거나 누르면 다 나오면서 둘레에 버튼 여섯 개가 펼쳐져요.
// 3. 가닥 버튼이나 둘레 버튼을 누르면 화면 위쪽에 노선도 창이 떠요 (백엔드의 /strip: 가닥 창의 노선도 카드만 따로 띄운 것).
// 4. 버튼은 끌어서 화면 가장자리 어디로든 옮길 수 있어요. 놓으면 가장 가까운 가장자리에 붙고, 메뉴 막대와 Dock 위에도 놓여요.
//
// 모양은 가닥의 표기 그대로예요: 종이색 동그라미 · 검은 선 · 심볼 A. 빨강은 ‘지금’과 할 일 수에만 써요.

import Cocoa
import WebKit

enum FloatEdge: String, CaseIterable { case left, right, top, bottom }

/// 버튼 둘레에 펼쳐지는 여섯 가지. key는 /strip의 탭 이름이거나(map · todo · dec · files) 가닥 창을 여는 일(find · window).
struct FloatAction { let key: String, label: String, tip: String }

let floatActions = [
    FloatAction(key: "map", label: "노선도", tip: "지금 대화의 노선도"),
    FloatAction(key: "todo", label: "할 일", tip: "놓친 일과 제안"),
    FloatAction(key: "dec", label: "정함", tip: "지금까지 정한 것"),
    FloatAction(key: "files", label: "산출물", tip: "나온 파일"),
    FloatAction(key: "find", label: "찾기", tip: "가닥 창에서 대화 찾기"),
    FloatAction(key: "window", label: "창", tip: "가닥 창 열기"),
]

let bubbleSize: CGFloat = 60          // 가닥 버튼 (다 나왔을 때)
let peekSize: CGFloat = 48            // 가장자리에 걸쳐 있을 때. 반만 보여요
let satelliteSize: CGFloat = 44       // 둘레의 버튼
let fanRadius: CGFloat = 84           // 가닥 버튼 가운데에서 둘레 버튼 가운데까지
let floatGap: CGFloat = 6             // 다 나왔을 때 화면 가장자리와의 틈
let shade: CGFloat = 10               // 그림자 자리
let floatSide: CGFloat = 2 * (fanRadius + satelliteSize / 2 + shade) + 4    // 버튼들이 든 투명한 창의 한 변

/// docs/design/tokens.css의 값 (밝게 · 어둡게)
func token(_ light: Int, _ dark: Int) -> NSColor {
    NSColor(name: nil) { appearance in
        let hex = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        return NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                       blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}
let floatSurface = token(0xFFFFFF, 0x1F1E1B)
let floatInk = token(0x141414, 0xF1EFEA)
let floatLine = token(0xBDB9B2, 0x6A665F)      // --ring: 어두운 화면에서도 동그라미 테두리가 보이게
let floatMuted = token(0x3F3F46, 0xD6D3CD)
let floatAccent = token(0xC8401A, 0xF0704A)

/// 심볼 A (mac/icon.swift와 같은 좌표): 본선 + 위로 빠지는 지선 + 보통 역 + 빨갛게 채운 ‘지금’
func drawMark(center: NSPoint, width: CGFloat) {
    let unit = width / 146
    func point(_ x: CGFloat, _ y: CGFloat) -> NSPoint { NSPoint(x: center.x + (x - 101) * unit, y: center.y - (y - 105) * unit) }
    func circle(_ at: NSPoint, _ radius: CGFloat) -> NSBezierPath {
        NSBezierPath(ovalIn: NSRect(x: at.x - radius, y: at.y - radius, width: radius * 2, height: radius * 2))
    }
    let line = NSBezierPath()
    line.lineWidth = 16 * unit
    line.lineCapStyle = .round
    line.lineJoinStyle = .round
    line.move(to: point(36, 122)); line.line(to: point(166, 122))
    line.move(to: point(100, 122)); line.line(to: point(132, 80)); line.line(to: point(154, 80))
    floatInk.setStroke()
    line.stroke()
    let station = circle(point(100, 122), 13 * unit)
    floatSurface.setFill(); station.fill()
    station.lineWidth = 10 * unit
    floatInk.setStroke(); station.stroke()
    floatAccent.setFill(); circle(point(154, 122), 16 * unit).fill()
}

func drawText(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor, centeredAt at: NSPoint) {
    let string = NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color])
    let box = string.size()
    string.draw(at: NSPoint(x: at.x - box.width / 2, y: at.y - box.height / 2))
}

/// 종이색 동그라미 (그림자 · 테두리). 마우스가 올라오면 테두리가 진해져요.
func drawDisc(in bounds: NSRect, diameter: CGFloat, hot: Bool) {
    let disc = NSBezierPath(ovalIn: NSRect(x: bounds.midX - diameter / 2, y: bounds.midY - diameter / 2, width: diameter, height: diameter))
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
    shadow.shadowBlurRadius = 7
    shadow.shadowOffset = NSSize(width: 0, height: -1.5)
    shadow.set()
    floatSurface.setFill()
    disc.fill()
    NSGraphicsContext.restoreGraphicsState()
    (hot ? floatInk : floatLine).setStroke()
    disc.lineWidth = hot ? 1.6 : 1.2
    disc.stroke()
}

/// 할 일 수 (빨강은 할 일에만)
func drawBadge(_ count: Int, at: NSPoint) {
    guard count > 0 else { return }
    let radius: CGFloat = 8
    floatAccent.setFill()
    NSBezierPath(ovalIn: NSRect(x: at.x - radius, y: at.y - radius, width: radius * 2, height: radius * 2)).fill()
    drawText(count > 9 ? "9+" : String(count), size: 9.5, weight: .bold, color: .white, centeredAt: at)
}

/// 동그란 버튼의 바탕: 동그라미 안에서만 눌려요. 창을 앞으로 가져오지 않고도 첫 클릭이 먹어요.
class DiscView: NSView {
    weak var owner: FloatController?
    @objc dynamic var diameter: CGFloat = 0 { didSet { needsDisplay = true } }
    var badge = 0 { didSet { needsDisplay = true } }
    var hot = false { didSet { needsDisplay = true } }
    private var area: NSTrackingArea?

    /// 크기도 자리처럼 부드럽게 바뀌어요 (animator().diameter)
    override class func defaultAnimation(forKey key: NSAnimatablePropertyKey) -> Any? {
        key == "diameter" ? CABasicAnimation() : super.defaultAnimation(forKey: key)
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard !isHidden, let parent = superview else { return nil }
        let local = convert(point, from: parent)
        return hypot(local.x - bounds.midX, local.y - bounds.midY) <= diameter / 2 ? self : nil
    }

    override func updateTrackingAreas() {
        if let old = area { removeTrackingArea(old) }
        let made = NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .mouseMoved, .activeAlways], owner: self, userInfo: nil)
        addTrackingArea(made)
        area = made
        super.updateTrackingAreas()
    }

    /// 마우스가 동그라미 안에 있는지 (네모난 둘레가 아니라)
    func inside(_ event: NSEvent) -> Bool {
        let local = convert(event.locationInWindow, from: nil)
        return hypot(local.x - bounds.midX, local.y - bounds.midY) <= diameter / 2
    }

    override func mouseEntered(with event: NSEvent) { hot = inside(event) }
    override func mouseMoved(with event: NSEvent) { hot = inside(event) }
    override func mouseExited(with event: NSEvent) { hot = false }
}

/// 가닥 버튼: 마우스를 올리면 둘레 버튼이 펼쳐지고, 누르면 노선도 창을 켜고 끄고, 끌면 옮겨져요.
final class BubbleView: DiscView {
    var pressed = false
    var peek: FloatEdge? { didSet { needsDisplay = true } }    // 걸쳐 있는 가장자리. 다 나왔으면 nil
    private var downAt: NSPoint?
    private var dragging = false
    private var woke = false          // 이번에 누른 것이 펼치기만 한 것인지

    override func mouseEntered(with event: NSEvent) { super.mouseEntered(with: event); if hot { owner?.hovered() } else { owner?.nearby() } }
    override func mouseMoved(with event: NSEvent) { super.mouseMoved(with: event); if hot { owner?.hovered() } }

    override func mouseDown(with event: NSEvent) {
        pressed = true
        dragging = false
        downAt = owner?.pointer()
        woke = owner?.wake() ?? false
        owner?.dragBegan()
    }

    override func mouseDragged(with event: NSEvent) {
        guard let start = downAt, let now = owner?.pointer() else { return }
        if !dragging && hypot(now.x - start.x, now.y - start.y) < 4 { return }    // 누르다 조금 흔들린 것은 끌기가 아니에요
        dragging = true
        owner?.drag(to: now)
    }

    override func mouseUp(with event: NSEvent) {
        pressed = false
        if dragging { owner?.dropped() } else if !woke { owner?.primary() }
        downAt = nil
        dragging = false
    }

    override func rightMouseDown(with event: NSEvent) { owner?.contextMenu(with: event) }

    override func draw(_ dirty: NSRect) {
        drawDisc(in: bounds, diameter: diameter, hot: hot)
        let middle = NSPoint(x: bounds.midX, y: bounds.midY), corner = diameter * 0.34
        guard let side = peek else {
            drawMark(center: NSPoint(x: middle.x, y: middle.y + diameter * 0.1), width: diameter * 0.47)
            drawText("가닥", size: 11, weight: .semibold, color: floatInk, centeredAt: NSPoint(x: middle.x, y: middle.y - diameter * 0.22))
            drawBadge(badge, at: NSPoint(x: middle.x + corner, y: middle.y + corner))
            return
        }
        // 걸쳐 있을 때는 보이는 반쪽 가운데에 심볼만 그려요
        let step = diameter * 0.23
        var at = middle
        switch side {
        case .left: at.x += step
        case .right: at.x -= step
        case .top: at.y -= step
        case .bottom: at.y += step
        }
        drawMark(center: at, width: diameter * 0.38)
        drawBadge(badge, at: NSPoint(x: middle.x + (side == .right ? -corner : corner), y: middle.y + (side == .top ? -corner : corner)))
    }
}

/// 둘레의 버튼 하나
final class SatelliteView: DiscView {
    var action = floatActions[0]
    var index = 0

    override func mouseUp(with event: NSEvent) { if inside(event) { owner?.choose(index) } }

    override func draw(_ dirty: NSRect) {
        drawDisc(in: bounds, diameter: diameter, hot: hot)
        drawText(action.label, size: action.label.count > 2 ? 10.5 : 11.5, weight: .medium, color: hot ? floatInk : floatMuted,
                 centeredAt: NSPoint(x: bounds.midX, y: bounds.midY))
        drawBadge(badge, at: NSPoint(x: bounds.midX + diameter * 0.34, y: bounds.midY + diameter * 0.34))
    }
}

/// 다른 앱 위에 떠 있고, 눌러도 가닥이 앞으로 나오지 않는 투명한 창
final class FloatPanel: NSPanel {
    var keyable = false
    override var canBecomeKey: Bool { keyable }
    override var canBecomeMain: Bool { false }
}

/// 노선도 창의 화면. 가닥이 앞에 있지 않아도 첫 클릭부터 눌리고(안 그러면 첫 클릭은 창을 깨우는 데만 쓰여요),
/// 누르면 창이 글쇠를 받아서 찾기 칸에 글을 칠 수 있어요.
final class StripWebView: WKWebView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var needsPanelToBecomeKey: Bool { true }
}

func makeFloatPanel(level: NSWindow.Level, keyable: Bool) -> FloatPanel {
    let panel = FloatPanel(contentRect: NSRect(x: 0, y: 0, width: floatSide, height: floatSide),
                           styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    panel.keyable = keyable
    panel.isOpaque = false
    panel.backgroundColor = .clear
    panel.hasShadow = false
    panel.hidesOnDeactivate = false          // 다른 앱을 쓰는 동안에도 보여야 해요
    panel.isFloatingPanel = true
    panel.level = level                      // isFloatingPanel이 높이를 바꾸니 그 뒤에 정해요
    panel.becomesKeyOnlyIfNeeded = true
    panel.isReleasedWhenClosed = false
    panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
    return panel
}

final class FloatController: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    enum Mode { case peek, out, menu }   // 반쯤 걸침 · 가닥 버튼만 나옴(끄는 중 · 놓은 뒤) · 둘레 버튼까지 펼침

    weak var app: AppDelegate?
    let panel = makeFloatPanel(level: .statusBar, keyable: false)     // 메뉴 막대와 Dock 위에도 놓을 수 있게
    let bubble = BubbleView(frame: NSRect(x: 0, y: 0, width: bubbleSize + shade * 2, height: bubbleSize + shade * 2))
    var satellites: [SatelliteView] = []
    var mode = Mode.peek

    // 어디에 붙어 있는지: 어느 화면의 어느 가장자리, 그 가장자리를 따라 어디쯤(0…1)
    var edge = FloatEdge.left
    var along: CGFloat = 0.56
    var screenIndex = 0

    var base: URL?                        // 백엔드 주소. 켜지기 전에는 nil
    var todo = 0
    var overlay: FloatPanel?              // 노선도 창
    var web: WKWebView?
    var loaded = false
    var shown: String?                    // 노선도 창에 지금 보이는 것 (map · todo · dec · files)
    var overlayHeight: CGFloat = 300

    private var watch: Timer?
    private var poll: Timer?
    private var lurk: Timer?
    private var awaySince: Date?
    private var openedAt: Date?
    private var waking = false            // 마우스가 올라와서, 펼칠지 잠깐 재는 중
    private var wasOff = false            // 마우스가 가닥 버튼 밖에 있었는지 (다시 올라오면 다시 펼쳐요)
    private var grab = NSPoint.zero
    var monitors: [Any] = []
    var pointer: () -> NSPoint = { NSEvent.mouseLocation }      // 마우스 자리. 스스로 확인할 때만 바꿔 끼워요
    var testing = false                   // 스스로 확인할 때(mac/FloatCheck.swift)는 마우스가 없어도 펼친 채로 둬요

    init(app: AppDelegate) {
        self.app = app
        super.init()
        let saved = UserDefaults.standard
        if let raw = saved.string(forKey: "GadakFloatEdge"), let kept = FloatEdge(rawValue: raw) { edge = kept }
        if saved.object(forKey: "GadakFloatAlong") != nil { along = min(max(CGFloat(saved.double(forKey: "GadakFloatAlong")), 0), 1) }
        screenIndex = saved.integer(forKey: "GadakFloatScreen")

        let content = NSView(frame: NSRect(x: 0, y: 0, width: floatSide, height: floatSide))
        for (index, action) in floatActions.enumerated() {
            let view = SatelliteView(frame: NSRect(x: 0, y: 0, width: satelliteSize + shade * 2, height: satelliteSize + shade * 2))
            view.owner = self
            view.diameter = satelliteSize
            view.action = action
            view.index = index
            view.toolTip = action.tip
            view.isHidden = true
            view.alphaValue = 0
            content.addSubview(view)
            satellites.append(view)
        }
        bubble.owner = self
        bubble.diameter = peekSize
        bubble.toolTip = "가닥 · 누르면 노선도, 끌면 옮겨져요"
        content.addSubview(bubble)
        panel.contentView = content

        NotificationCenter.default.addObserver(self, selector: #selector(screensChanged),
                                               name: NSApplication.didChangeScreenParametersNotification, object: nil)
        // 다른 곳을 누르면 펼친 버튼을 접어요 (노선도 창은 그대로 둬요: 일하면서 볼 수 있게)
        if let other = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown], handler: { [weak self] _ in self?.clickedAway() }) {
            monitors.append(other)
        }
        if let mine = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .keyDown], handler: { [weak self] event in
            guard let self = self else { return event }
            if event.type == .keyDown {
                if event.keyCode == 53, self.overlay?.isVisible == true, event.window === self.overlay { self.closeOverlay(); return nil }   // esc
                return event
            }
            if event.window !== self.panel { self.clickedAway() }
            return event
        }) {
            monitors.append(mine)
        }
    }

    // MARK: 보이기 · 숨기기

    func show() {
        mode = .peek
        place()
        layout(animated: false)
        panel.orderFrontRegardless()
    }

    /// 버튼을 숨겨요. 이 뒤로는 쓰지 않아요 (다시 켜면 새로 만들어요)
    func close() {
        closeOverlay()
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "gadak")
        watch?.invalidate()
        poll?.invalidate()
        lurk?.invalidate()
        watch = nil
        poll = nil
        lurk = nil
        monitors.forEach { NSEvent.removeMonitor($0) }
        monitors = []
        NotificationCenter.default.removeObserver(self)
        panel.orderOut(nil)
    }

    @objc func screensChanged() {
        place()
        if overlay?.isVisible == true { overlay?.setFrame(overlayFrame(), display: true) }
    }

    // MARK: 자리

    var screen: NSScreen {
        let all = NSScreen.screens
        return screenIndex < all.count ? all[screenIndex] : (all.first ?? NSScreen.main!)
    }

    /// 펼친 버튼이 화면 밖으로 나가지 않게 모서리에서 이만큼은 떨어져요
    static let keep = fanRadius + satelliteSize / 2 + 10

    /// 화면 위쪽 가운데의 카메라 자리(가로 범위). 없는 화면이면 nil
    func notch() -> ClosedRange<CGFloat>? {
        let display = screen
        guard display.safeAreaInsets.top > 0, let left = display.auxiliaryTopLeftArea, let right = display.auxiliaryTopRightArea,
              left.maxX < right.minX else { return nil }
        // 화면 안의 좌표로 줄 때가 있어서, 화면 밖 값이면 화면 자리만큼 옮겨요
        let frame = display.frame
        let global = left.minX >= frame.minX - 1 && right.maxX <= frame.maxX + 1
        let shift = global ? 0 : frame.minX
        return (left.maxX + shift)...(right.minX + shift)
    }

    /// 위쪽 가장자리에서는 카메라 자리에 가리지 않게 옆으로 비켜요
    func clearOfNotch(_ x: CGFloat) -> CGFloat {
        guard let hidden = notch() else { return x }
        let reach = bubbleSize / 2 + 6
        if x + reach <= hidden.lowerBound || x - reach >= hidden.upperBound { return x }
        return x < (hidden.lowerBound + hidden.upperBound) / 2 ? hidden.lowerBound - reach : hidden.upperBound + reach
    }

    /// 다 나왔을 때 가닥 버튼 가운데가 가장자리에서 떨어지는 만큼. 위쪽에 카메라 자리가 있는 화면에서는 그 아래까지 내려와요
    func inset() -> CGFloat {
        let plain = bubbleSize / 2 + floatGap
        return edge == .top ? min(plain + screen.safeAreaInsets.top, floatSide / 2 - bubble.frame.height / 2) : plain
    }

    /// 다 나왔을 때 가닥 버튼의 가운데
    func outCenter() -> NSPoint {
        let frame = screen.frame, inset = inset(), keep = FloatController.keep
        let x = frame.minX + keep + along * max(frame.width - 2 * keep, 0)
        let y = frame.minY + keep + along * max(frame.height - 2 * keep, 0)
        switch edge {
        case .left: return NSPoint(x: frame.minX + inset, y: y)
        case .right: return NSPoint(x: frame.maxX - inset, y: y)
        case .top: return NSPoint(x: clearOfNotch(x), y: frame.maxY - inset)
        case .bottom: return NSPoint(x: x, y: frame.minY + inset)
        }
    }

    func place(animated: Bool = false) {
        let center = outCenter()
        panel.setFrame(NSRect(x: center.x - floatSide / 2, y: center.y - floatSide / 2, width: floatSide, height: floatSide),
                       display: true, animate: animated)
    }

    /// 반쯤 걸쳤을 때 가닥 버튼이 가장자리 쪽으로 물러나는 만큼 (가운데가 화면 끝에 오게)
    func peekShift() -> NSPoint {
        let distance = inset()
        switch edge {
        case .left: return NSPoint(x: -distance, y: 0)
        case .right: return NSPoint(x: distance, y: 0)
        case .top: return NSPoint(x: 0, y: distance)
        case .bottom: return NSPoint(x: 0, y: -distance)
        }
    }

    /// 둘레 버튼이 놓이는 각도(도). 화면 안쪽으로 반원으로 펼치고, 첫 버튼이 위(왼쪽 · 오른쪽 가장자리)나 왼쪽(위 · 아래 가장자리)에 와요
    func fanAngles() -> [CGFloat] {
        switch edge {
        case .left: return [90, 54, 18, -18, -54, -90]
        case .right: return [90, 126, 162, 198, 234, 270]
        case .top: return [180, 216, 252, 288, 324, 360]
        case .bottom: return [180, 144, 108, 72, 36, 0]
        }
    }

    func layout(animated: Bool) {
        let center = NSPoint(x: floatSide / 2, y: floatSide / 2)
        let shift = mode == .peek ? peekShift() : .zero
        let home = NSPoint(x: center.x + shift.x, y: center.y + shift.y)
        let open = mode == .menu
        let angles = fanAngles()
        bubble.peek = mode == .peek ? edge : nil
        if open { satellites.forEach { $0.isHidden = false } }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = animated ? 0.18 : 0
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            bubble.animator().diameter = mode == .peek ? peekSize : bubbleSize
            bubble.animator().setFrameOrigin(NSPoint(x: home.x - bubble.frame.width / 2, y: home.y - bubble.frame.height / 2))
            for (index, view) in satellites.enumerated() {
                let angle = angles[index] * .pi / 180
                let at = open ? NSPoint(x: center.x + cos(angle) * fanRadius, y: center.y + sin(angle) * fanRadius) : home
                view.animator().setFrameOrigin(NSPoint(x: at.x - view.frame.width / 2, y: at.y - view.frame.height / 2))
                view.animator().alphaValue = open ? 1 : 0
            }
        }, completionHandler: { [weak self] in
            guard let self = self, self.mode != .menu else { return }
            self.satellites.forEach { $0.isHidden = true; $0.hot = false }
        })
    }

    // MARK: 마우스

    /// 화면에서 가닥 버튼의 가운데 (지금 모양 기준)
    func bubbleCenter() -> NSPoint {
        let at = outCenter(), shift = mode == .peek ? peekShift() : .zero
        return NSPoint(x: at.x + shift.x, y: at.y + shift.y)
    }

    /// 걸쳐 있는 버튼에 마우스가 올라왔어요. 지나가다 스친 것이 아니면 펼쳐요
    func hovered() {
        guard mode == .peek, !waking else { return }
        waking = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in
            guard let self = self else { return }
            self.waking = false
            let mouse = self.pointer(), at = self.bubbleCenter()
            if self.mode == .peek, hypot(mouse.x - at.x, mouse.y - at.y) <= peekSize / 2 + 3 { self.open() }
        }
    }

    /// 걸쳐 있는 버튼 바로 옆(그림자 · 네모난 둘레)에 마우스가 왔어요. 동그라미 위로 올라오는지 잠깐 지켜봐요
    func nearby() {
        guard mode == .peek, lurk == nil else { return }
        lurk = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
            guard let self = self else { timer.invalidate(); return }
            let mouse = self.pointer(), at = self.bubbleCenter()
            let distance = hypot(mouse.x - at.x, mouse.y - at.y)
            if self.mode != .peek || distance > bubbleSize * 1.5 { timer.invalidate(); self.lurk = nil; return }
            if distance <= peekSize / 2 + 3 { self.hovered() }
        }
    }

    /// 다 나오면서 둘레 버튼을 펼쳐요
    func open() {
        guard mode != .menu else { return }
        mode = .menu
        openedAt = Date()
        layout(animated: true)
        startWatch()
    }

    /// 가닥 버튼을 눌렀을 때: 아직 펼쳐지지 않았으면 펼치기만 해요(true). 막 펼쳐진 참이어도 같은 한 번으로 쳐요
    func wake() -> Bool {
        if mode == .peek { open(); return true }
        if mode == .menu, let at = openedAt, Date().timeIntervalSince(at) < 0.35 { return true }
        return false
    }

    /// 다시 가장자리에 걸쳐요
    func retreat() {
        mode = .peek
        layout(animated: true)
        bubble.hot = false
        watch?.invalidate()
        watch = nil
    }

    /// 나와 있는 동안 마우스가 어디 있는지 재요. 버튼이 움직이는 동안 들락날락하지 않게 자리를 직접 재요
    func startWatch() {
        awaySince = nil
        if watch != nil { return }
        watch = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.watchTick() }
    }

    func watchTick() {
        guard mode != .peek, !bubble.pressed, !testing else { awaySince = nil; return }
        let mouse = pointer(), center = outCenter()
        let distance = hypot(mouse.x - center.x, mouse.y - center.y)
        let onBubble = distance <= bubbleSize / 2 + 2
        if mode == .out, onBubble, wasOff { wasOff = false; open(); return }     // 나갔다가 다시 올라오면 다시 펼쳐요
        wasOff = !onBubble
        let reach = (mode == .menu ? fanRadius + satelliteSize / 2 : bubbleSize / 2) + 16
        if distance <= reach { awaySince = nil; return }
        if awaySince == nil { awaySince = Date() }
        if let since = awaySince, Date().timeIntervalSince(since) > 0.5 { retreat() }
    }

    /// 펼쳐진 가닥 버튼을 눌렀어요: 노선도 창을 켜고 꺼요
    func primary() {
        if overlay?.isVisible == true { closeOverlay() } else { showOverlay("map") }
    }

    func clickedAway() {
        guard mode != .peek, !bubble.pressed else { return }
        retreat()
    }

    func dragBegan() {
        let mouse = pointer(), at = outCenter()
        grab = NSPoint(x: mouse.x - at.x, y: mouse.y - at.y)
        let length = hypot(grab.x, grab.y), most = bubbleSize / 2 - 8        // 끄는 동안 버튼이 마우스 아래에 있게
        if length > most { grab = NSPoint(x: grab.x * most / length, y: grab.y * most / length) }
    }

    func drag(to mouse: NSPoint) {
        if mode != .out { mode = .out; layout(animated: false) }
        watch?.invalidate()
        watch = nil
        panel.setFrameOrigin(NSPoint(x: mouse.x - grab.x - floatSide / 2, y: mouse.y - grab.y - floatSide / 2))
    }

    /// 놓은 자리에서 가장 가까운 가장자리에 붙어요
    func dropped() {
        snap(to: NSPoint(x: panel.frame.midX, y: panel.frame.midY))
        let saved = UserDefaults.standard
        saved.set(edge.rawValue, forKey: "GadakFloatEdge")
        saved.set(Double(along), forKey: "GadakFloatAlong")
        saved.set(screenIndex, forKey: "GadakFloatScreen")
        place(animated: true)
        if overlay?.isVisible == true { overlay?.setFrame(overlayFrame(), display: true) }
        wasOff = false
        startWatch()
    }

    func snap(to center: NSPoint) {
        let all = NSScreen.screens
        func distance(_ frame: NSRect) -> CGFloat {
            let dx = max(frame.minX - center.x, 0, center.x - frame.maxX), dy = max(frame.minY - center.y, 0, center.y - frame.maxY)
            return hypot(dx, dy)
        }
        screenIndex = all.indices.min { distance(all[$0].frame) < distance(all[$1].frame) } ?? 0
        let frame = screen.frame, keep = FloatController.keep
        let gaps: [(FloatEdge, CGFloat)] = [(.left, center.x - frame.minX), (.right, frame.maxX - center.x),
                                            (.bottom, center.y - frame.minY), (.top, frame.maxY - center.y)]
        edge = gaps.min { $0.1 < $1.1 }?.0 ?? .left
        let raw = (edge == .left || edge == .right)
            ? (center.y - frame.minY - keep) / max(frame.height - 2 * keep, 1)
            : (center.x - frame.minX - keep) / max(frame.width - 2 * keep, 1)
        along = min(max(raw, 0), 1)
    }

    func contextMenu(with event: NSEvent) {
        let menu = NSMenu()
        func add(_ title: String, _ action: Selector) {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
            item.target = self
            menu.addItem(item)
        }
        add("가닥 창 열기", #selector(openWindow))
        add("버튼 숨기기", #selector(hideButton))
        menu.addItem(.separator())
        add("가닥 끄기", #selector(quit))
        NSMenu.popUpContextMenu(menu, with: event, for: bubble)
    }

    @objc func openWindow() { retreat(); app?.showMain() }
    @objc func hideButton() { app?.setFloat(false) }
    @objc func quit() { NSApp.terminate(nil) }

    // MARK: 둘레 버튼 → 노선도 창

    /// 노선도 창에서 볼 것을 고르면 둘레 버튼은 그대로 둬요(이어서 다른 것을 눌러 볼 수 있게). 가닥 창을 여는 것은 접어요
    func choose(_ index: Int) {
        let action = floatActions[index]
        switch action.key {
        case "find": retreat(); app?.showMain(script: "window.gadakFind && window.gadakFind()")
        case "window": retreat(); app?.showMain()
        default:
            if overlay?.isVisible == true && shown == action.key { closeOverlay() } else { showOverlay(action.key) }
        }
    }

    /// 화면 위쪽 가운데. 메뉴 막대 바로 아래에 떠요
    func overlayFrame() -> NSRect {
        let visible = screen.visibleFrame
        let width = min(visible.width - 32, 1180)
        return NSRect(x: visible.midX - width / 2, y: visible.maxY - overlayHeight - 2, width: width, height: overlayHeight)
    }

    func showOverlay(_ tab: String) {
        guard let base = base else { NSSound.beep(); return }      // 가닥이 아직 켜지는 중이에요
        if overlay == nil {
            let made = makeFloatPanel(level: .floating, keyable: true)        // 다른 앱 창 위, 가닥 버튼 아래
            let configuration = WKWebViewConfiguration()
            configuration.userContentController.add(self, name: "gadak")
            let view = StripWebView(frame: .zero, configuration: configuration)
            view.setValue(false, forKey: "drawsBackground")       // 카드 둘레가 비쳐 보이게
            view.navigationDelegate = self
            made.contentView = view
            overlay = made
            web = view
        }
        let list = tab != "map", side = tab == "map" ? "todo" : tab
        overlay?.setFrame(overlayFrame(), display: true)
        if loaded {
            web?.evaluateJavaScript("window.gadakStrip && window.gadakStrip({ tab: '\(side)', list: \(list) })", completionHandler: nil)
        } else {
            var address = URLComponents(url: base.appendingPathComponent("strip"), resolvingAgainstBaseURL: false)!
            address.queryItems = [URLQueryItem(name: "tab", value: side), URLQueryItem(name: "list", value: list ? "1" : "0")]
            web?.load(URLRequest(url: address.url!))
            loaded = true
        }
        shown = tab
        overlay?.orderFrontRegardless()
        panel.orderFrontRegardless()         // 가닥 버튼이 노선도 창 위에
    }

    func closeOverlay() {
        overlay?.orderOut(nil)
        shown = nil
    }

    func webView(_ view: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { loaded = false }
    func webView(_ view: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { loaded = false }
    func webViewWebContentProcessDidTerminate(_ view: WKWebView) { loaded = false }

    /// 노선도 창의 화면이 부탁하는 것: 복사 · 창 닫기 · 카드 높이에 맞추기 · 가닥 창에서 그 역 열기
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "gadak", let body = message.body as? [String: Any] else { return }
        if let text = body["copy"] as? String {
            let board = NSPasteboard.general
            board.clearContents()
            board.setString(text, forType: .string)
        }
        if let what = body["float"] as? String {
            if what == "close" { closeOverlay() }
            if what == "size", let height = (body["height"] as? NSNumber)?.doubleValue {
                overlayHeight = min(max(CGFloat(height), 90), screen.visibleFrame.height * 0.75)
                if overlay?.isVisible == true { overlay?.setFrame(overlayFrame(), display: true) }
            }
        }
        if let target = body["open"] as? [String: Any], let json = try? JSONSerialization.data(withJSONObject: target),
           let text = String(data: json, encoding: .utf8) {
            app?.showMain(script: "window.gadakOpen && window.gadakOpen(\(text))")
        }
    }

    // MARK: 백엔드

    /// 백엔드가 켜졌어요. 할 일 수를 가끔 물어 버튼에 빨간 수로 보여 줘요
    func ready(_ url: URL) {
        base = url
        loaded = false
        poll?.invalidate()
        poll = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in self?.ask() }
        ask()
    }

    func ask() {
        guard let base = base else { return }
        var request = URLRequest(url: base.appendingPathComponent("float"))
        request.timeoutInterval = 3
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let data = data, let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            let count = (json["todo"] as? NSNumber)?.intValue ?? 0
            DispatchQueue.main.async { self?.setTodo(count) }
        }.resume()
    }

    func setTodo(_ count: Int) {
        guard count != todo else { return }
        todo = count
        bubble.badge = count
        satellites[1].badge = count
    }
}
