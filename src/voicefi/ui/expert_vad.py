"""
Expert VAD & Acoustic Inspector Panel.
Provides an interactive, native macOS floating panel with real-time audio oscilloscope, 
neural speech confidence metrics, and fine-tuning sliders for Voice Activity Detection.
"""

import threading
import time
from typing import Optional, Any
import numpy as np
import math

from AppKit import (
    NSPanel,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextAlignmentRight,
    NSButton,
    NSBezelStyleRounded,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSBezierPath,
    NSSlider,
    NSSegmentedControl,
    NSSegmentStyleTexturedRounded,
    NSLayoutConstraint,
    NSLayoutAttributeCenterX,
    NSLayoutAttributeCenterY,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
)
import objc
from PyObjCTools import AppHelper

from voicefi.config import load_config, save_config
from voicefi.audio.monitor import LiveVADMonitor
from voicefi.audio.device import is_using_builtin_speakers


try:
    ExpertActionTarget = objc.lookUpClass("ExpertActionTarget")
except objc.nosuchclass_error:
    class ExpertActionTarget(objc.lookUpClass("NSObject")):
        def initWithCallback_(self, callback):
            self = objc.super(ExpertActionTarget, self).init()
            if self is not None:
                self.callback = callback
            return self

        def actionHandler_(self, sender):
            if self.callback:
                self.callback(sender)


try:
    VADOscilloscopeView = objc.lookUpClass("VADOscilloscopeView")
except objc.nosuchclass_error:
    class VADOscilloscopeView(objc.lookUpClass("NSView")):
        def initWithFrame_(self, frame):
            self = objc.super(VADOscilloscopeView, self).initWithFrame_(frame)
            if self is not None:
                self._history_len = 100
                self._energy_history = [0.0] * self._history_len
                self._noise_history = [0.0] * self._history_len
                self._trigger_thresh = 0.004
                self._is_speech = False
                self._prob = 0.0
            return self

        @objc.python_method
        def update_data(self, energy, noise, thresh, prob, is_speech):
            self._energy_history.pop(0)
            self._energy_history.append(energy)
            self._noise_history.pop(0)
            self._noise_history.append(noise)
            self._trigger_thresh = thresh
            self._prob = prob
            self._is_speech = is_speech
            
            # Request redraw on main thread
            self.setNeedsDisplay_(True)

        def drawRect_(self, dirtyRect):
            bounds = self.bounds()
            w = bounds.size.width
            h = bounds.size.height

            # Background
            NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.4).setFill()
            NSBezierPath.fillRect_(bounds)

            # Max scale value to normalize visually
            max_scale = max(0.02, max(self._energy_history) * 1.2, self._trigger_thresh * 1.5)

            # Draw Speech Probability Background Glow
            if self._is_speech:
                glow_h = h * self._prob
                glow_rect = NSRect(NSPoint(0, 0), NSSize(w, glow_h))
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.3, 0.3, 0.15).setFill()
                NSBezierPath.fillRect_(glow_rect)

            dx = w / (self._history_len - 1)

            # Draw Threshold Line
            thresh_y = h * min(1.0, self._trigger_thresh / max_scale)
            thresh_path = NSBezierPath.bezierPath()
            thresh_path.moveToPoint_(NSPoint(0, thresh_y))
            thresh_path.lineToPoint_(NSPoint(w, thresh_y))
            dash = [4.0, 4.0]
            thresh_path.setLineDash_count_phase_(dash, 2, 0.0)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.8, 0.2, 0.8).setStroke()
            thresh_path.setLineWidth_(1.5)
            thresh_path.stroke()

            # Draw Noise Floor Line
            current_noise = self._noise_history[-1]
            noise_y = h * min(1.0, current_noise / max_scale)
            noise_path = NSBezierPath.bezierPath()
            noise_path.moveToPoint_(NSPoint(0, noise_y))
            noise_path.lineToPoint_(NSPoint(w, noise_y))
            noise_path.setLineDash_count_phase_(dash, 2, 0.0)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.6, 1.0, 0.8).setStroke()
            noise_path.setLineWidth_(1.5)
            noise_path.stroke()

            # Draw Energy Waveform
            path = NSBezierPath.bezierPath()
            for i, val in enumerate(self._energy_history):
                x = i * dx
                y = h * min(1.0, val / max_scale)
                if i == 0:
                    path.moveToPoint_(NSPoint(x, y))
                else:
                    path.lineToPoint_(NSPoint(x, y))

            if self._is_speech:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.9, 0.5, 1.0).setStroke()
            else:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.7, 0.9, 1.0).setStroke()
                
            path.setLineWidth_(2.0)
            path.stroke()


