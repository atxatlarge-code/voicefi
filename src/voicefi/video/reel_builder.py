"""
VoiceFi™ Social Reel & Video Compiler.
Builds multi-format social video reels (9:16 Vertical, 1:1 Square, 4:5 Portrait, 16:9 Widescreen)
from master voice audio tracks, with box-filling typography scaling, avatar presets, and synced captions.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

# Official Logos & Avatars
ANTIGRAVITY_LOGO_SVG = """<svg viewBox="10 16 92 82" width="100%" height="100%" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <mask id="ag-mask-vid" maskUnits="userSpaceOnUse" x="10" y="15" width="92" height="85">
      <path d="M89.6992 93.695C94.3659 97.195 101.366 94.8617 94.9492 88.445C75.6992 69.7783 79.7825 18.445 55.8659 18.445C31.9492 18.445 36.0325 69.7783 16.7825 88.445C9.78251 95.445 17.3658 97.195 22.0325 93.695C40.1159 81.445 38.9492 59.8617 55.8659 59.8617C72.7825 59.8617 71.6159 81.445 89.6992 93.695Z" fill="#FFFFFF"/>
    </mask>
  </defs>
  <path d="M89.6992 93.695C94.3659 97.195 101.366 94.8617 94.9492 88.445C75.6992 69.7783 79.7825 18.445 55.8659 18.445C31.9492 18.445 36.0325 69.7783 16.7825 88.445C9.78251 95.445 17.3658 97.195 22.0325 93.695C40.1159 81.445 38.9492 59.8617 55.8659 59.8617C72.7825 59.8617 71.6159 81.445 89.6992 93.695Z" fill="#3186FF"/>
  <g mask="url(#ag-mask-vid)">
    <circle cx="56" cy="26" r="22" fill="#FFE432"/>
    <circle cx="94" cy="38" r="26" fill="#FC413D"/>
    <circle cx="16" cy="46" r="26" fill="#00B95C"/>
    <circle cx="75" cy="98" r="24" fill="#3186FF"/>
  </g>
</svg>"""

CLAUDE_LOGO_SVG = """<svg viewBox="0 0 100 100" width="100%" height="100%" fill="#D97757" xmlns="http://www.w3.org/2000/svg">
  <path d="m19.6 66.5 19.7-11 .3-1-.3-.5h-1l-3.3-.2-11.2-.3L14 53l-9.5-.5-2.4-.5L0 49l.2-1.5 2-1.3 2.9.2 6.3.5 9.5.6 6.9.4L38 49.1h1.6l.2-.7-.5-.4-.4-.4L29 41l-10.6-7-5.6-4.1-3-2-1.5-2-.6-4.2 2.7-3 3.7.3.9.2 3.7 2.9 8 6.1L37 36l1.5 1.2.6-.4.1-.3-.7-1.1L33 25l-6-10.4-2.7-4.3-.7-2.6c-.3-1-.4-2-.4-3l3-4.2L28 0l4.2.6L33.8 2l2.6 6 4.1 9.3L47 29.9l2 3.8 1 3.4.3 1h.7v-.5l.5-7.2 1-8.7 1-11.2.3-3.2 1.6-3.8 3-2L61 2.6l2 2.9-.3 1.8-1.1 7.7L59 27.1l-1.5 8.2h.9l1-1.1 4.1-5.4 6.9-8.6 3-3.5L77 13l2.3-1.8h4.3l3.1 4.7-1.4 4.9-4.4 5.6-3.7 4.7-5.3 7.1-3.2 5.7.3.4h.7l12-2.6 6.4-1.1 7.6-1.3 3.5 1.6.4 1.6-1.4 3.4-8.2 2-9.6 2-14.3 3.3-.2.1.2.3 6.4.6 2.8.2h6.8l12.6 1 3.3 2 1.9 2.7-.3 2-5.1 2.6-6.8-1.6-16-3.8-5.4-1.3h-.8v.4l4.6 4.5 8.3 7.5L89 80.1l.5 2.4-1.3 2-1.4-.2-9.2-7-3.6-3-8-6.8h-.5v.7l1.8 2.7 9.8 14.7.5 4.5-.7 1.4-2.6 1-2.7-.6-5.8-8-6-9-4.7-8.2-.5.4-2.9 30.2-1.3 1.5-3 1.2-2.5-2-1.4-3 1.4-6.2 1.6-8 1.3-6.4 1.2-7.9.7-2.6v-.2H49L43 72l-9 12.3-7.2 7.6-1.7.7-3-1.5.3-2.8L24 86l10-12.8 6-7.9 4-4.6-.1-.5h-.3L17.2 77.4l-4.7.6-2-2 .2-3 1-1 8-5.5Z"></path>
