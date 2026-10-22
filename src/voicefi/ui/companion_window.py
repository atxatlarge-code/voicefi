"""
Native macOS Desktop Window for VoiceFi Companion using WKWebView.
Provides a lightweight, floating, native macOS desktop client for the
VoiceFi Companion UI (http://localhost:5142), supporting live multi-turn
chat threads, local Gemma on Metal GPU, Claude, Antigravity, and speech audio.
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Any

try:
    import objc
    from Foundation import NSBundle, NSURL, NSURLRequest, NSObject
    from AppKit import (
        NSApplication,
        NSPanel,
        NSWindow,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskMiniaturizable,
        NSBackingStoreBuffered,
        NSRect,
        NSPoint,
        NSSize,
        NSScreen,
        NSView,
        NSApp,
        NSColor,
        NSFloatingWindowLevel,
        NSNormalWindowLevel,
        NSOpenPanel,
        NSModalResponseOK,
        NSViewWidthSizable,
        NSViewHeightSizable,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorMoveToActiveSpace,
    )
    from PyObjCTools import AppHelper

    # Dynamically load WebKit framework without external pip dependencies
    bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/WebKit.framework")
    if bundle:
        bundle.load()
    WKWebView = objc.lookUpClass("WKWebView")
    WKWebViewConfiguration = objc.lookUpClass("WKWebViewConfiguration")
except Exception:
    pass


def is_headless() -> bool:
    """Return True if running in headless / testing mode."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


try:
    CompanionWindowDelegate = objc.lookUpClass("CompanionWindowDelegate")
except objc.nosuchclass_error:

    class CompanionWindowDelegate(objc.lookUpClass("NSObject")):
        """Window delegate to handle moving, resizing, and closing without terminating."""

        def initWithWindow_(self, win):
            self = objc.super(CompanionWindowDelegate, self).init()
            if self is not None:
                self.win = win
            return self

        def windowDidMove_(self, notification):
            if hasattr(self, "win") and self.win:
                self.win.schedule_save_geometry()

        def windowDidResize_(self, notification):
            if hasattr(self, "win") and self.win:
                self.win.schedule_save_geometry()

        def windowShouldClose_(self, sender):
            if hasattr(self, "win") and self.win:
                self.win.save_geometry()
                self.win.hide()
            return False


# Ensure handlers are bound even if class was previously loaded into runtime
def _delegate_window_did_move(self, notification):
    if hasattr(self, "win") and self.win:
        self.win.schedule_save_geometry()


def _delegate_window_did_resize(self, notification):
    if hasattr(self, "win") and self.win:
        self.win.schedule_save_geometry()


def _delegate_window_should_close(self, sender):
    if hasattr(self, "win") and self.win:
        self.win.save_geometry()
        self.win.hide()
    return False


CompanionWindowDelegate.windowDidMove_ = _delegate_window_did_move
CompanionWindowDelegate.windowDidResize_ = _delegate_window_did_resize
CompanionWindowDelegate.windowShouldClose_ = _delegate_window_should_close


try:
    CompanionNavDelegate = objc.lookUpClass("CompanionNavDelegate")
except objc.nosuchclass_error:

    class CompanionNavDelegate(objc.lookUpClass("NSObject")):
        def initWithWindow_(self, win):
            self = objc.super(CompanionNavDelegate, self).init()
            if self is not None:
                self.win = win
            return self

        def webView_didFinishNavigation_(self, webView, navigation):
            print("[CompanionWindow] ✅ Web UI loaded successfully", flush=True)
            if hasattr(self, "win") and self.win:
                self.win._is_loaded = True
                self.win._flush_pending_js()

        def webView_didFailNavigation_withError_(self, webView, navigation, error):
            print(f"[CompanionWindow] ❌ Web UI failed navigation: {error}", flush=True)

        def webView_didFailProvisionalNavigation_withError_(self, webView, navigation, error):
            print(f"[CompanionWindow] ❌ Web UI failed provisional navigation: {error}", flush=True)


def _nav_did_finish(self, webView, navigation):
    print("[CompanionWindow] ✅ Web UI loaded successfully", flush=True)
    if hasattr(self, "win") and self.win:
        self.win._is_loaded = True
        self.win._flush_pending_js()


