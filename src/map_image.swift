import AppKit
import Foundation
import ImageIO

// Local composition only. MapMap renders a 720×480 viewport centered on Tesla's
// GPS point; the same blue dot as the OSM prototype is drawn in its center.
// This helper receives image bytes, never credentials, VIN, coordinates or paths.
let input = FileHandle.standardInput.readDataToEndOfFile()
guard input.count <= 3_000_000,
      let source = CGImageSourceCreateWithData(input as CFData, nil),
      let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
      let width = properties[kCGImagePropertyPixelWidth] as? Int,
      let height = properties[kCGImagePropertyPixelHeight] as? Int,
      width == 720, height == 480,
      let image = NSImage(data: input),
      let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
          bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
          colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
      let context = NSGraphicsContext(bitmapImageRep: bitmap) else { exit(1) }

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
image.draw(in: NSRect(x: 0, y: 0, width: width, height: height))
let blue = NSColor(srgbRed: 22.0 / 255, green: 119.0 / 255, blue: 1, alpha: 1)
blue.withAlphaComponent(0.15).setFill()
NSBezierPath(ovalIn: NSRect(x: 329, y: 209, width: 62, height: 62)).fill()
let dot = NSBezierPath(ovalIn: NSRect(x: 346, y: 226, width: 28, height: 28))
blue.setFill()
dot.fill()
NSColor.white.setStroke()
dot.lineWidth = 5
dot.stroke()
NSGraphicsContext.restoreGraphicsState()

// Set the logical size after drawing: 720×480 pixels occupy 360×240 menu points.
bitmap.size = NSSize(width: 360, height: 240)
guard let output = bitmap.representation(using: .png, properties: [:]) else { exit(1) }
FileHandle.standardOutput.write(output)