</svg>"""

VOICEFI_LOGO_SVG = """<svg viewBox="68 68 376 388" width="100%" height="100%" fill="none" xmlns="http://www.w3.org/2000/svg">
  <g transform="translate(0, 5)">
    <g stroke="#FF2A2A" stroke-linecap="round" fill="none">
      <path d="M 152 145 A 120 120 0 0 1 360 145" stroke-width="26" />
      <path d="M 184 180 A 80 80 0 0 1 328 180" stroke-width="24" />
      <path d="M 216 215 A 42 42 0 0 1 296 215" stroke-width="22" />
    </g>
    <g stroke="#FFFFFF" stroke-width="14" stroke-linecap="round">
      <line x1="202" y1="262" x2="234" y2="262" />
      <line x1="278" y1="262" x2="310" y2="262" />
    </g>
    <rect x="236" y="276" width="40" height="18" rx="9" fill="#000000" stroke="#FF2A2A" stroke-width="4" />
    <line x1="246" y1="285" x2="266" y2="285" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" />
    <path d="M 228 322 Q 256 348 284 322" fill="none" stroke="#FF2A2A" stroke-width="8" stroke-linecap="round" />
    <path d="M 124 220 C 124 350, 175 385, 256 385 C 337 385, 388 350, 388 220" fill="none" stroke="#FFFFFF" stroke-width="20" stroke-linecap="round" />
    <rect x="108" y="202" width="32" height="34" rx="7" fill="#000000" stroke="#FFFFFF" stroke-width="4.5" />
    <circle cx="124" cy="219" r="5.5" fill="#FF2A2A" />
    <rect x="372" y="202" width="32" height="34" rx="7" fill="#000000" stroke="#FFFFFF" stroke-width="4.5" />
    <circle cx="388" cy="219" r="5.5" fill="#FF2A2A" />
    <line x1="256" y1="385" x2="256" y2="435" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" />
    <line x1="185" y1="435" x2="327" y2="435" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" />
  </g>
</svg>"""

RADIO_HOST_LOGO_SVG = """<svg viewBox="0 0 100 100" width="100%" height="100%" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="44" fill="rgba(239,68,68,0.18)" stroke="#EF4444" stroke-width="3.5"/>
  <rect x="38" y="22" width="24" height="34" rx="12" fill="#EF4444" stroke="#FFFFFF" stroke-width="3"/>
  <line x1="44" y1="30" x2="56" y2="30" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="44" y1="36" x2="56" y2="36" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="44" y1="42" x2="56" y2="42" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M28 44 C28 58 38 68 50 68 C62 68 72 58 72 44" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round"/>
  <line x1="50" y1="68" x2="50" y2="82" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round"/>
  <line x1="34" y1="82" x2="66" y2="82" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round"/>
</svg>"""

JAKE_LOGO_SVG = """<svg viewBox="0 0 100 100" width="100%" height="100%" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="44" fill="rgba(139,92,246,0.2)" stroke="#8B5CF6" stroke-width="3.5"/>
  <circle cx="50" cy="38" r="15" fill="#8B5CF6" stroke="#FFFFFF" stroke-width="2.5"/>
  <path d="M26 78 C26 64 36 57 50 57 C64 57 74 64 74 78" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" fill="none"/>