class ExpertVADPanel:
    """Singleton Floating Expert VAD Inspector."""
    _instance: Optional["ExpertVADPanel"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ExpertVADPanel":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = load_config()
        self._panel: Optional[NSPanel] = None
        self._targets = []
        self._is_visible = False
        
        self.lbl_energy = None
        self.lbl_noise = None
        self.lbl_prob = None
        self.lbl_barge = None
        
        self.slider_speech = None
        self.slider_energy = None
        self.slider_silence = None
        self.seg_engine = None
        
        self.val_speech = None
        self.val_energy = None
        self.val_silence = None

        self._build_panel()

    def _build_panel(self):
        w, h = 480, 380
        rect = NSRect(NSPoint(1200, 500), NSSize(w, h))
        style_mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskNonactivatingPanel
            | NSWindowStyleMaskFullSizeContentView
        )
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self._panel.setTitle_("🎙️ VoiceFi • Expert VAD & Acoustic Inspector")
        self._panel.setLevel_(NSFloatingWindowLevel)
        self._panel.setFloatingPanel_(True)
        self._panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
        
        # Transparent background for Visual Effect
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setTitlebarAppearsTransparent_(True)

        effect_view = NSVisualEffectView.alloc().initWithFrame_(rect)
        effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect_view.setState_(1)
        
        # Scope box
        scope_rect = NSRect(NSPoint(20, h - 140), NSSize(w - 40, 90))
        self.oscilloscope = VADOscilloscopeView.alloc().initWithFrame_(scope_rect)
        self.oscilloscope.setWantsLayer_(True)
        self.oscilloscope.layer().setCornerRadius_(8.0)
        self.oscilloscope.layer().setMasksToBounds_(True)
        effect_view.addSubview_(self.oscilloscope)
        
        # Telemetry Text Labels
        def _make_lbl(x, y, w, h, size=11, bold=False):
            lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(x, y), NSSize(w, h)))
            lbl.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
            lbl.setTextColor_(NSColor.whiteColor())
            lbl.setBezeled_(False)
            lbl.setDrawsBackground_(False)
            lbl.setEditable_(False)
            return lbl

        self.lbl_energy = _make_lbl(20, h - 170, 100, 20, 12, True)
        self.lbl_noise = _make_lbl(130, h - 170, 100, 20, 12, True)
        self.lbl_prob = _make_lbl(240, h - 170, 120, 20, 12, True)
        self.lbl_barge = _make_lbl(20, h - 190, 400, 20, 11)

        effect_view.addSubview_(self.lbl_energy)
        effect_view.addSubview_(self.lbl_noise)
        effect_view.addSubview_(self.lbl_prob)
        effect_view.addSubview_(self.lbl_barge)

        # Controls
        controls_y = h - 230
        
        # Engine Selector
        engine_lbl = _make_lbl(20, controls_y, 100, 20)
        engine_lbl.setStringValue_("VAD Engine:")
        effect_view.addSubview_(engine_lbl)
        
        self.seg_engine = NSSegmentedControl.alloc().initWithFrame_(NSRect(NSPoint(120, controls_y), NSSize(340, 24)))
        self.seg_engine.setSegmentCount_(3)
        self.seg_engine.setLabel_forSegment_("Auto Hybrid", 0)
        self.seg_engine.setLabel_forSegment_("Silero AI", 1)
        self.seg_engine.setLabel_forSegment_("Energy", 2)
        self.seg_engine.setSegmentStyle_(NSSegmentStyleTexturedRounded)
        
        current_eng = self.config.vad.engine
        idx = 0 if current_eng == "auto" else 1 if current_eng == "silero" else 2
        self.seg_engine.setSelectedSegment_(idx)
        
        target_engine = ExpertActionTarget.alloc().initWithCallback_(self._on_engine_change)
        self._targets.append(target_engine)
        self.seg_engine.setTarget_(target_engine)
        self.seg_engine.setAction_("actionHandler:")
        effect_view.addSubview_(self.seg_engine)
        
        # Sliders
        controls_y -= 40
        self.slider_speech, self.val_speech = self._add_slider_row(effect_view, "Speech Prob:", 20, controls_y, 0.1, 0.9, self.config.vad.speech_threshold, self._on_speech_change)
        
        controls_y -= 30
        self.slider_energy, self.val_energy = self._add_slider_row(effect_view, "Energy Thresh:", 20, controls_y, 0.001, 0.050, self.config.vad.energy_threshold, self._on_energy_change)
        
        controls_y -= 30
        self.slider_silence, self.val_silence = self._add_slider_row(effect_view, "Silence Cutoff:", 20, controls_y, 0.4, 3.0, self.config.vad.silence_duration, self._on_silence_change)
        
        # Buttons
        controls_y -= 45
        btn_cal = NSButton.alloc().initWithFrame_(NSRect(NSPoint(20, controls_y), NSSize(160, 24)))
        btn_cal.setTitle_("🎯 Calibrate Room Noise")
        btn_cal.setBezelStyle_(NSBezelStyleRounded)
        target_cal = ExpertActionTarget.alloc().initWithCallback_(self._on_calibrate)
        self._targets.append(target_cal)
        btn_cal.setTarget_(target_cal)
        btn_cal.setAction_("actionHandler:")
        effect_view.addSubview_(btn_cal)

        self._panel.setContentView_(effect_view)

    def _add_slider_row(self, view, label, x, y, min_val, max_val, cur_val, callback):
        lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(x, y), NSSize(100, 20)))
        lbl.setStringValue_(label)
        lbl.setFont_(NSFont.systemFontOfSize_(11))
        lbl.setTextColor_(NSColor.whiteColor())
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        view.addSubview_(lbl)
        
        slider = NSSlider.alloc().initWithFrame_(NSRect(NSPoint(x + 100, y), NSSize(280, 20)))
        slider.setMinValue_(min_val)
        slider.setMaxValue_(max_val)
        slider.setFloatValue_(float(cur_val))
        
        target = ExpertActionTarget.alloc().initWithCallback_(callback)
        self._targets.append(target)
        slider.setTarget_(target)
        slider.setAction_("actionHandler:")
        view.addSubview_(slider)
        
        val_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(x + 390, y), NSSize(50, 20)))
        val_lbl.setStringValue_(f"{cur_val:.3f}")
        val_lbl.setFont_(NSFont.boldSystemFontOfSize_(11))
        val_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.8, 1.0, 1.0))
        val_lbl.setBezeled_(False)
        val_lbl.setDrawsBackground_(False)
        val_lbl.setEditable_(False)
        view.addSubview_(val_lbl)
        
        return slider, val_lbl

    def _on_engine_change(self, sender):
        idx = sender.selectedSegment()
        eng = "auto" if idx == 0 else "silero" if idx == 1 else "energy"
        self.config.vad.engine = eng
        self._apply_config()

    def _on_speech_change(self, sender):
        val = sender.floatValue()
        self.val_speech.setStringValue_(f"{val:.2f}")
        self.config.vad.speech_threshold = round(val, 2)
        self._apply_config()

    def _on_energy_change(self, sender):
        val = sender.floatValue()
        self.val_energy.setStringValue_(f"{val:.4f}")
        self.config.vad.energy_threshold = round(val, 4)
        self._apply_config()

    def _on_silence_change(self, sender):
        val = sender.floatValue()
        self.val_silence.setStringValue_(f"{val:.2f}s")
        self.config.vad.silence_duration = round(val, 2)
        self._apply_config()

    def _on_calibrate(self, sender):
        try:
            from voicefi.troubleshoot import AudioTroubleshooter
            t = AudioTroubleshooter(self.config)
            def _cal():
                res = t.test_microphone_loopback(duration_seconds=1.5, play_back=False)
                if res.success:
                    suggested = max(min(res.rms_energy * 1.5, 0.02), 0.002)
                    AppHelper.callAfter(self._set_calibrated_energy, suggested)
            threading.Thread(target=_cal, daemon=True).start()
        except Exception:
            pass

    def _set_calibrated_energy(self, val):
        self.slider_energy.setFloatValue_(val)
        self.val_energy.setStringValue_(f"{val:.4f}")
        self.config.vad.energy_threshold = round(val, 4)
        self._apply_config()

    def _apply_config(self):
        save_config(self.config)
        # Hot-reload monitor
        LiveVADMonitor.get_instance().reload_config()

    def _on_audio_data(self, energy, prob, is_speech, raw_chunk, noise_floor, active_thresh):
        if not self._is_visible:
            return
            
        def _update():
            if self.oscilloscope:
                self.oscilloscope.update_data(energy, noise_floor, active_thresh, prob, is_speech)
            
            if self.lbl_energy:
                self.lbl_energy.setStringValue_(f"RMS: {energy:.4f}")
            if self.lbl_noise:
                self.lbl_noise.setStringValue_(f"Noise: {noise_floor:.4f}")
            if self.lbl_prob:
                self.lbl_prob.setStringValue_(f"AI: {prob*100:.1f}%")
                
            if self.lbl_barge:
                builtin = is_using_builtin_speakers()
                safe = "Safe Mode" if builtin else "Full Duplex 0ms"
                self.lbl_barge.setStringValue_(f"Barge-In: {safe}")
                
        AppHelper.callAfter(_update)

    def show(self, relative_to_rect: Optional[NSRect] = None):
        if not self._panel:
            return
            
        def _do_show():
            if relative_to_rect:
                x = relative_to_rect.origin.x + (relative_to_rect.size.width - self._panel.frame().size.width) / 2
                y = relative_to_rect.origin.y - self._panel.frame().size.height - 10
                self._panel.setFrameOrigin_(NSPoint(x, y))
                
            LiveVADMonitor.get_instance().add_listener(self._on_audio_data)
            self._panel.orderFrontRegardless()
            self._is_visible = True
            
        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            AppHelper.callAfter(_do_show)

    def hide(self):
        if not self._panel:
            return
            
        def _do_hide():
            self._panel.orderOut_(None)
            self._is_visible = False
            LiveVADMonitor.get_instance().remove_listener(self._on_audio_data)
            
        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def toggle(self, relative_to_rect: Optional[NSRect] = None):
        if self._is_visible:
            self.hide()
        else:
            self.show(relative_to_rect)
