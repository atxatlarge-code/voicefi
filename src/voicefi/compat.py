"""
macOS compatibility patches for VoiceFi.
Prevents crashes on macOS 15+ (Sequoia) when third-party libraries (pynput, Carbon)
call thread-unsafe TSM APIs from background listener threads.
"""

import sys
import contextlib
import threading

_pynput_patched = False
_cached_keycode_context = None


def patch_pynput_darwin() -> None:
    """
    Patch pynput's keycode_context on macOS 15+ to prevent SIGTRAP / EXC_BREAKPOINT crashes.

    On macOS 15+ (Sequoia), Carbon's TISCopyCurrentKeyboardInputSource and
    TSMGetInputSourceProperty contain assertions (dispatch_assert_queue) requiring execution
    on the main dispatch queue. When pynput's keyboard.Listener thread starts, it calls
    keycode_context() off the main thread, triggering _dispatch_assert_queue_fail and terminating
    the Python process with SIGTRAP.

    This patch pre-caches or safely resolves the keycode context so background listener
    threads never call Carbon TIS APIs off the main thread.
    """
    global _pynput_patched, _cached_keycode_context
    if _pynput_patched or sys.platform != "darwin":
        return

    try:
        import pynput._util.darwin as pynput_darwin

        _orig_keycode_context = pynput_darwin.keycode_context

        # Pre-warm context on main thread if currently running on main thread
        if threading.current_thread() is threading.main_thread():
            try:
                with _orig_keycode_context() as ctx:
                    if ctx and ctx[0] is not None and ctx[1] is not None:
                        _cached_keycode_context = ctx
            except Exception:
                pass

        @contextlib.contextmanager
        def safe_keycode_context():
            global _cached_keycode_context
            # If on the main thread, attempt to use original context and update cache
            if threading.current_thread() is threading.main_thread():
                try:
                    with _orig_keycode_context() as ctx:
                        if ctx and ctx[0] is not None and ctx[1] is not None:
                            _cached_keycode_context = ctx
                        yield ctx
                        return
                except Exception:
                    pass

            # On secondary threads, NEVER invoke TISCopyCurrentKeyboardInputSource
            if _cached_keycode_context is not None:
                yield _cached_keycode_context
            else:
                # Safe fallback keyboard layout context (virtual key codes still work)
                yield (91, None)

        pynput_darwin.keycode_context = safe_keycode_context

        # Also patch CarbonExtra C functions directly so any direct callers never assert off-thread
        if hasattr(pynput_darwin, "CarbonExtra"):
            carbon = pynput_darwin.CarbonExtra
            _orig_tis_copy = getattr(carbon, "TISCopyCurrentKeyboardInputSource", None)
            _orig_tis_ascii = getattr(
                carbon, "TISCopyCurrentASCIICapableKeyboardLayoutInputSource", None
            )
            _orig_tis_prop = getattr(carbon, "TISGetInputSourceProperty", None)

            def _safe_tis_copy():
                if threading.current_thread() is threading.main_thread() and _orig_tis_copy:
                    try:
                        return _orig_tis_copy()
                    except Exception:
                        return None
                return None

            def _safe_tis_ascii():
                if threading.current_thread() is threading.main_thread() and _orig_tis_ascii:
                    try:
                        return _orig_tis_ascii()
                    except Exception:
                        return None
                return None

            def _safe_tis_prop(source, prop):
                if threading.current_thread() is threading.main_thread() and _orig_tis_prop:
                    try:
                        return _orig_tis_prop(source, prop)
                    except Exception:
                        return None
                return None

            carbon.TISCopyCurrentKeyboardInputSource = staticmethod(_safe_tis_copy)
            carbon.TISCopyCurrentASCIICapableKeyboardLayoutInputSource = staticmethod(
                _safe_tis_ascii
            )
            carbon.TISGetInputSourceProperty = staticmethod(_safe_tis_prop)

        # Patch keyboard._darwin module if already or subsequently imported
        try:
            import pynput.keyboard._darwin as pynput_kb_darwin
            import Quartz

            pynput_kb_darwin.keycode_context = safe_keycode_context

            # Exclude NSSystemDefined (14) from keyboard listener event mask.
            # This ensures hardware media/volume keys (Volume Up, Volume Down, Mute, Brightness)
            # pass natively to macOS CoreAudio and OSD without being swallowed by the event tap.
            pynput_kb_darwin.Listener._EVENTS = (
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
            )
        except Exception:
            pass

        # Patch ListenerMixin to cleanly disable and invalidate CGEventTap on stop
        # preventing severe keyboard typing lag caused by leaked event taps in WindowServer
        if hasattr(pynput_darwin, "ListenerMixin"):
            _orig_mixin_stop = pynput_darwin.ListenerMixin._stop_platform

            def _clean_darwin_run(self):
                try:
                    import HIServices

                    self.IS_TRUSTED = HIServices.AXIsProcessTrusted()
                except Exception:
                    pass
                if not getattr(self, "IS_TRUSTED", False):
                    self._mark_ready()
                    return

                self._loop = None
                self._tap = None
                self._loop_source = None
                try:
                    self._tap = self._create_event_tap()
                    if self._tap is None:
                        self._mark_ready()
                        return

                    import Quartz

                    self._loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
                    self._loop = Quartz.CFRunLoopGetCurrent()

                    Quartz.CFRunLoopAddSource(
                        self._loop, self._loop_source, Quartz.kCFRunLoopDefaultMode
                    )
                    Quartz.CGEventTapEnable(self._tap, True)

                    self._mark_ready()

                    try:
                        while self.running:
                            result = Quartz.CFRunLoopRunInMode(
                                Quartz.kCFRunLoopDefaultMode, 1, False
                            )
                            if result != Quartz.kCFRunLoopRunTimedOut:
                                break
                    except Exception:
                        pass
                finally:
                    if getattr(self, "_tap", None) is not None:
                        try:
                            import Quartz

                            Quartz.CGEventTapEnable(self._tap, False)
                        except Exception:
                            pass
                        try:
                            import Quartz

                            Quartz.CFMachPortInvalidate(self._tap)
                        except Exception:
                            pass
                    if (
                        getattr(self, "_loop", None) is not None
                        and getattr(self, "_loop_source", None) is not None
                    ):
                        try:
                            import Quartz

                            Quartz.CFRunLoopRemoveSource(
                                self._loop, self._loop_source, Quartz.kCFRunLoopDefaultMode
                            )
                        except Exception:
                            pass
                    self._loop = None
                    self._tap = None
                    self._loop_source = None

            def _clean_darwin_stop(self):
                # Instantly disable event tap to eliminate any keyboard latency immediately
                if getattr(self, "_tap", None) is not None:
                    try:
                        import Quartz

                        Quartz.CGEventTapEnable(self._tap, False)
                    except Exception:
                        pass
                if getattr(self, "_loop", None) is not None:
                    try:
                        import Quartz

                        Quartz.CFRunLoopStop(self._loop)
                        Quartz.CFRunLoopWakeUp(self._loop)
                    except Exception:
                        pass
                try:
                    _orig_mixin_stop(self)
                except Exception:
                    pass

            pynput_darwin.ListenerMixin._run = _clean_darwin_run
            pynput_darwin.ListenerMixin._stop_platform = _clean_darwin_stop

        _pynput_patched = True
    except ImportError:
        pass
    except Exception:
        pass