</svg>"""

VOICEFI_MASTER_LOCKUP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 590 120" width="100%" height="100%">
  <defs>
    <linearGradient id="vfDarkSymRed" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FF3B30" />
      <stop offset="50%" stop-color="#FF2A2A" />
      <stop offset="100%" stop-color="#E0002A" />
    </linearGradient>
  </defs>
  <g id="voicefi-logo-group">
    <g transform="translate(0, 4) scale(0.28)">
      <g transform="translate(-68, -63)">
        <g stroke="url(#vfDarkSymRed)" stroke-linecap="round" fill="none">
          <path d="M 152 145 A 120 120 0 0 1 360 145" stroke-width="26" />
          <path d="M 184 180 A 80 80 0 0 1 328 180" stroke-width="24" />
          <path d="M 216 215 A 42 42 0 0 1 296 215" stroke-width="22" />
        </g>
        <g stroke="#FFFFFF" stroke-width="14" stroke-linecap="round">
          <line x1="202" y1="262" x2="234" y2="262" />
          <line x1="278" y1="262" x2="310" y2="262" />
        </g>
        <rect x="236" y="276" width="40" height="18" rx="9" fill="#000000" stroke="#FF2A2A" stroke-width="4" />
        <line x1="246" y1="285" x2="266" y2="285" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" />
        <path d="M 228 322 Q 256 348 284 322" fill="none" stroke="#FF2A2A" stroke-width="8" stroke-linecap="round" />
        <path d="M 124 220 C 124 350, 175 385, 256 385 C 337 385, 388 350, 388 220" fill="none" stroke="#FFFFFF" stroke-width="20" stroke-linecap="round" />
        <rect x="108" y="202" width="32" height="34" rx="7" fill="#000000" stroke="#FFFFFF" stroke-width="4.5" />
        <circle cx="124" cy="219" r="5.5" fill="#FF2A2A" />
        <rect x="372" y="202" width="32" height="34" rx="7" fill="#000000" stroke="#FFFFFF" stroke-width="4.5" />
        <circle cx="388" cy="219" r="5.5" fill="#FF2A2A" />
        <line x1="256" y1="385" x2="256" y2="435" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" />
        <line x1="185" y1="435" x2="327" y2="435" stroke="#FFFFFF" stroke-width="22" stroke-linecap="round" />
      </g>
    </g>
    <g transform="translate(122, -1)">
      <path d="M44.60 100L26.60 100L1.10 25.50L18.10 25.50L35.60 80L53.10 25.50L70.10 25.50L44.60 100Z" fill="#FF2A2A" />
      <path d="M95.30 101.20L95.30 101.20Q87.20 101.20 80.55 97.50Q73.90 93.80 69.95 87.35Q66 80.90 66 72.70L66 72.70Q66 64.40 69.95 58Q73.90 51.60 80.55 47.90Q87.20 44.20 95.30 44.20L95.30 44.20Q103.40 44.20 110 47.90Q116.60 51.60 120.55 58Q124.50 64.40 124.50 72.70L124.50 72.70Q124.50 80.90 120.55 87.35Q116.60 93.80 110 97.50Q103.40 101.20 95.30 101.20ZM95.30 87.70L95.30 87.70Q99.40 87.70 102.45 85.80Q105.50 83.90 107.25 80.50Q109 77.10 109 72.70L109 72.70Q109 68.30 107.25 64.95Q105.50 61.60 102.45 59.65Q99.40 57.70 95.30 57.70L95.30 57.70Q91.20 57.70 88.10 59.65Q85 61.60 83.25 64.95Q81.50 68.30 81.50 72.70L81.50 72.70Q81.50 77.10 83.25 80.50Q85 83.90 88.10 85.80Q91.20 87.70 95.30 87.70Z" fill="#FFFFFF" />
      <path d="M144.80 100L129.80 100L129.80 45.40L144.80 45.40L144.80 100ZM144.80 40.50L129.80 40.50L129.80 25.50L144.80 25.50L144.80 40.50Z" fill="#FF2A2A" />
      <path d="M179.10 101.20L179.10 101.20Q170.90 101.20 164.35 97.45Q157.80 93.70 153.95 87.20Q150.10 80.70 150.10 72.60L150.10 72.60Q150.10 64.50 153.90 58.05Q157.70 51.60 164.30 47.90Q170.90 44.20 179.10 44.20L179.10 44.20Q185.20 44.20 190.40 46.30Q195.60 48.40 199.30 52.15Q203 55.90 204.60 61L204.60 61L191.60 66.60Q190.20 62.50 186.85 60.10Q183.50 57.70 179.10 57.70L179.10 57.70Q175.20 57.70 172.15 59.60Q169.10 61.50 167.35 64.90Q165.60 68.30 165.60 72.70L165.60 72.70Q165.60 77.10 167.35 80.50Q169.10 83.90 172.15 85.80Q175.20 87.70 179.10 87.70L179.10 87.70Q183.60 87.70 186.90 85.30Q190.20 82.90 191.60 78.80L191.60 78.80L204.60 84.50Q203.10 89.30 199.40 93.10Q195.70 96.90 190.50 99.05Q185.30 101.20 179.10 101.20Z" fill="#FFFFFF" />
      <path d="M236.20 101.20L236.20 101.20Q227.50 101.20 221.10 97.35Q214.70 93.50 211.20 87Q207.70 80.50 207.70 72.60L207.70 72.60Q207.70 64.40 211.35 58Q215 51.60 221.20 47.90Q227.40 44.20 235.20 44.20L235.20 44.20Q241.70 44.20 246.70 46.25Q251.70 48.30 255.15 52Q258.60 55.70 260.40 60.55Q262.20 65.40 262.20 71.10L262.20 71.10Q262.20 72.70 262.05 74.25Q261.90 75.80 261.50 76.90L261.50 76.90L223.30 76.90Q223.50 79 224.30 80.80L224.30 80.80Q225.80 84.30 228.90 86.25Q232 88.20 236.40 88.20L236.40 88.20Q240.40 88.20 243.25 86.60Q246.10 85 247.70 82.20L247.70 82.20L259.70 87.90Q258.10 91.90 254.65 94.90Q251.20 97.90 246.50 99.55Q241.80 101.20 236.20 101.20ZM223.60 65.90L223.60 65.90L246.30 65.90Q246.20 64.60 245.80 63.40L245.80 63.40Q244.70 60.10 241.95 58.15Q239.20 56.20 235.20 56.20L235.20 56.20Q231.30 56.20 228.50 58.10Q225.70 60 224.30 63.70L224.30 63.70Q223.90 64.70 223.60 65.90Z" fill="#FFFFFF" />
      <path d="M284.10 100L268.60 100L268.60 25.50L319.60 25.50L319.60 39L284.10 39L284.10 57.90L314.60 57.90L314.60 71.40L284.10 71.40L284.10 100Z" fill="#FF2A2A" />
      <path d="M337.70 100L322.70 100L322.70 45.40L337.70 45.40L337.70 100ZM337.70 40.50L322.70 40.50L322.70 25.50L337.70 25.50L337.70 40.50Z" fill="#FF2A2A" />
      <path d="M357.56 100L350.66 100L350.66 92.20L357.56 92.20L357.56 100Z" fill="#94A3B8" />
      <path d="M382.94 100.72L382.94 100.72Q378.26 100.72 374.39 98.50Q370.52 96.28 368.24 92.44Q365.96 88.60 365.96 83.74L365.96 83.74Q365.96 78.82 368.24 75.01Q370.52 71.20 374.36 69.01Q378.20 66.82 382.94 66.82L382.94 66.82Q387.74 66.82 391.55 69.01Q395.36 71.20 397.61 75.01Q399.86 78.82 399.86 83.74L399.86 83.74Q399.86 88.66 397.58 92.50Q395.30 96.34 391.46 98.53Q387.62 100.72 382.94 100.72ZM382.94 94.42L382.94 94.42Q385.82 94.42 388.04 93.04Q390.26 91.66 391.55 89.23Q392.84 86.80 392.84 83.74L392.84 83.74Q392.84 80.68 391.55 78.28Q390.26 75.88 388.04 74.50Q385.82 73.12 382.94 73.12L382.94 73.12Q380.12 73.12 377.87 74.50Q375.62 75.88 374.33 78.28Q373.04 80.68 373.04 83.74L373.04 83.74Q373.04 86.80 374.33 89.23Q375.62 91.66 377.87 93.04Q380.12 94.42 382.94 94.42Z" fill="#94A3B8" />
      <path d="M412.04 100L405.26 100L405.26 67.54L411.74 67.54L411.74 71.68Q412.82 69.58 414.62 68.50L414.62 68.50Q417.02 67.12 420.38 67.12L420.38 67.12L422.36 67.12L422.36 73.30L419.54 73.30Q416.18 73.30 414.11 75.37Q412.04 77.44 412.04 81.28L412.04 81.28L412.04 100Z" fill="#94A3B8" />
      <path d="M441.44 113.20L441.44 113.20Q437.90 113.20 434.90 112.06Q431.90 110.92 429.74 108.91Q427.58 106.90 426.50 104.20L426.50 104.20L432.74 101.62Q433.58 103.90 435.83 105.40Q438.08 106.90 441.38 106.90L441.38 106.90Q443.96 106.90 446 105.91Q448.04 104.92 449.24 103.03Q450.44 101.14 450.44 98.50L450.44 98.50L450.44 94.42Q449 96.22 447.02 97.30L447.02 97.30Q444.02 98.92 440.30 98.92L440.30 98.92Q435.80 98.92 432.20 96.82Q428.60 94.72 426.53 91.06Q424.46 87.40 424.46 82.84L424.46 82.84Q424.46 78.22 426.53 74.62Q428.60 71.02 432.14 68.92Q435.68 66.82 440.24 66.82L440.24 66.82Q443.96 66.82 446.90 68.38L446.90 68.38Q449.12 69.64 450.74 71.68L450.74 71.68L450.74 67.54L457.16 67.54L457.16 98.50Q457.16 102.70 455.15 106.03Q453.14 109.36 449.60 111.28Q446.06 113.20 441.44 113.20ZM441.08 92.62L441.08 92.62Q443.78 92.62 445.88 91.33Q447.98 90.04 449.21 87.85Q450.44 85.66 450.44 82.90Q450.44 80.14 449.18 77.92Q447.92 75.70 445.82 74.41Q443.72 73.12 441.08 73.12L441.08 73.12Q438.32 73.12 436.16 74.41Q434 75.70 432.77 77.89Q431.54 80.08 431.54 82.90L431.54 82.90Q431.54 85.60 432.77 87.82Q434 90.04 436.16 91.33Q438.32 92.62 441.08 92.62Z" fill="#94A3B8" />
    </g>
  </g>
</svg>"""

