/**
 * VoiceFi Dynamic Island HUD Web Controller & Reactive SVG Engine
 * Shared between macOS Companion HUD, Web Mocks, and voicefi.org
 * 
 * Supports states: 'idle', 'thinking', 'speaking', 'listening', 'working'
 */

(function (global) {
  'use strict';

  /**
   * Generates the anatomical VoiceFi reactive character SVG logo mark.
   * State dynamically shifts lighting across Wi-Fi hat, eyes/nose, mouth/jaw, and ear waves.
   */
  function getVoiceFiReactiveSVG(state = 'idle') {
    const validStates = ['idle', 'thinking', 'speaking', 'listening', 'working'];
    const safeState = validStates.includes(state) ? state : 'idle';
    const stateClass = `vifi-active-${safeState}`;

    return `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="50 50 412 412" class="w-full h-full object-contain ${stateClass}" style="overflow: visible;" aria-label="VoiceFi Status: ${safeState}">
        <g transform="translate(0, 15)">
          <g class="vifi-wifi-group" fill="none" stroke-linecap="round">
            <path class="vifi-wifi-crown" d="M 152 145 A 120 120 0 0 1 360 145" stroke="#FFFFFF" stroke-width="18" />
            <path class="vifi-wifi-visor" d="M 184 180 A 80 80 0 0 1 328 180" stroke="#FFFFFF" stroke-width="17" />
            <path class="vifi-wifi-brim" d="M 216 215 A 42 42 0 0 1 296 215" stroke="#FFFFFF" stroke-width="16" />
          </g>
          <g class="vifi-eyes-group" stroke-linecap="round">
            <line class="vifi-eyes vifi-eye-left" x1="202" y1="262" x2="234" y2="262" stroke="#FFFFFF" stroke-width="8" />
            <line class="vifi-eyes vifi-eye-right" x1="278" y1="262" x2="310" y2="262" stroke="#FFFFFF" stroke-width="8" />
          </g>
          <g class="vifi-nose-group">
            <rect class="vifi-nose-frame" x="238" y="278" width="36" height="15" rx="7.5" fill="#000000" stroke="#FFFFFF" stroke-width="2.5" />
            <line class="vifi-nose-pin" x1="246" y1="285.5" x2="266" y2="285.5" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round" />
          </g>
          <path class="vifi-mouth" d="M 230 320 Q 256 342 282 320" fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" />
          <path class="vifi-cradle" d="M 124 220 C 124 350, 175 385, 256 385 C 337 385, 388 350, 388 220" fill="none" stroke="#FFFFFF" stroke-width="12" stroke-linecap="round" />
          <g class="vifi-ear-left">
            <rect class="vifi-ear-frame" x="110" y="205" width="28" height="30" rx="6" fill="#000000" stroke="#FFFFFF" stroke-width="3.5" />
            <circle class="vifi-ear-dot vifi-ear-dot-l" cx="124" cy="220" r="4.5" fill="#FFFFFF" />
          </g>
          <g class="vifi-ear-right">
            <rect class="vifi-ear-frame" x="374" y="205" width="28" height="30" rx="6" fill="#000000" stroke="#FFFFFF" stroke-width="3.5" />
            <circle class="vifi-ear-dot vifi-ear-dot-r" cx="388" cy="220" r="4.5" fill="#FFFFFF" />
          </g>
          <g class="vifi-ear-waves" fill="none" stroke-linecap="round">
            <path class="vifi-ear-wave" d="M 96 206 A 18 18 0 0 0 96 234" stroke="#ff0033" stroke-width="9" />
            <path class="vifi-ear-wave" d="M 80 196 A 34 34 0 0 0 80 244" stroke="#ff0033" stroke-width="10.5" />
            <path class="vifi-ear-wave" d="M 64 186 A 50 50 0 0 0 64 254" stroke="#ff0033" stroke-width="12" />
            <path class="vifi-ear-wave" d="M 416 206 A 18 18 0 0 1 416 234" stroke="#ff0033" stroke-width="9" />
            <path class="vifi-ear-wave" d="M 432 196 A 34 34 0 0 1 432 244" stroke="#ff0033" stroke-width="10.5" />
            <path class="vifi-ear-wave" d="M 448 186 A 50 50 0 0 1 448 254" stroke="#ff0033" stroke-width="12" />
          </g>
          <line class="vifi-stem" x1="256" y1="385" x2="256" y2="430" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round" />
          <line class="vifi-base-stand" x1="190" y1="430" x2="322" y2="430" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round" />
        </g>
      </svg>
    `;
  }

  /**
   * Updates a mounted Dynamic Island HUD container.
   */
  function updateVoiceFiHud(state, options = {}) {
    const safeState = ['idle', 'speaking', 'thinking', 'working', 'listening'].includes(state) ? state : 'idle';
    const title = options.title || 'VoiceFi';
    const tag = options.tag || '';
    const tagColor = options.tagColor || 'text-slate-300';
    const body = options.body || 'Standing by • Dictate (⌃T) or speak to agent (⌃R)';
    const showAppIcon = options.showAppIcon !== undefined ? options.showAppIcon : true;
    const personaName = options.personaName || null;

    const capsule = document.getElementById('simLiveHudCapsule');
    const logoHost = document.getElementById('simHudLogoHost');
    const titleEl = document.getElementById('simHudTitle');
    const tagEl = document.getElementById('simHudTag');
    const bodyEl = document.getElementById('simHudBodyText');
    const waveBars = document.getElementById('simHudWaveBars');
    const thinkingBadge = document.getElementById('simHudThinkingBadge');
    const workingBadge = document.getElementById('simHudWorkingBadge');
    const vadVisualizer = document.getElementById('simHudVadVisualizer');
    const appBadge = document.getElementById('simHudAppBadge');

    // 1. Inject Reactive Vector SVG Mark
    if (logoHost) {
      logoHost.innerHTML = getVoiceFiReactiveSVG(state);
    }

    // 2. Update Titles & Status Tag
    if (titleEl) titleEl.innerText = title;
    if (tagEl) {
      tagEl.innerText = tag;
      tagEl.className = `text-[10px] sm:text-[11px] font-medium truncate ${tagColor}`;
    }

    // 3. Update Spoken Subtitle Body Text
    if (bodyEl) {
      bodyEl.innerText = body;
    }

    // 4. Update Aura Halos & Right Visualizers
    if (capsule) {
      capsule.classList.remove('glow-speaking', 'glow-thinking', 'glow-working', 'glow-listening', 'hud-state-idle', 'hud-state-listening', 'hud-state-speaking', 'hud-state-thinking', 'hud-state-working');
      capsule.classList.add('hud-state-' + safeState);
    }
    if (waveBars) {
      waveBars.classList.add('hidden');
      waveBars.classList.remove('flex');
    }
    if (thinkingBadge) {
      thinkingBadge.classList.add('hidden');
      thinkingBadge.classList.remove('flex');
    }
    if (workingBadge) {
      workingBadge.classList.add('hidden');
      workingBadge.classList.remove('flex');
    }
    if (vadVisualizer) {
      vadVisualizer.classList.add('hidden');
      vadVisualizer.classList.remove('flex');
    }

    if (state === 'speaking') {
      if (waveBars) {
        waveBars.classList.remove('hidden');
        waveBars.classList.add('flex');
      }
    } else if (state === 'thinking') {
      if (thinkingBadge) {
        thinkingBadge.classList.remove('hidden');
        thinkingBadge.classList.add('flex');
      }
    } else if (state === 'working') {
      if (workingBadge) {
        workingBadge.classList.remove('hidden');
        workingBadge.classList.add('flex');
      }
    } else if (state === 'listening') {
      if (vadVisualizer) {
        vadVisualizer.classList.remove('hidden');
        vadVisualizer.classList.add('flex');
      }
    }

    // 5. Update Connected App / Persona Logo Badge
    if (appBadge) {
      if (showAppIcon) {
        appBadge.style.display = 'flex';
        const name = personaName || (typeof window !== 'undefined' && window.selectedVoiceKey && typeof voicePersonas !== 'undefined' && voicePersonas[window.selectedVoiceKey] ? voicePersonas[window.selectedVoiceKey].name : null);
        if (state === 'speaking' && name) {
          appBadge.innerText = (name === 'Christopher' ? '🧔' : (name === 'Viv' ? '✨' : (name === 'Aria' ? '⚡' : (name === 'Emily' ? '🍀' : (name === 'Sonia' ? '🔬' : '🤖')))));
        } else {
          appBadge.innerText = '🤖';
        }
      } else {
        appBadge.style.display = 'flex';
        appBadge.innerText = '🎙️';
      }
    }
  }

  // Export globally
  global.getVoiceFiReactiveSVG = getVoiceFiReactiveSVG;
  global.updateVoiceFiHud = updateVoiceFiHud;
  global.updateSimHud = function (state, title, tag, tagColor, body, showAppIcon) {
    updateVoiceFiHud(state, { title, tag, tagColor, body, showAppIcon });
  };

})(typeof window !== 'undefined' ? window : globalThis);
