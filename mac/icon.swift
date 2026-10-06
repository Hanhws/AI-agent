// 가닥 앱 아이콘을 그려요. 쓰는 법: icon <폴더>  → 그 폴더(AppIcon.iconset)에 크기별 PNG를 채워요.
// 모양은 파비콘(prototype 첫 줄)과 같아요: 본선 + 위로 빠지는 지선 + 보통 역 하나 + 빨갛게 채운 ‘지금’ (README 7-12).

import Cocoa

func color(_ hex: Int) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

func draw(_ pixels: Int) -> Data? {
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                                        samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let graphics = NSGraphicsContext(bitmapImageRep: bitmap) else { return nil }
    let context = graphics.cgContext
    context.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)

    // 바탕: macOS 아이콘 틀(1024 안의 824 둥근 사각형)에 종이색
    let body = CGPath(roundedRect: CGRect(x: 100, y: 100, width: 824, height: 824), cornerWidth: 185, cornerHeight: 185,
                      transform: nil)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: -10), blur: 22, color: CGColor(gray: 0, alpha: 0.22))
    context.addPath(body)
    context.setFillColor(color(0xFAF9F6))
    context.fillPath()
    context.restoreGState()
    context.addPath(body)
    context.setStrokeColor(color(0xE6E3DD))
    context.setLineWidth(4)
    context.strokePath()

    // 심볼: 파비콘의 좌표(가운데 100,106)를 틀 가운데(512,512)로. SVG는 y가 아래로, 여기는 위로 자라요
    let unit: CGFloat = 4.1
    func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: 512 + (x - 100) * unit, y: 512 - (y - 106) * unit) }
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.setStrokeColor(color(0x141414))
    context.setLineWidth(16 * unit)
    context.move(to: point(36, 122)); context.addLine(to: point(166, 122))
    context.move(to: point(100, 122)); context.addLine(to: point(132, 80)); context.addLine(to: point(154, 80))
    context.strokePath()

    func circle(_ x: CGFloat, _ y: CGFloat, _ radius: CGFloat) -> CGRect {
        let center = point(x, y)
        return CGRect(x: center.x - radius * unit, y: center.y - radius * unit, width: radius * 2 * unit, height: radius * 2 * unit)
    }
    context.setFillColor(color(0xFFFFFF))
    context.fillEllipse(in: circle(100, 122, 13))
    context.setLineWidth(10 * unit)
    context.strokeEllipse(in: circle(100, 122, 13))
    context.setFillColor(color(0xC8401A))
    context.fillEllipse(in: circle(154, 122, 16))
    return bitmap.representation(using: .png, properties: [:])
}

guard CommandLine.arguments.count == 2 else {
    print("쓰는 법: icon <AppIcon.iconset 폴더>")
    exit(1)
}
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for points in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        guard let png = draw(points * scale) else { exit(1) }
        let name = "icon_\(points)x\(points)" + (scale == 2 ? "@2x" : "") + ".png"
        try png.write(to: folder.appendingPathComponent(name))
    }
}