TYPOGRAPHY_PRESETS = {
    "classic_ai": {
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@700&family=Newsreader:ital,opsz,wght@0,6..72,600;1,6..72,600&family=Orbitron:wght@800;900&family=Space+Grotesk:wght@700;800&display=swap",
        "viv": {
            "font_family": "'Space Grotesk', sans-serif",
            "font_weight": "700",
            "letter_spacing": "-0.5px",
            "font_style": "normal",
        },
        "claude": {
            "font_family": "'Newsreader', serif",
            "font_weight": "600",
            "letter_spacing": "-0.2px",
            "font_style": "italic",
        },
        "emily": {
            "font_family": "'Orbitron', sans-serif",
            "font_weight": "800",
            "letter_spacing": "1.5px",
            "font_style": "normal",
            "text_transform": "uppercase",
        },
        "punchline_font": "'Space Grotesk', sans-serif",
        "cackle_font": "'Newsreader', serif",
    },
    "witty_comedy": {
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800;12..96,900&family=Fraunces:ital,opsz,wght@0,9..144,700;1,9..144,700;1,9..144,800&family=JetBrains+Mono:wght@700&family=Syncopate:wght@700&display=swap",
        "viv": {
            "font_family": "'Bricolage Grotesque', sans-serif",
            "font_weight": "800",
            "letter_spacing": "-0.8px",
            "font_style": "normal",
        },
        "claude": {
            "font_family": "'Fraunces', serif",
            "font_weight": "700",
            "letter_spacing": "-0.4px",
            "font_style": "italic",
        },
        "emily": {
            "font_family": "'Syncopate', sans-serif",
            "font_weight": "700",
            "letter_spacing": "2.5px",
            "font_style": "normal",
            "text_transform": "uppercase",
        },
        "punchline_font": "'Bricolage Grotesque', sans-serif",
        "cackle_font": "'Fraunces', serif",
    },
    "dev_terminal": {
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@700;800&family=JetBrains+Mono:wght@700;800&family=Outfit:wght@700;800&family=Space+Mono:ital,wght@0,700;1,700&display=swap",
        "viv": {
            "font_family": "'Outfit', sans-serif",
            "font_weight": "800",
            "letter_spacing": "-0.4px",
            "font_style": "normal",
        },
        "claude": {
            "font_family": "'Space Mono', monospace",
            "font_weight": "700",
            "letter_spacing": "-0.5px",
            "font_style": "normal",
        },
        "emily": {
            "font_family": "'Chakra Petch', sans-serif",
            "font_weight": "700",
            "letter_spacing": "1.2px",
            "font_style": "normal",
            "text_transform": "uppercase",
        },
        "punchline_font": "'Outfit', sans-serif",
        "cackle_font": "'Space Mono', monospace",
    },
    "clean_tech": {
        "google_fonts_url": "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@700&family=Plus+Jakarta+Sans:wght@700;800;900&family=Syne:wght@700;800&display=swap",
        "viv": {
            "font_family": "'Plus Jakarta Sans', sans-serif",
            "font_weight": "800",
            "letter_spacing": "-0.5px",
            "font_style": "normal",
        },
        "claude": {
            "font_family": "'Instrument Serif', serif",
            "font_weight": "400",
            "letter_spacing": "0px",
            "font_style": "italic",
        },
        "emily": {
            "font_family": "'Syne', sans-serif",
            "font_weight": "800",
            "letter_spacing": "1.0px",
            "font_style": "normal",
            "text_transform": "uppercase",
        },
        "punchline_font": "'Plus Jakarta Sans', sans-serif",
        "cackle_font": "'Instrument Serif', serif",
    },
}