CompanionNavDelegate.webView_didFinishNavigation_ = _nav_did_finish


def _ui_run_open_panel(self, webView, parameters, frame, completionHandler):
    """Handle <input type="file"> clicks in macOS WKWebView via native NSOpenPanel."""
    selected_paths = []
    try:
        try:
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        allows_multiple = True
        try:
            if parameters is not None and hasattr(parameters, "allowsMultipleSelection"):
                allows_multiple = bool(parameters.allowsMultipleSelection())
        except Exception:
            allows_multiple = True
        panel.setAllowsMultipleSelection_(allows_multiple)
        response = panel.runModal()
        if response == NSModalResponseOK:
            urls = panel.URLs()
            try:
                for u in urls:
                    p = u.path()
                    if p:
                        selected_paths.append(str(p))
            except Exception:
                pass
            try:
                completionHandler(urls)
                return
            except Exception as block_err:
                print(
                    f"[CompanionWindow] completionHandler block fallback triggered: {block_err}",
                    flush=True,
                )
                try:
                    completionHandler(None)
                except Exception:
                    pass
                if selected_paths and webView is not None:
                    import json

                    js_call = f"if (typeof window.attachLocalMacPaths === 'function') window.attachLocalMacPaths({json.dumps(selected_paths)});"
                    webView.evaluateJavaScript_completionHandler_(js_call, None)
                return
        else:
            completionHandler(None)
    except Exception as e:
        print(f"[CompanionWindow] Open panel error: {e}", flush=True)
        try:
            completionHandler(None)
        except Exception:
            pass
        if selected_paths and webView is not None:
            try:
                import json

                js_call = f"if (typeof window.attachLocalMacPaths === 'function') window.attachLocalMacPaths({json.dumps(selected_paths)});"
                webView.evaluateJavaScript_completionHandler_(js_call, None)
            except Exception:
                pass


def _ui_media_permission(self, webView, origin, frame, media_type, decisionHandler):
    """Auto-grant microphone/camera capture permission inside the local Companion WKWebView."""
    try:
        decisionHandler(1)  # WKPermissionDecisionGrant = 1
    except Exception:
        pass


try:
    for _cls_name in (b"NSObject", b"CompanionUIDelegate"):
        objc.registerMetaDataForSelector(
            _cls_name,
            b"webView:runOpenPanelWithParameters:initiatedByFrame:completionHandler:",
            {
                "arguments": {
                    5: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {
                                0: {"type": b"^v"},
                                1: {"type": b"@"},
                            },
                        }
                    }
                }
            },
        )
        objc.registerMetaDataForSelector(
            _cls_name,
            b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:",
            {
                "arguments": {
                    4: {"type": b"q"},
                    5: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {
                                0: {"type": b"^v"},
                                1: {"type": b"q"},
                            },
                        }
                    },
                }
            },
        )
except Exception:
    pass


try:
    CompanionUIDelegate = objc.lookUpClass("CompanionUIDelegate")
except objc.nosuchclass_error:

    class CompanionUIDelegate(objc.lookUpClass("NSObject")):
        def initWithWindow_(self, win):
            self = objc.super(CompanionUIDelegate, self).init()
            if self is not None:
                self.win = win
            return self

        def webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_(
            self, webView, parameters, frame, completionHandler
        ):
            _ui_run_open_panel(self, webView, parameters, frame, completionHandler)

        @objc.signature(b"v@:@@@q@?")
        def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
            self, webView, origin, frame, media_type, decisionHandler
        ):
            _ui_media_permission(self, webView, origin, frame, media_type, decisionHandler)


try:
    CompanionWindow = objc.lookUpClass("CompanionWindow")
