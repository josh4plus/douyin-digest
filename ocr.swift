import Foundation
import Vision
import AppKit

// 用法: vision-ocr <图片路径> [更多图片...]
// 输出: 每行 "<文件名>\t<识别到的整段文字>"，多张图多行

func ocr(_ path: String) -> String {
    guard let img = NSImage(contentsOfFile: path),
          let tiff = img.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let cg = rep.cgImage else { return "" }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true

    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([request]) } catch { return "" }

    guard let obs = request.results else { return "" }
    // 按纵向位置从上到下排序
    let sorted = obs.sorted { a, b in a.boundingBox.midY > b.boundingBox.midY }
    var lines: [String] = []
    for o in sorted {
        if let top = o.topCandidates(1).first { lines.append(top.string) }
    }
    return lines.joined(separator: " ")
}

let args = Array(CommandLine.arguments.dropFirst())
for path in args {
    let text = ocr(path)
    let name = (path as NSString).lastPathComponent
    print(name + "\t" + text)
}