FORMAT_PRESETS = {
    "9:16": {
        "width": 1080,
        "height": 1920,
        "name": "9:16 Vertical Reel (TikTok, Reels, Shorts)",
        "card_width": 900,
        "card_min_height": 1180,
        "card_padding": "76px 68px",
        "avatar_size": 102,
        "avatar_padding": 17,
        "avatar_radius": 30,
        "speaker_size": 38,
        "counter_size": 28,
        "hook_size": 72,
        "punchline_size": 74,
        "cackle_size": 72,
        "outro_size": 68,
        "body_size": 28,
        "footer_width": 290,
        "footer_height": 58,
        "card_gap": 32,
    },
    "1:1": {
        "width": 1080,
        "height": 1080,
        "name": "1:1 Square Video (X / Twitter, LinkedIn Feed)",
        "card_width": 980,
        "card_min_height": 860,
        "card_padding": "56px 52px",
        "avatar_size": 88,
        "avatar_padding": 15,
        "avatar_radius": 26,
        "speaker_size": 34,
        "counter_size": 24,
        "hook_size": 48,
        "punchline_size": 54,
        "cackle_size": 52,
        "outro_size": 46,
        "body_size": 24,
        "footer_width": 260,
        "footer_height": 52,
        "card_gap": 24,
    },
    "4:5": {
        "width": 1080,
        "height": 1350,
        "name": "4:5 Portrait Video (Instagram / Facebook Feed)",
        "card_width": 960,
        "card_min_height": 1040,
        "card_padding": "64px 58px",
        "avatar_size": 92,
        "avatar_padding": 15,
        "avatar_radius": 27,
        "speaker_size": 35,
        "counter_size": 25,
        "hook_size": 52,
        "punchline_size": 58,
        "cackle_size": 55,
        "outro_size": 50,
        "body_size": 26,
        "footer_width": 275,
        "footer_height": 55,
        "card_gap": 28,
    },
    "16:9": {
        "width": 1920,
        "height": 1080,
        "name": "16:9 Landscape Video (YouTube, Desktop, Keynote)",
        "card_width": 1400,
        "card_min_height": 820,
        "card_padding": "64px 72px",
        "avatar_size": 92,
        "avatar_padding": 15,
        "avatar_radius": 27,
        "speaker_size": 36,
        "counter_size": 26,
        "hook_size": 54,
        "punchline_size": 60,
        "cackle_size": 56,
        "outro_size": 52,
        "body_size": 26,
        "footer_width": 290,
        "footer_height": 58,
        "card_gap": 28,
    },
}


