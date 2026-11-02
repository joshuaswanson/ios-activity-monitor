import AppKit
import SwiftUI
import WebKit

/// Shows the bundled interface and connects it to the engine.
struct MonitorView: NSViewRepresentable {
    func makeCoordinator() -> EngineBridge {
        EngineBridge()
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(context.coordinator, name: "engine")
        let webView = InterfaceWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        webView.navigationDelegate = context.coordinator
        context.coordinator.webView = webView
        if let interface = Bundle.main.resourceURL?.appending(path: "ui") {
            webView.loadFileURL(interface.appending(path: "index.html"), allowingReadAccessTo: interface)
        }
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {}
}

private final class InterfaceWebView: WKWebView {
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) {
        menu.removeAllItems()
    }
}

@MainActor
final class EngineBridge: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    weak var webView: WKWebView?
    private lazy var engine = EngineClient { [weak self] line in
        self?.webView?.evaluateJavaScript("window.onEngineEvent(\(line));")
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard let body = message.body as? [String: Any],
              let command = body["cmd"] as? String,
              let ms = body["ms"] as? Int else { return }
        switch command {
        case "start": engine.start(intervalMs: ms)
        case "set_sample_interval": engine.setSampleInterval(ms)
        default: break
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.window?.makeFirstResponder(webView)
    }
}
