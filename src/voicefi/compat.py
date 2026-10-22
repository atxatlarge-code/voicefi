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
        # and provide microsecond fast-path bypass for gaming and normal typing.
        if hasattr(pynput_darwin, "ListenerMixin"):
            _orig_mixin_stop = pynput_darwin.ListenerMixin._stop_platform
            _orig_handler = getattr(pynput_darwin.ListenerMixin, "_handler", None)

            # Hotkeys VoiceFi recognizes:
            # 53=Esc, 48=Tab, 36=Return, 76=NumpadEnter, 49=Space, 8=C, 45=N, 38=J, 0=A, 2=D, 17=T, 9=V, 15=R
            _HOTKEY_VKS = frozenset((53, 48, 36, 76, 49, 8, 45, 38, 0, 2, 17, 9, 15))
            _MODIFIER_VKS = frozenset((54, 55, 56, 58, 59, 60, 61, 62, 63))
            _PTT_VKS = frozenset((17, 2, 15, 9, 45))

            def _safe_darwin_handler(self, proxy, event_type, event, refcon):
                # Re-enable tap if macOS WindowServer ever sends kCGEventTapDisabledByTimeout (0xFFFFFFFE)
                if event_type in (0xFFFFFFFE, 0xFFFFFFFF) or event is None:
                    if getattr(self, "_tap", None) is not None and getattr(self, "running", False):
                        try:
                            import Quartz

                            Quartz.CGEventTapEnable(self._tap, True)
                        except Exception:
                            pass
                    return event

                import Quartz

                _k_key_down = Quartz.kCGEventKeyDown
                _k_key_up = Quartz.kCGEventKeyUp
                _k_flags_changed = Quartz.kCGEventFlagsChanged

                # 1. FlagsChanged: only modifier keys (Shift, Ctrl, Alt, Cmd, Fn) ever matter
                if event_type == _k_flags_changed:
                    vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                    if vk in _MODIFIER_VKS:
                        if _orig_handler is not None:
                            return _orig_handler(self, proxy, event_type, event, refcon)
                    return event

                # 2. KeyUp: Critical Zero-Latency Gaming Fast-Path
                # In games, holding down keys (e.g. WASD, Space, Shift) and releasing them sends KeyUp.
                # If Python holds the GIL (e.g. during speech playback, TTS synthesis, or VAD),
                # queuing KeyUp in WindowServer causes 'extended key presses' where the player keeps moving.
                # VoiceFi NEVER acts on KeyUp while speech is active, and only acts on KeyUp when
                # actively recording in PTT mode for specific action keys.
                if event_type == _k_key_up:
                    vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                    # Modifier release must be tracked so chord states stay clean
                    if vk in _MODIFIER_VKS:
                        if _orig_handler is not None:
                            return _orig_handler(self, proxy, event_type, event, refcon)
                        return event

                    # Instant Sub-Microsecond Bypass for 100% of Non-PTT Keys:
                    # In games, releasing W, A, S, Space, Esc, Tab, E, Q, F, numbers, etc.
                    # returns immediately to macOS WindowServer in <20ns without Python locks or imports!
                    if vk not in _PTT_VKS:
                        return event

                    # For PTT keys (17=Ctrl+T, 2=Opt+D, 15=R, 9=Opt+V, 45=N):
                    # Check if speech is active -> 100% bypass on all KeyUps while speaking!
                    try:
                        from voicefi.tts.base import is_agent_speaking, is_agent_audio_playing

                        if is_agent_speaking() or is_agent_audio_playing():
                            return event
                    except Exception:
                        pass

                    # When not speaking, only dispatch KeyUp if actively recording in VoiceFi PTT mode
                    try:
                        from voicefi.tts.base import is_mic_recording_active

                        if is_mic_recording_active(include_external=False):
                            if _orig_handler is not None:
                                return _orig_handler(self, proxy, event_type, event, refcon)
                    except Exception:
                        pass
                    return event

                # 3. KeyDown:
                if event_type == _k_key_down:
                    vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)

                    # 3.1 Escape (53): Always process so user can stop speech or cancel recording instantly
                    if vk == 53:
                        if _orig_handler is not None:
                            return _orig_handler(self, proxy, event_type, event, refcon)
                        return event

                    # 3.2 Return / Enter (36, 76): Only process if actively recording
                    if vk in (36, 76):
                        try:
                            from voicefi.tts.base import is_mic_recording_active, is_agent_speaking

                            if not is_agent_speaking() and is_mic_recording_active(include_external=False):
                                if _orig_handler is not None:
                                    return _orig_handler(self, proxy, event_type, event, refcon)
                        except Exception:
                            pass
                        return event

                    # 3.3 Fast Non-Hotkey Bypass: If vk is not one of VoiceFi's action keys
                    # (e.g. W, S, E, Q, F, Z, X, 1-9, Arrows, etc.), bypass in <1us without Python overhead!
                    if vk not in _HOTKEY_VKS:
                        return event

                    # 3.4 For keys in _HOTKEY_VKS (A, D, C, R, Space, Tab, T, V, J, N):
                    # They are ONLY VoiceFi hotkeys if Alt (Option), Control, or Command is held!
                    flags = Quartz.CGEventGetFlags(event)
                    _mask_mod = (
                        Quartz.kCGEventFlagMaskAlternate
                        | Quartz.kCGEventFlagMaskControl
                        | Quartz.kCGEventFlagMaskCommand
                    )
                    if not (flags & _mask_mod):
                        # Bare WASD movement (A=0, D=2), bare space jump (49), bare crouch (8), etc.
                        # Impossible to be a VoiceFi hotkey -> zero-latency bypass!
                        return event

                    # 3.5 While speech is active, only Escape (handled above), Option+Tab (vk=48),
                    # and Option/Ctrl+Space (vk=49) ever matter
                    try:
                        from voicefi.tts.base import is_agent_speaking, is_agent_audio_playing
                        if is_agent_speaking() or is_agent_audio_playing():
                            _mask_alt = Quartz.kCGEventFlagMaskAlternate
                            _mask_ctrl = Quartz.kCGEventFlagMaskControl
                            is_opt_tab = (vk == 48 and bool(flags & _mask_alt))
                            is_quick_bar = (vk == 49 and bool(flags & (_mask_alt | _mask_ctrl)))
                            if not (is_opt_tab or is_quick_bar):
                                return event
                    except Exception:
                        pass

                    if _orig_handler is not None:
                        return _orig_handler(self, proxy, event_type, event, refcon)
                    return event

                if _orig_handler is not None:
                    return _orig_handler(self, proxy, event_type, event, refcon)
                return event

            def _listen_only_create_event_tap(self):
                import Quartz

                # CRITICAL: Always use kCGEventTapOptionListenOnly (1) instead of kCGEventTapOptionDefault (0)!
                # A kCGEventTapOptionDefault tap blocks macOS WindowServer from delivering ANY keystroke to
                # games/apps whenever the Python process holds the GIL (e.g. during turn-end TTS synthesis,
                # Silero VAD, or Whisper STT), which locks up the user's keyboard at turn end!
                # Using kCGTailAppendEventTap places the passive listener at the end of the event chain,
                # ensuring active games and frontmost windows receive events first with zero delay.
                return Quartz.CGEventTapCreate(
                    Quartz.kCGSessionEventTap,
                    Quartz.kCGTailAppendEventTap,
                    Quartz.kCGEventTapOptionListenOnly,
                    self._EVENTS,
                    self._handler,
                    None,
                )

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
                    self._tap = _listen_only_create_event_tap(self)
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

            pynput_darwin.ListenerMixin._handler = _safe_darwin_handler
            pynput_darwin.ListenerMixin._create_event_tap = _listen_only_create_event_tap
            pynput_darwin.ListenerMixin._run = _clean_darwin_run
            pynput_darwin.ListenerMixin._stop_platform = _clean_darwin_stop

        _pynput_patched = True
    except ImportError:
        pass
    except Exception:
        pass