class ReelBuilder:
    """Builds social video reels and slide decks from audio."""

    @classmethod
    def render_html_slide(
        cls,
        slide_data: Dict[str, Any],
        format_type: str = "9:16",
        preset_config: Optional[Dict[str, Any]] = None,
        font_multiplier: float = 1.0,
    ) -> str:
        """Render a single high-resolution HTML/CSS slide card."""
        if preset_config is None:
            preset_config = TYPOGRAPHY_PRESETS["classic_ai"]

        fmt = FORMAT_PRESETS.get(format_type, FORMAT_PRESETS["9:16"])
        width, height = fmt["width"], fmt["height"]
        speaker = slide_data.get("speaker", "Radio Host")

        avatar_svg = slide_data.get("avatar_svg")
        avatar_border = slide_data.get("avatar_border")
        avatar_bg = slide_data.get("avatar_bg")

        if not avatar_svg:
            if speaker in ("Viv", "Google Antigravity"):
                avatar_svg = ANTIGRAVITY_LOGO_SVG
                avatar_border = "#FF2A2A" if slide_data.get("is_punchline") else "#3186FF"
                avatar_bg = (
                    "rgba(255,42,42,0.15)"
                    if slide_data.get("is_punchline")
                    else "rgba(49,134,255,0.15)"
                )
            elif speaker in ("Claude", "Steffan", "Anthropic Claude"):
                avatar_svg = CLAUDE_LOGO_SVG
                avatar_border = "#D97757"
                avatar_bg = "rgba(217,119,87,0.15)"
            elif speaker in ("Jake", "Creator", "Developer"):
                avatar_svg = JAKE_LOGO_SVG
                avatar_border = "#8B5CF6"
                avatar_bg = "rgba(139,92,246,0.15)"
            elif speaker in ("Radio Host", "Announcer", "Host"):
                avatar_svg = RADIO_HOST_LOGO_SVG
                avatar_border = "#EF4444"
                avatar_bg = "rgba(239,68,68,0.15)"
            else:  # VoiceFi Emily / Narrator
                avatar_svg = VOICEFI_LOGO_SVG
                avatar_border = "#10B981"
                avatar_bg = "rgba(16,185,129,0.15)"

        if speaker in ("Viv", "Google Antigravity"):
            cfg = preset_config.get("viv", preset_config.get("emily", {}))
        elif speaker in ("Claude", "Steffan", "Anthropic Claude"):
            cfg = preset_config.get("claude", preset_config.get("emily", {}))
        elif speaker in ("Jake", "Creator", "Developer"):
            cfg = {
                "font_family": "'Plus Jakarta Sans', sans-serif",
                "font_weight": "800",
                "letter_spacing": "-0.5px",
                "font_style": "normal",
                "text_transform": "none",
            }
        elif speaker in ("Radio Host", "Announcer", "Host"):
            cfg = {
                "font_family": "'Plus Jakarta Sans', sans-serif",
                "font_weight": "900",
                "letter_spacing": "-0.6px",
                "font_style": "normal",
                "text_transform": "none",
            }
        else:
            cfg = preset_config.get(
                "emily", {"font_family": "'Plus Jakarta Sans', sans-serif", "font_weight": "800"}
            )

        font_fam = cfg.get("font_family", "'Plus Jakarta Sans', sans-serif")
        font_wt = cfg.get("font_weight", "800")
        letter_sp = cfg.get("letter_spacing", "-0.5px")
        font_st = cfg.get("font_style", "normal")
        text_tf = cfg.get("text_transform", "none")

        base_hook_size = int(fmt["hook_size"] * font_multiplier)
        hook_color = "#F8FAFC"

        if slide_data.get("is_punchline"):
            font_fam = preset_config.get("punchline_font", font_fam)
            hook_color = "#FF2A2A"
            base_hook_size = int(fmt["punchline_size"] * font_multiplier)
        elif slide_data.get("is_cackle"):
            font_fam = preset_config.get("cackle_font", font_fam)
            hook_color = "#D97757"
            base_hook_size = int(fmt["cackle_size"] * font_multiplier)
        elif slide_data.get("is_outro"):
            hook_color = "#10B981"
            base_hook_size = int(fmt["outro_size"] * font_multiplier)

        body_html = (
            f'<div class="body-text">{slide_data["body"]}</div>' if slide_data.get("body") else ""
        )
        hide_footer = slide_data.get("hide_footer", False)

        footer_css = (
            ""
            if hide_footer
            else f"""
  .card-footer {{
    border-top: 2px solid #232838;
    padding-top: 32px;
    display: flex;
    align-items: center;
    justify-content: {"center" if slide_data.get("is_outro") else "flex-start"};
  }}
  .footer-lockup {{
    width: {fmt["footer_width"]}px;
    height: {fmt["footer_height"]}px;
    display: flex;
    align-items: center;
  }}"""
        )

        footer_html = (
            ""
            if hide_footer
            else f"""
    <div class="card-footer">
      <div class="footer-lockup">{VOICEFI_MASTER_LOCKUP_SVG}</div>
    </div>"""
        )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{preset_config.get("google_fonts_url", "")}" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {width}px;
    height: {height}px;
    background: radial-gradient(circle at 50% 35%, #1A1F2C 0%, #0A0D14 100%);
    font-family: 'Plus Jakarta Sans', sans-serif;
    color: #F8FAFC;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 40px;
  }}
  .slide-card {{
    width: {fmt["card_width"]}px;
    background: #11141D;
    border: 2.5px solid #232838;
    border-radius: 44px;
    padding: {fmt["card_padding"]};
    box-shadow: 0 35px 90px rgba(0, 0, 0, 0.7), 0 0 50px rgba(255, 42, 42, 0.12);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: {fmt["card_min_height"]}px;
  }}
  .card-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .speaker-group {{
    display: flex;
    align-items: center;
    gap: 22px;
  }}
  .avatar {{
    width: {fmt["avatar_size"]}px;
    height: {fmt["avatar_size"]}px;
    border-radius: {fmt["avatar_radius"]}px;
    background: {avatar_bg};
    border: 2.5px solid {avatar_border};
    padding: {fmt["avatar_padding"]}px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  .speaker-meta {{
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .speaker-name {{
    font-size: {fmt["speaker_size"]}px;
    font-weight: 800;
    color: #F8FAFC;
    letter-spacing: -0.4px;
    font-family: {font_fam};
  }}
  .counter {{
    font-size: {fmt["counter_size"]}px;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    color: #94A3B8;
  }}
  .card-body {{
    margin: auto 0;
    display: flex;
    flex-direction: column;
    gap: {fmt["card_gap"]}px;
    padding: 32px 0;
    {"text-align: center; align-items: center; justify-content: center;" if slide_data.get("is_outro") else ""}
  }}
  .hook-text {{
    font-family: {font_fam};
    font-weight: {font_wt};
    font-style: {font_st};
    letter-spacing: {letter_sp};
    text-transform: {text_tf};
    font-size: {base_hook_size}px;
    line-height: 1.32;
    color: {hook_color};
    {"text-align: center; width: 100%;" if slide_data.get("is_outro") else ""}
  }}
  .body-text {{
    font-size: {fmt["body_size"]}px;
    font-weight: 500;
    line-height: 1.55;
    color: #94A3B8;
    {"text-align: center; max-width: 820px; margin: 16px auto 0 auto;" if slide_data.get("is_outro") else ""}
  }}
  {footer_css}
</style>
</head>
<body>
  <div class="slide-card">
    <div class="card-header">
      <div class="speaker-group">
        <div class="avatar">{avatar_svg}</div>
        <div class="speaker-meta">
          <span class="speaker-name">{slide_data.get("speaker", "Radio Host")}</span>
        </div>
      </div>
      <div class="counter">{slide_data.get("counter", "1/1")}</div>
    </div>

    <div class="card-body">
      <div class="hook-text">{slide_data.get("hook", "")}</div>
      {body_html}
    </div>

    {footer_html}
  </div>
</body>
</html>"""

    @classmethod
    def auto_generate_slides_from_text(
        cls, transcript: str, total_duration: float, speaker: str = "Radio Host"
    ) -> List[Dict[str, Any]]:
        """Split a raw spoken transcript into pacing-aligned slide cards."""
        sentences = [s.strip() for s in transcript.replace("\n", " ").split(".") if s.strip()]
        if not sentences:
            sentences = [transcript.strip() or "VoiceFi Studio Master Audio"]

        # Group sentences into slides of 10-18 words
        slides_text = []
        curr = []
        for s in sentences:
            curr.append(s)
            word_count = sum(len(x.split()) for x in curr)
            if word_count >= 12:
                slides_text.append(". ".join(curr) + ".")
                curr = []
        if curr:
            slides_text.append(". ".join(curr) + ("." if not curr[-1].endswith(".") else ""))

        slide_count = max(1, len(slides_text))
        dur_per_slide = total_duration / slide_count

        slides = []
        for idx, txt in enumerate(slides_text):
            is_last = idx == slide_count - 1
            slides.append(
                {
                    "slide_idx": idx + 1,
                    "speaker": speaker,
                    "counter": f"{idx + 1}/{slide_count}",
                    "hook": f"“{txt.strip()}”",
                    "body": "",
                    "is_outro": is_last and slide_count > 2,
                    "dur": round(dur_per_slide, 2),
                }
            )
        return slides

    @classmethod
    def compile_reel(
        cls,
        output_mp4: Union[str, Path],
        audio_file: Union[str, Path],
        slides: Optional[List[Dict[str, Any]]] = None,
        transcript: Optional[str] = None,
        format_type: str = "9:16",
        preset_name: str = "classic_ai",
        font_multiplier: float = 1.0,
        speaker_name: str = "Radio Host",
    ) -> Path:
        """Compile MP4 video reel by rendering slide cards and muxing with audio."""
        out_path = Path(output_mp4).resolve()
        audio_path = Path(audio_file).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Get audio duration
        from voicefi.audio.effects import VoiceFXEngine

        info = VoiceFXEngine.get_audio_info(audio_path)
        total_duration = info["duration"]

        if not slides:
            slides = cls.auto_generate_slides_from_text(
                transcript=transcript or "VoiceFi Studio Master Audio",
                total_duration=total_duration,
                speaker=speaker_name,
            )

        fmt = FORMAT_PRESETS.get(format_type, FORMAT_PRESETS["9:16"])
        width, height = fmt["width"], fmt["height"]
        preset_cfg = dict(TYPOGRAPHY_PRESETS.get(preset_name, TYPOGRAPHY_PRESETS["classic_ai"]))

        tmp_dir = Path(tempfile.mkdtemp(prefix="vifi_reel_build_"))

        try:
            # 1. Render HTML slides to PNG images via Headless Chrome
            png_files = []
            chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if not os.path.exists(chrome_path):
                chrome_path = "google-chrome"

            for idx, s in enumerate(slides):
                html_file = tmp_dir / f"slide_{idx}.html"
                png_file = tmp_dir / f"slide_{idx}.png"
                html_content = cls.render_html_slide(
                    slide_data=s,
                    format_type=format_type,
                    preset_config=preset_cfg,
                    font_multiplier=font_multiplier,
                )
                html_file.write_text(html_content, encoding="utf-8")

                cmd = [
                    chrome_path,
                    "--headless",
                    "--disable-gpu",
                    f"--window-size={width},{height}",
                    f"--screenshot={str(png_file)}",
                    f"file://{str(html_file)}",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0 or not png_file.is_file():
                    raise RuntimeError(f"Chrome screenshot failed for slide {idx}: {res.stderr}")
                png_files.append(png_file)

            # 2. Build FFmpeg concat plan
            concat_file = tmp_dir / "concat_plan.txt"
            with open(concat_file, "w") as f:
                for idx, s in enumerate(slides):
                    f.write(f"file '{png_files[idx]}'\n")
                    f.write(f"duration {s.get('dur', 4.0):.3f}\n")
                f.write(f"file '{png_files[-1]}'\n")

            # 3. Compile MP4 with FFmpeg
            cmd_ffmpeg = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-i",
                str(audio_path),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "medium",
                "-crf",
                "19",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out_path),
            ]
            res_ff = subprocess.run(cmd_ffmpeg, capture_output=True, text=True)
            if res_ff.returncode != 0 or not out_path.is_file():
                raise RuntimeError(f"FFmpeg video compilation failed: {res_ff.stderr}")

            return out_path

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