except objc.nosuchclass_error:

    class CompanionWindow(objc.lookUpClass("NSWindow")):
        """Native macOS window allowing key and main window focus in an accessory app."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return True


class CompanionDesktopWindow:
    """
    Singleton native macOS window hosting the VoiceFi Companion Web UI
    via a lightweight native WebKit WKWebView instance.
    """

    _instance: Optional["CompanionDesktopWindow"] = None

    @classmethod
    def get_instance(cls, port: Optional[int] = None) -> "CompanionDesktopWindow":
        if cls._instance is None:
            if port is None:
                try:
                    from voicefi.config import load_config

                    cfg = load_config()
                    port = getattr(getattr(cfg, "companion", None), "port", 5141)
                except Exception:
                    port = 5141
            cls._instance = cls(port=port)
        return cls._instance

    def __init__(self, port: int = 5141):
        self.port = port
        self._panel: Optional[Any] = None
        self._webview: Optional[Any] = None
        self._delegate: Optional[Any] = None
        self._nav_delegate: Optional[Any] = None
        self._ui_delegate: Optional[Any] = None
        self._is_loaded: bool = False
        self._pending_js: list[str] = []

        if not is_headless():
            self._build_window()

    def _build_window(self):
        """Construct the NSPanel and WKWebView on the main thread."""

        def _do_build():
            try:
                screen = NSScreen.mainScreen()
                screen_frame = (
                    screen.visibleFrame() if screen else NSRect(NSPoint(0, 0), NSSize(1440, 900))
                )

                width = 460.0
                height = 760.0
                saved_x = None
                saved_y = None

                try:
                    from voicefi.config import load_config

                    cfg = load_config()
                    comp = getattr(cfg, "companion", None)
                    if comp:
                        width = getattr(comp, "window_width", 460.0) or 460.0
                        height = getattr(comp, "window_height", 760.0) or 760.0
                        saved_x = getattr(comp, "window_x", None)
                        saved_y = getattr(comp, "window_y", None)
                except Exception:
                    pass

                placed = False
                if saved_x is not None and saved_y is not None:
                    # Validate that saved coordinates intersect an actively connected screen
                    try:
                        screens = NSScreen.screens()
                        for sc in screens:
                            sf = sc.visibleFrame()
                            if (
                                saved_x + width > sf.origin.x + 30.0
                                and saved_x < sf.origin.x + sf.size.width - 30.0
                                and saved_y + height > sf.origin.y + 30.0
                                and saved_y < sf.origin.y + sf.size.height - 30.0
                            ):
                                x = saved_x
                                y = saved_y
                                placed = True
                                break
                    except Exception:
                        pass

                if not placed:
                    # Position on the right side of the main screen
                    x = screen_frame.origin.x + screen_frame.size.width - width - 24.0
                    y = screen_frame.origin.y + (screen_frame.size.height - height) / 2.0

                frame = NSRect(NSPoint(x, y), NSSize(width, height))

                style = (
                    NSWindowStyleMaskTitled
                    | NSWindowStyleMaskClosable
                    | NSWindowStyleMaskResizable
                    | NSWindowStyleMaskMiniaturizable
                )

                self._panel = CompanionWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    frame,
                    style,
                    NSBackingStoreBuffered,
                    False,
                )
                self._panel.setTitle_("VoiceFi Companion")
                self._panel.setMinSize_(NSSize(380, 500))
                self._panel.setBackgroundColor_(NSColor.blackColor())
                self._panel.setCollectionBehavior_(NSWindowCollectionBehaviorMoveToActiveSpace)

                # WebKit Configuration
                config = WKWebViewConfiguration.alloc().init()
                try:
                    config.preferences().setValue_forKey_(True, "developerExtrasEnabled")
                except Exception:
                    pass

                self._webview = WKWebView.alloc().initWithFrame_configuration_(
                    NSRect(NSPoint(0, 0), NSSize(width, height)),
                    config,
                )
                self._webview.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
                try:
                    self._webview.setValue_forKey_(False, "drawsBackground")
                except Exception:
                    pass
                self._panel.setContentView_(self._webview)

                # Delegate
                self._delegate = CompanionWindowDelegate.alloc().initWithWindow_(self)
                self._panel.setDelegate_(self._delegate)

                # Navigation Delegate
                try:
                    self._nav_delegate = CompanionNavDelegate.alloc().initWithWindow_(self)
                except Exception:
                    self._nav_delegate = CompanionNavDelegate.alloc().init()
                    self._nav_delegate.win = self
                self._webview.setNavigationDelegate_(self._nav_delegate)

                # UI Delegate (Enables <input type="file"> NSOpenPanel & mic/camera permissions in WKWebView)
                try:
                    self._ui_delegate = CompanionUIDelegate.alloc().initWithWindow_(self)
                except Exception:
                    self._ui_delegate = CompanionUIDelegate.alloc().init()
                    self._ui_delegate.win = self
                self._webview.setUIDelegate_(self._ui_delegate)

                # Load initial URL via direct IPv4
                url_str = f"http://127.0.0.1:{self.port}"
                req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url_str))
                self._webview.loadRequest_(req)
                print(f"[CompanionWindow] 🚀 Initialized WKWebView targeting {url_str}", flush=True)

            except Exception as e:
                print(f"[CompanionWindow] Notice building window: {e}", flush=True)

        if threading.current_thread() is threading.main_thread():
            _do_build()
        else:
            AppHelper.callAfter(_do_build)

    def _flush_pending_js(self):
        """Execute any JavaScript queued while the WKWebView was finishing initial navigation."""
        if not self._pending_js:
            return
        pending = list(self._pending_js)
        self._pending_js.clear()
        for js in pending:
            self.evaluate_js(js, delay_s=0.1)

    def schedule_save_geometry(self, delay: float = 0.5):
        """Debounced geometry saving to prevent disk churn during window drag/resize."""
        if hasattr(self, "_save_timer") and self._save_timer:
            try:
                self._save_timer.cancel()
            except Exception:
                pass
        self._save_timer = threading.Timer(delay, self.save_geometry)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_geometry(self):
        """Save window frame coordinates and docking state to ~/.voicefi/config.yaml."""
        if not self._panel or is_headless():
            return
        try:
            frame = self._panel.frame()
            x = float(frame.origin.x)
            y = float(frame.origin.y)
            w = float(frame.size.width)
            h = float(frame.size.height)

            dock_edge = "float"
            try:
                screen = self._panel.screen() or NSScreen.mainScreen()
                if screen:
                    sf = screen.visibleFrame()
                    right_gap = abs((sf.origin.x + sf.size.width) - (x + w))
                    left_gap = abs(x - sf.origin.x)
                    if right_gap < 50.0:
                        dock_edge = "right"
                    elif left_gap < 50.0:
                        dock_edge = "left"
            except Exception:
                pass

            from voicefi.config import load_config, save_config

            cfg = load_config()
            cfg.companion.window_x = x
            cfg.companion.window_y = y
            cfg.companion.window_width = w
            cfg.companion.window_height = h
            cfg.companion.dock_edge = dock_edge
            save_config(cfg)
        except Exception as e:
            print(f"[CompanionWindow] Notice saving window geometry: {e}", flush=True)

    def show(self):
        """Bring the companion window to the front and focus it."""

        def _do_show():
            if not self._panel:
                self._build_window()
            if not self._panel:
                return
            try:
                # If webview has never loaded or was on a failed URL, re-trigger request
                if self._webview:
                    curr_url = self._webview.URL()
                    target_url = f"http://127.0.0.1:{self.port}"
                    if not self._webview.isLoading() and (
                        not curr_url
                        or not curr_url.absoluteString()
                        or not curr_url.absoluteString().startswith(f"http://127.0.0.1:{self.port}")
                    ):
                        req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(target_url))
                        self._webview.loadRequest_(req)
                self._panel.setLevel_(NSFloatingWindowLevel)
                self._panel.makeKeyAndOrderFront_(None)
                if hasattr(self._panel, "orderFrontRegardless"):
                    self._panel.orderFrontRegardless()
                NSApp.activateIgnoringOtherApps_(True)
            except Exception as e:
                print(f"[CompanionWindow] show error: {e}", flush=True)

        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            AppHelper.callAfter(_do_show)

    def hide(self):
        """Hide the companion window."""
        if not self._panel:
            return

        def _do_hide():
            try:
                self._panel.orderOut_(None)
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def toggle(self):
        """Toggle visibility of the companion window."""
        if not self._panel:
            return
        if self._panel.isVisible():
            self.hide()
        else:
            self.show()

    def evaluate_js(self, js_code: str, delay_s: float = 0.0):
        """Safely evaluate JavaScript inside the native WKWebView on the main thread."""
        if is_headless():
            return

        def _do_eval():
            try:
                if self._webview:
                    self._webview.evaluateJavaScript_completionHandler_(js_code, None)
            except Exception as e:
                print(f"[CompanionWindow] evaluate_js notice: {e}", flush=True)

        def _schedule():
            if delay_s > 0:
                time.sleep(delay_s)
            if threading.current_thread() is threading.main_thread():
                _do_eval()
            else:
                AppHelper.callAfter(_do_eval)

        if delay_s > 0:
            threading.Thread(target=_schedule, daemon=True).start()
        elif threading.current_thread() is threading.main_thread():
            _do_eval()
        else:
            AppHelper.callAfter(_do_eval)

    def open_channel_mode(self, mac_mic_active: bool = False):
        """Show the Companion window and open the Obsidian ✨ Channel takeover modal."""
        self.show()
        flag = "true" if mac_mic_active else "false"
        js = (
            f"if (typeof openObsidianTakeover === 'function') {{ "
            f"window._macDesktopChannelRecording = {flag}; "
            f"const m = document.getElementById('obsidianModal'); "
            f"if (!m || m.classList.contains('hidden') || currentObsidianMode !== 'channel') {{ "
            f"openObsidianTakeover('channel'); "
            f"}} else if ({flag}) {{ "
            f"const st = document.getElementById('obsidianTakeoverStatus'); "
            f"if (st) st.innerText = '🎙️ Mac Mic Active • Pacing Mode (Click Stop & Save when done)'; "
            f"}} "
            f"}}"
        )
        if not self._is_loaded:
            self._pending_js.append(js)
        self.evaluate_js(js, delay_s=0.15)
        self.evaluate_js(js, delay_s=0.65)

    def open_channel_studio(self, memo_payload: dict):
        """Show the Companion window and open the Post-Channel Studio view with a saved memo payload."""
        import json

        self.show()
        payload_json = json.dumps(memo_payload)
        js = (
            f"if (typeof openDesktopChannelStudioFromPayload === 'function') {{ "
            f"openDesktopChannelStudioFromPayload({payload_json}); "
            f"}}"
        )
        if not self._is_loaded:
            self._pending_js.append(js)
        self.evaluate_js(js, delay_s=0.20)
        self.evaluate_js(js, delay_s=0.70)


    def dispatch_prompt(
        self,
        text: str,
        engine: str = "gemma",
        model: str = "gemma4-2b",
        show_window: bool = True,
    ):
        """
        Submit prompt to the Companion backend, optionally presenting the window.
        """
        if show_window:
            self.show()

        def _submit():
            try:
                import urllib.request
                import json

                url = f"http://127.0.0.1:{self.port}/api/conversations/new"
                payload = json.dumps(
                    {
                        "prompt": text,
                        "engine": engine,
                        "model": model,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    new_id = data.get("conv_id")
                    if new_id and self._webview:
                        js = f"if (typeof fetchConversationDetails === 'function') {{ activeConvId = '{new_id}'; fetchConversationDetails('{new_id}'); }}"
                        self._webview.evaluateJavaScript_completionHandler_(js, None)
            except Exception as e:
                print(
                    f"[CompanionWindow] Notice: Companion server API unreachable ({e}), executing via direct LocalModelEngine...",
                    flush=True,
                )
                try:
                    import asyncio
                    from voicefi.integrations.conversations import save_gemma_turn
                    from voicefi.local.engine import LocalModelEngine

                    cid = f"gemma_{int(time.time())}"
                    c_title = text[:40] if text else "Local Gemma"
                    save_gemma_turn(cid, user_text=text, agent_text="", model=model, title=c_title)
                    eng = LocalModelEngine(model_name=model)
                    ans = asyncio.run(eng.chat_text(text))
                    save_gemma_turn(cid, user_text=text, agent_text=ans, model=model, title=c_title)

                    try:
                        from voicefi.tts import get_tts_engine
                        from voicefi.config import load_config

                        tts = get_tts_engine(load_config(), agent_name="gemma")
                        tts.speak(ans)
                    except Exception as speak_err:
                        print(f"[CompanionWindow] TTS playback notice: {speak_err}", flush=True)
                except Exception as fallback_err:
                    print(
                        f"[CompanionWindow] Direct local execution error: {fallback_err}",
                        flush=True,
                    )

        threading.Thread(target=_submit, daemon=True, name="CompanionPromptSubmit").start()
