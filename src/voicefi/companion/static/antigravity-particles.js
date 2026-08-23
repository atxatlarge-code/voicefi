/**
 * Antigravity Particles Engine
 * Zero-gravity floating particles, cursor anti-gravity deflection,
 * constellation neural links, and acoustic state reactivity.
 * 
 * Inspired by https://antigravity.google/
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AntigravityField = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const THEMES = {
    google: {
      name: 'Google Antigravity Glow',
      background: '#05070d',
      colors: [
        { r: 66, g: 133, b: 244 },   // Google Blue (#4285f4)
        { r: 234, g: 67, b: 53 },    // Google Red (#ea4335)
        { r: 251, g: 188, b: 5 },    // Google Yellow (#fbbc05)
        { r: 52, g: 168, b: 83 },    // Google Green (#34a853)
        { r: 168, g: 199, b: 250 },  // Light Blue / Cyan
      ],
      lineColor: 'rgba(100, 149, 237, ',
      particleAlpha: 0.85,
      glowAlpha: 0.35,
      ambientGlow: 'rgba(66, 133, 244, 0.04)',
    },
    monochrome: {
      name: 'Cyber Monochrome',
      background: '#000000',
      colors: [
        { r: 255, g: 255, b: 255 },
        { r: 212, g: 212, b: 216 },
        { r: 161, g: 161, b: 170 },
        { r: 113, g: 113, b: 122 },
      ],
      lineColor: 'rgba(255, 255, 255, ',
      particleAlpha: 0.75,
      glowAlpha: 0.25,
      ambientGlow: 'rgba(255, 255, 255, 0.02)',
    },
    broadcast: {
      name: 'Studio Broadcast Red',
      background: '#090000',
      colors: [
        { r: 255, g: 51, b: 51 },    // Broadcast Red (#ff3333)
        { r: 255, g: 102, b: 102 },  // Soft Coral
        { r: 255, g: 170, b: 0 },    // Studio Amber (#ffaa00)
        { r: 220, g: 38, b: 38 },    // Dark Red
      ],
      lineColor: 'rgba(255, 51, 51, ',
      particleAlpha: 0.85,
      glowAlpha: 0.35,
      ambientGlow: 'rgba(255, 51, 51, 0.05)',
    },
    emerald: {
      name: 'Neural Matrix',
      background: '#020904',
      colors: [
        { r: 16, g: 185, b: 129 },   // Emerald 500
        { r: 52, g: 211, b: 153 },   // Emerald 400
        { r: 110, g: 231, b: 183 },  // Emerald 300
        { r: 5, g: 150, b: 105 },    // Emerald 600
      ],
      lineColor: 'rgba(52, 211, 153, ',
      particleAlpha: 0.8,
      glowAlpha: 0.3,
      ambientGlow: 'rgba(16, 185, 129, 0.04)',
    }
  };

  class Particle {
    constructor(field, isDust = false) {
      this.field = field;
      this.isDust = isDust;
      this.reset(true);
    }

    reset(initial = false) {
      const w = this.field.width;
      const h = this.field.height;

      this.x = Math.random() * w;
      this.y = initial ? Math.random() * h : h + Math.random() * 20;
      
      // Floating speed and size
      if (this.isDust) {
        this.baseRadius = 0.5 + Math.random() * 1.2;
        this.vx = (Math.random() - 0.5) * 0.15;
        this.vy = -(0.08 + Math.random() * 0.2); // Gentle upward float
        this.mass = 0.5;
        this.alpha = 0.15 + Math.random() * 0.35;
      } else {
        this.baseRadius = 1.2 + Math.random() * 2.4;
        this.vx = (Math.random() - 0.5) * 0.4;
        this.vy = -(0.15 + Math.random() * 0.5); // Zero-gravity upward lift
        this.mass = 1.0 + Math.random() * 1.5;
        this.alpha = 0.4 + Math.random() * 0.55;
      }

      this.radius = this.baseRadius;
      this.color = this.field.getRandomColor();
      this.phase = Math.random() * Math.PI * 2;
      this.pulseSpeed = 0.02 + Math.random() * 0.03;
      this.originalVy = this.vy;

      // Thinking state neural orbital mechanics parameters
      const minDim = Math.min(w || 800, h || 600);
      this.baseOrbitRadius = 70 + Math.random() * (minDim * 0.38);
      this.orbitDirection = Math.random() < 0.08 ? -1 : 1; // 92% unified direction for mesmerizing coherent galaxy swirl
      this.orbitSpeed = 0.75 + Math.random() * 0.50; // Active, responsive cosmic orbit
      this.neuralPhase = Math.random() * Math.PI * 2;
      this.synapticFlash = 0;
    }

    update(dt, pointer, state, audioLevel) {
      const timeScale = Math.min(dt / 16.6, 2.0);
      this.phase += this.pulseSpeed * timeScale;
      this.neuralPhase += 0.018 * timeScale;

      // Decay idea lightning synaptic flare
      if (this.synapticFlash > 0) {
        this.synapticFlash = Math.max(0, this.synapticFlash - (dt / 1000) * 4.8);
      }

      // 1. State-Driven Physics
      if (state === 'speaking') {
        // Energetic anti-gravity liftoff buoyancy (approx 2.5x idle speed)
        const buoyancy = this.field.options.buoyancy * 2.4;
        this.vy += buoyancy * timeScale;

        // Acoustic upward wave surge
        const liftoffForce = (0.05 + (this.isDust ? 0.02 : 0.08) + (audioLevel * 0.22)) * timeScale;
        this.vy -= liftoffForce;

        // Acoustic harmonic lateral oscillation (voice resonance)
        const acousticWave = Math.sin(this.phase * 3 + (this.field.time || 0) * 10) * (0.4 + audioLevel * 1.4) * (this.isDust ? 0.3 : 0.8);
        this.vx += acousticWave * timeScale;

        this.x += this.vx * timeScale;
        this.y += this.vy * timeScale;

      } else if (state === 'thinking') {
        // Synchronized Neural Constellation Swirl (Graceful, hypnotic orbital flow):
        // Buoyancy is zeroed so nodes glide in smooth 360-degree rotating orbital shells
        const center = this.field.getPullCenter();
        const cx = center.x;
        const cy = center.y;
        const dx = cx - this.x;
        const dy = cy - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const normX = dx / dist;
        const normY = dy / dist;

        // Gentle, slow meditative breathing of orbital shells
        const breathing = 1.0 + Math.sin((this.field.time || 0) * 0.8 + this.neuralPhase) * 0.05;
        const targetR = this.baseOrbitRadius * breathing;

        // Gentle spring smoothly keeping particles in their orbit ring
        const rDiff = dist - targetR;
        const spring = (this.isDust ? 0.015 : 0.03) * timeScale;
        this.vx += normX * rDiff * spring;
        this.vy += normY * rDiff * spring;

        // Controlled, graceful orbital cruise velocity (~0.6 - 0.95 px/frame)
        const swirlSpeed = this.field.options.thinkingSwirlSpeed !== undefined ? this.field.options.thinkingSwirlSpeed : 1.0;
        const targetSpeed = (0.50 + (30 / (dist + 50))) * (this.orbitDirection || 1) * (this.isDust ? 0.6 : 0.85) * swirlSpeed;
        const targetVx = -normY * targetSpeed;
        const targetVy = normX * targetSpeed;

        // Smoothly interpolate current velocity toward target orbital velocity (controlled, steady cruise)
        const lerpFactor = (this.isDust ? 0.05 : 0.08) * timeScale;
        this.vx += (targetVx - this.vx) * lerpFactor;
        this.vy += (targetVy - this.vy) * lerpFactor;

        this.x += this.vx * timeScale;
        this.y += this.vy * timeScale;

      } else if (state === 'listening') {
        // Acoustic Black Hole Singularity Gravitational Pull
        let buoyancy = this.field.options.buoyancy * 0.08;
        this.vy += buoyancy * timeScale;

        const center = this.field.getPullCenter();
        const cx = center.x;
        const cy = center.y;
        const dx = cx - this.x;
        const dy = cy - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;

        const pullStrength = this.field.options.listeningPullStrength !== undefined ? this.field.options.listeningPullStrength : 2.0;
        const swirlStrength = this.field.options.listeningSwirl !== undefined ? this.field.options.listeningSwirl : 1.2;
        const audioBoost = 1.0 + (audioLevel * 1.5);

        if (dist > 0.5) {
          const normX = dx / dist;
          const normY = dy / dist;

          // Non-linear gravitational acceleration curve
          const gravity = (0.16 + (240 / (dist + 38))) * pullStrength * 0.28 * audioBoost * timeScale;
          this.vx += (normX * gravity) / Math.sqrt(this.mass);
          this.vy += (normY * gravity) / Math.sqrt(this.mass);

          // Tangential accretion vortex swirl
          const tangentialSpeed = (0.10 + (160 / (dist + 45))) * swirlStrength * 0.24 * audioBoost * timeScale;
          this.vx += (-normY * tangentialSpeed) / Math.sqrt(this.mass);
          this.vy += (normX * tangentialSpeed) / Math.sqrt(this.mass);

          // Event horizon core slingshot buffer
          if (dist < 26) {
            const corePush = (1 - dist / 26) * 0.9 * pullStrength * timeScale;
            this.vx -= normX * corePush;
            this.vy -= normY * corePush;
          }
        }

        const drift = 0.03 * Math.sin(this.phase) * (this.isDust ? 0.05 : 0.12);
        this.x += (this.vx + drift) * timeScale;
        this.y += this.vy * timeScale;

      } else {
        // Idle Zero-G Drift
        let buoyancy = this.field.options.buoyancy;
        this.vy += buoyancy * timeScale;

        const drift = Math.sin(this.phase) * (this.isDust ? 0.05 : 0.12);
        this.x += (this.vx + drift) * timeScale;
        this.y += this.vy * timeScale;
      }

      // 2. Audio-reactive / Neural radius expansion
      if (state === 'speaking' || audioLevel > 0.02) {
        this.radius = this.baseRadius + audioLevel * (this.isDust ? 2.2 : 4.5);
      } else if (state === 'thinking') {
        const neuralP = Math.sin((this.field.time || 0) * 1.5 + this.neuralPhase);
        this.radius = this.baseRadius + (neuralP > 0.5 ? (neuralP - 0.5) * 1.2 : 0);
      } else {
        this.radius = this.baseRadius + Math.sin(this.phase) * 0.3;
      }

      // 3. Pointer Anti-Gravity Force Field (Repulsion / Elastic Deflection)
      if (pointer.active) {
        const dx = this.x - pointer.x;
        const dy = this.y - pointer.y;
        const distSq = dx * dx + dy * dy;
        const radius = this.field.options.repulsionRadius;
        const radiusSq = radius * radius;

        if (distSq < radiusSq && distSq > 0.1) {
          const dist = Math.sqrt(distSq);
          const normX = dx / dist;
          const normY = dy / dist;
          
          // Smooth cubic falloff for organic zero-gravity push
          const force = Math.pow(1 - dist / radius, 2) * this.field.options.repulsionStrength;
          
          this.vx += (normX * force * 4) / this.mass;
          this.vy += (normY * force * 4) / this.mass;
        }
      }

      // 4. State-specific Inertial Damping
      if (state === 'listening') {
        this.vx *= 0.965;
        this.vy *= 0.965;
      } else if (state === 'thinking') {
        this.vx *= 0.965;
        this.vy *= 0.965;
      } else if (state === 'speaking') {
        this.vx *= 0.94;
        this.vy *= 0.96;
      } else {
        this.vx *= 0.94;
        this.vy *= 0.96;
      }

      // Ensure minimum upward float doesn't freeze in idle
      if (state === 'idle' && Math.abs(this.vy) < 0.05) {
        this.vy = this.originalVy;
      }

      // Wrap around bounds seamlessly
      const margin = 50;
      if (this.y < -margin) {
        this.y = this.field.height + margin;
        this.x = Math.random() * this.field.width;
        if (state === 'speaking') {
          this.vy = -(0.8 + Math.random() * 1.5 + audioLevel * 1.0);
        }
      } else if (this.y > this.field.height + margin) {
        this.y = -margin;
      }

      if (this.x < -margin) {
        this.x = this.field.width + margin;
      } else if (this.x > this.field.width + margin) {
        this.x = -margin;
      }
    }

    draw(ctx) {
      const c = this.color;
      const audio = this.field.effectiveAudio !== undefined ? this.field.effectiveAudio : (this.field.audioLevel || 0);
      const glowIntensity = this.field.options.glowIntensity || 1.2;
      const state = this.field.state;

      // Calculate audio/state-boosted alpha
      let alpha = this.alpha * (this.isDust ? 0.4 : 1.0);
      if (state === 'speaking' || audio > 0.02) {
        alpha = Math.min(1.0, alpha + audio * 0.55 * glowIntensity);
      } else if (state === 'thinking') {
        const neuralP = Math.sin((this.field.time || 0) * 1.5 + this.neuralPhase);
        if (neuralP > 0.4) {
          alpha = Math.min(1.0, alpha + (neuralP - 0.4) * 0.5);
        }
      }

      // Core particle
      ctx.beginPath();
      ctx.arc(this.x, this.y, Math.max(0.5, this.radius), 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha})`;
      ctx.fill();

      // Specular bright center highlight when voice is active or neural firing
      if (!this.isDust) {
        let specularAlpha = 0;
        if ((state === 'speaking' || audio > 0.05) && audio > 0.12) {
          specularAlpha = Math.min(0.95, audio * 0.9);
        } else if (state === 'thinking') {
          const neuralP = Math.sin((this.field.time || 0) * 1.5 + this.neuralPhase);
          if (neuralP > 0.75) {
            specularAlpha = (neuralP - 0.75) * 2.2;
          }
        }

        if (specularAlpha > 0.05) {
          ctx.beginPath();
          ctx.arc(this.x, this.y, Math.max(0.4, this.radius * 0.45), 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 255, ${specularAlpha})`;
          ctx.fill();
        }
      }

      // Luminescent glow halo for primary nodes (blooms with volume and neural state)
      if (!this.isDust && this.field.options.glowEnabled && this.radius > 1.1) {
        let glowMultiplier = 3.5;
        let peakAlpha = alpha * 0.45;

        if (state === 'speaking' || audio > 0.02) {
          glowMultiplier = 3.5 + (audio * 7.5 * glowIntensity);
          peakAlpha = Math.min(0.95, (alpha * 0.45) + (audio * 0.85 * glowIntensity));
        } else if (state === 'thinking') {
          const neuralP = Math.sin((this.field.time || 0) * 1.5 + this.neuralPhase);
          const neuralGlow = Math.max(0, neuralP) * 0.35;
          glowMultiplier = 3.8 + neuralGlow * 2.0;
          peakAlpha = Math.min(0.85, (alpha * 0.5) + neuralGlow);
        }

        const glowRadius = this.radius * glowMultiplier;
        const gradient = ctx.createRadialGradient(this.x, this.y, this.radius * 0.2, this.x, this.y, glowRadius);
        gradient.addColorStop(0, `rgba(${c.r}, ${c.g}, ${c.b}, ${peakAlpha})`);
        gradient.addColorStop(0.35, `rgba(${c.r}, ${c.g}, ${c.b}, ${peakAlpha * 0.4})`);
        gradient.addColorStop(1, `rgba(${c.r}, ${c.g}, ${c.b}, 0)`);
        
        ctx.beginPath();
        ctx.arc(this.x, this.y, glowRadius, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();
      }

      // Synaptic Idea Flash Flare (electric flare when idea lightning strikes this node)
      if (this.synapticFlash > 0.02) {
        const flash = this.synapticFlash;
        const flashRadius = this.radius * (4.0 + flash * 5.0);
        const flashGrad = ctx.createRadialGradient(this.x, this.y, 0, this.x, this.y, flashRadius);
        flashGrad.addColorStop(0, `rgba(255, 255, 255, ${Math.min(1.0, flash * 0.98)})`);
        flashGrad.addColorStop(0.25, `rgba(${c.r}, ${c.g}, ${c.b}, ${Math.min(1.0, flash * 0.8)})`);
        flashGrad.addColorStop(0.7, `rgba(${c.r}, ${c.g}, ${c.b}, ${flash * 0.3})`);
        flashGrad.addColorStop(1, `rgba(${c.r}, ${c.g}, ${c.b}, 0)`);

        ctx.beginPath();
        ctx.arc(this.x, this.y, flashRadius, 0, Math.PI * 2);
        ctx.fillStyle = flashGrad;
        ctx.fill();

        // White-hot core specular spark
        ctx.beginPath();
        ctx.arc(this.x, this.y, Math.max(1.0, this.radius * (0.9 + flash * 0.6)), 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${Math.min(1.0, flash * 0.95)})`;
        ctx.fill();
      }
    }
  }

  /**
   * LightningArc: Jagged electric arc discharging between neural particle nodes (idea flashes)
   */
  class LightningArc {
    constructor(x1, y1, x2, y2, color, options = {}) {
      this.x1 = x1;
      this.y1 = y1;
      this.x2 = x2;
      this.y2 = y2;
      this.color = color || { r: 168, g: 215, b: 255 }; // Electric bright cyan/blue
      this.maxLife = options.maxLife || (0.14 + Math.random() * 0.10); // 140ms - 240ms duration
      this.delay = options.delay || 0; // Sequential cascade delay (for multi-jump chaining)
      this.life = 0;
      this.branches = [];
      this.points = this._generatePoints(x1, y1, x2, y2, 6, 18);

      // 45% chance to create a side branch fork
      if (Math.random() < 0.5 && this.points.length > 3) {
        const branchIdx = Math.floor(Math.random() * (this.points.length - 2)) + 1;
        const bp = this.points[branchIdx];
        const angle = Math.atan2(y2 - y1, x2 - x1) + (Math.random() - 0.5) * 1.3;
        const branchLen = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) * 0.38;
        const bx2 = bp.x + Math.cos(angle) * branchLen;
        const by2 = bp.y + Math.sin(angle) * branchLen;
        this.branches.push(this._generatePoints(bp.x, bp.y, bx2, by2, 4, 10));
      }
    }

    _generatePoints(x1, y1, x2, y2, segments = 6, maxJitter = 18) {
      const pts = [{ x: x1, y: y1 }];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const nx = -dy / dist; // Perpendicular normal
      const ny = dx / dist;

      for (let i = 1; i < segments; i++) {
        const t = i / segments;
        // Midpoint sine envelope: maximum jitter in middle, clamped at ends
        const envelope = Math.sin(t * Math.PI);
        const jitter = (Math.random() - 0.5) * maxJitter * 2 * envelope;
        pts.push({
          x: x1 + dx * t + nx * jitter,
          y: y1 + dy * t + ny * jitter
        });
      }
      pts.push({ x: x2, y: y2 });
      return pts;
    }

    update(dt) {
      if (this.delay > 0) {
        this.delay -= dt / 1000;
        return true;
      }
      this.life += dt / 1000;
      return this.life < this.maxLife;
    }

    draw(ctx) {
      if (this.delay > 0) return;
      const progress = this.life / this.maxLife;
      // Realistic electrical flickering and decay
      const flicker = 0.72 + Math.random() * 0.28;
      const alpha = Math.max(0, (1 - Math.pow(progress, 1.4)) * flicker);
      if (alpha <= 0.01) return;

      const c = this.color;

      const renderBolt = (pts, widthScale = 1.0) => {
        if (pts.length < 2) return;
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) {
          ctx.lineTo(pts[i].x, pts[i].y);
        }

        // 1. Broad outer plasma bloom
        ctx.strokeStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha * 0.45 * widthScale})`;
        ctx.lineWidth = 3.8 * widthScale;
        ctx.stroke();

        // 2. Focused electric beam
        ctx.strokeStyle = `rgba(${Math.min(255, c.r + 60)}, ${Math.min(255, c.g + 60)}, ${Math.min(255, c.b + 60)}, ${alpha * 0.85 * widthScale})`;
        ctx.lineWidth = 1.8 * widthScale;
        ctx.stroke();

        // 3. Hot white core arc
        ctx.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.95 * widthScale})`;
        ctx.lineWidth = 0.75 * widthScale;
        ctx.stroke();
      };

      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'bevel';

      // Draw main lightning arc
      renderBolt(this.points, 1.0);

      // Draw secondary branching forks
      for (let b = 0; b < this.branches.length; b++) {
        renderBolt(this.branches[b], 0.65);
      }

      ctx.restore();
    }
  }

  class AntigravityField {
    constructor(canvas, options = {}) {
      if (typeof canvas === 'string') {
        this.canvas = document.querySelector(canvas);
      } else {
        this.canvas = canvas;
      }

      if (!this.canvas) {
        throw new Error('AntigravityField: Target canvas element not found.');
      }

      this.ctx = this.canvas.getContext('2d', { alpha: true });
      
      // Configuration defaults
      this.options = Object.assign({
        theme: 'google',               // 'google' | 'monochrome' | 'broadcast' | 'emerald'
        particleCount: 75,
        dustCount: 90,
        connectionDistance: 130,
        repulsionRadius: 150,
        repulsionStrength: 1.5,
        buoyancy: -0.012,              // Gentle upward lift (zero-g float)
        glowEnabled: true,
        connectConstellations: true,
        enablePointerGravity: true,
        autoResize: true,
        reducedMotion: false,
        listeningPullStrength: 2.0,    // Gravitational pull intensity in listening state (black hole)
        listeningSwirl: 1.2,           // Orbital vortex / swirl factor around singularity
        thinkingSwirlSpeed: 1.0,       // Active orbital neural constellation swirl speed
        enableIdeaLightning: true,     // Flashes of synaptic lightning arcs between particles during thinking
        ideaLightningInterval: 0.35,   // Frequency interval (in seconds) between idea lightning strikes
        pullCenterSelector: null,      // Optional CSS selector to dynamically align center with a DOM element
        pullCenterX: undefined,        // Optional custom pull center X (defaults to width / 2)
        pullCenterY: undefined,        // Optional custom pull center Y (defaults to height / 2)
      }, options);

      // State tracking
      this.theme = THEMES[this.options.theme] || THEMES.google;
      this.state = 'idle';             // 'idle' | 'listening' | 'thinking' | 'speaking'
      this.audioLevel = 0.0;
      this.effectiveAudio = 0.0;
      this.time = 0;
      this.stateTimer = 0;
      this.particles = [];
      this.dust = [];
      this.running = false;
      this.lastTime = 0;
      this.pointer = { x: -1000, y: -1000, active: false };
      this.shockwaves = [];
      this.lightningArcs = [];
      this.ideaLightningTimer = 0;
      this.nextLightningStrike = 0.35;

      // Check system reduced motion preference
      if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        this.options.reducedMotion = true;
      }

      this._init();
    }

    _init() {
      this._bindEvents();
      this.resize();
      this._spawnParticles();
      this.start();
    }

    _bindEvents() {
      this._onResize = () => this.resize();
      this._onPointerMove = (e) => {
        if (!this.options.enablePointerGravity) return;
        const rect = this.canvas.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        this.pointer.x = clientX - rect.left;
        this.pointer.y = clientY - rect.top;
        this.pointer.active = true;
      };

      this._onPointerLeave = () => {
        this.pointer.active = false;
      };

      this._onVisibilityChange = () => {
        if (document.hidden) {
          this.pause();
        } else {
          this.start();
        }
      };

      if (this.options.autoResize) {
        window.addEventListener('resize', this._onResize, { passive: true });
        if (typeof ResizeObserver !== 'undefined' && this.canvas.parentElement && this.canvas.parentElement !== document.body) {
          this._resizeObserver = new ResizeObserver(() => this.resize());
          this._resizeObserver.observe(this.canvas.parentElement);
        }
      }

      // Pointer event listeners on window to track hover across transparent UI
      window.addEventListener('mousemove', this._onPointerMove, { passive: true });
      window.addEventListener('touchmove', this._onPointerMove, { passive: true });
      window.addEventListener('touchstart', this._onPointerMove, { passive: true });
      window.addEventListener('touchend', this._onPointerLeave, { passive: true });
      document.addEventListener('mouseleave', this._onPointerLeave, { passive: true });
      document.addEventListener('visibilitychange', this._onVisibilityChange);

      // Support modern content-visibility auto state change
      if ('contentVisibility' in document.documentElement.style) {
        this.canvas.addEventListener('contentvisibilityautostatechange', (e) => {
          if (e.skipped) {
            this.pause();
          } else {
            this.start();
          }
        });
      }
    }

    resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      
      let w = window.innerWidth;
      let h = window.innerHeight;

      if (this.canvas) {
        const computed = window.getComputedStyle(this.canvas);
        if (computed.position !== 'fixed' && this.canvas.parentElement && this.canvas.parentElement !== document.body) {
          const rect = this.canvas.parentElement.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            w = rect.width;
            h = rect.height;
          }
        }
      }

      this.width = w;
      this.height = h;

      this.canvas.width = Math.floor(this.width * dpr);
      this.canvas.height = Math.floor(this.height * dpr);
      this.canvas.style.width = `${this.width}px`;
      this.canvas.style.height = `${this.height}px`;

      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    _spawnParticles() {
      this.particles = [];
      this.dust = [];

      const count = this.options.reducedMotion ? Math.floor(this.options.particleCount / 2) : this.options.particleCount;
      const dustCount = this.options.reducedMotion ? Math.floor(this.options.dustCount / 2) : this.options.dustCount;

      for (let i = 0; i < count; i++) {
        this.particles.push(new Particle(this, false));
      }

      for (let i = 0; i < dustCount; i++) {
        this.dust.push(new Particle(this, true));
      }
    }

    getRandomColor() {
      const colors = this.theme.colors;
      return colors[Math.floor(Math.random() * colors.length)];
    }

    setTheme(themeName) {
      if (THEMES[themeName]) {
        this.theme = THEMES[themeName];
        this.options.theme = themeName;
        // Re-assign colors to existing particles smoothly
        this.particles.forEach(p => p.color = this.getRandomColor());
        this.dust.forEach(p => p.color = this.getRandomColor());
      }
    }

    setState(stateName) {
      const prevState = this.state;
      this.state = stateName; // 'idle' | 'listening' | 'thinking' | 'speaking'
      this.stateTimer = 0;

      // State transition impulse
      if (stateName === 'speaking' && prevState !== 'speaking') {
        this.particles.forEach(p => {
          p.vy -= (1.6 + Math.random() * 2.2);
        });
      } else if (stateName === 'thinking' && prevState !== 'thinking') {
        const center = this.getPullCenter();
        const cx = center.x;
        const cy = center.y;
        this.particles.forEach(p => {
          const dx = cx - p.x;
          const dy = cy - p.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          // Smooth, calm tangential entry velocity
          p.vx = (-dy / dist) * (p.orbitDirection || 1) * 0.75;
          p.vy = (dx / dist) * (p.orbitDirection || 1) * 0.75;
        });
      }
    }

    getPullCenter() {
      if (this.options.pullCenterSelector && this.canvas) {
        const el = document.querySelector(this.options.pullCenterSelector);
        if (el) {
          const cr = this.canvas.getBoundingClientRect();
          const er = el.getBoundingClientRect();
          if (cr.width > 0 && er.width > 0) {
            return {
              x: (er.left + er.width / 2) - cr.left,
              y: (er.top + er.height / 2) - cr.top
            };
          }
        }
      }
      return {
        x: this.options.pullCenterX !== undefined ? this.options.pullCenterX : this.width / 2,
        y: this.options.pullCenterY !== undefined ? this.options.pullCenterY : this.height / 2
      };
    }

    setPullCenter(x, y) {
      this.options.pullCenterX = x;
      this.options.pullCenterY = y;
    }

    setAudioLevel(rms) {
      this.audioLevel = Math.max(0, Math.min(1.0, rms));
    }

    pulse(intensity = 1.0, x, y) {
      const center = this.getPullCenter();
      const px = x !== undefined ? x : center.x;
      const py = y !== undefined ? y : center.y;
      // Create expanding shockwave ring
      this.shockwaves.push({
        x: px,
        y: py,
        radius: 10,
        maxRadius: Math.max(this.width, this.height) * 0.6,
        alpha: 0.6 * intensity,
        speed: 8 * intensity,
        color: this.getRandomColor()
      });

      // Deflect nearby particles outward
      this.particles.forEach(p => {
        const dx = p.x - px;
        const dy = p.y - py;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 350 && dist > 1) {
          const force = (1 - dist / 350) * 12 * intensity;
          p.vx += (dx / dist) * force;
          p.vy += (dy / dist) * force;
        }
      });
    }

    /**
     * Trigger a cascading burst of synaptic idea lightning arcing across up to 6 jumps
     */
    triggerIdeaLightning(sourceNode, targetNode, targetJumps) {
      if (!this.particles || this.particles.length < 2) return;

      let p1 = sourceNode;
      if (!p1) {
        p1 = this.particles[Math.floor(Math.random() * this.particles.length)];
      }

      // Chain length: 3 to 6 jumps by default, or specific requested number up to 6
      const numJumps = targetJumps !== undefined ? Math.min(6, Math.max(1, targetJumps)) : (3 + Math.floor(Math.random() * 4));

      // Electric spark color palette
      const electricPalette = [
        { r: 170, g: 215, b: 255 }, // Electric cyan-blue
        { r: 255, g: 255, b: 255 }, // Pure white lightning
        { r: 190, g: 240, b: 255 }, // High-energy plasma cyan
        { r: 220, g: 190, b: 255 }, // Synaptic violet
        { r: 140, g: 230, b: 255 }, // Laser blue
      ];
      const boltColor = Math.random() < 0.7
        ? electricPalette[Math.floor(Math.random() * electricPalette.length)]
        : this.getRandomColor();

      const visited = new Set([p1]);
      let current = p1;
      current.synapticFlash = 1.0;

      for (let jump = 0; jump < numJumps; jump++) {
        let next = null;
        if (jump === 0 && targetNode && targetNode !== p1) {
          next = targetNode;
        } else {
          // Find unvisited candidates within proximity
          const candidates = [];
          for (let i = 0; i < this.particles.length; i++) {
            const p = this.particles[i];
            if (visited.has(p)) continue;
            const dx = p.x - current.x;
            const dy = p.y - current.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist >= 25 && dist <= 260) {
              candidates.push({ particle: p, dist: dist });
            }
          }

          if (candidates.length > 0) {
            candidates.sort((a, b) => a.dist - b.dist);
            // Pick from closest candidates for natural neural synaptic pathways
            const pickIdx = Math.floor(Math.random() * Math.min(candidates.length, 4));
            next = candidates[pickIdx].particle;
          } else {
            // Expand search radius if in a sparse zone
            for (let i = 0; i < this.particles.length; i++) {
              const p = this.particles[i];
              if (visited.has(p)) continue;
              const dx = p.x - current.x;
              const dy = p.y - current.y;
              const dist = Math.sqrt(dx * dx + dy * dy);
              if (dist <= 380) {
                candidates.push({ particle: p, dist: dist });
              }
            }
            if (candidates.length > 0) {
              candidates.sort((a, b) => a.dist - b.dist);
              next = candidates[0].particle;
            }
          }
        }

        if (!next) break; // Reached boundary of reachable constellation

        visited.add(next);
        next.synapticFlash = 1.0;

        // Cascade propagation delay (32ms per jump for high-speed synaptic travel)
        const delay = jump * 0.032;
        this.lightningArcs.push(new LightningArc(current.x, current.y, next.x, next.y, boltColor, {
          delay: delay,
          maxLife: 0.15 + (jump * 0.015)
        }));

        // 30% chance of a secondary divergent branch jump (dendritic idea fork)
        if (Math.random() < 0.30 && jump < numJumps - 1) {
          for (let i = 0; i < this.particles.length; i++) {
            const p = this.particles[i];
            if (visited.has(p)) continue;
            const dx = p.x - current.x;
            const dy = p.y - current.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist >= 30 && dist <= 200) {
              visited.add(p);
              p.synapticFlash = 1.0;
              this.lightningArcs.push(new LightningArc(current.x, current.y, p.x, p.y, boltColor, {
                delay: delay + 0.015,
                maxLife: 0.14
              }));
              break;
            }
          }
        }

        current = next;
      }
    }

    update(dt) {
      this.lastDt = dt;
      this.time = (this.time || 0) + (dt / 1000);
      this.stateTimer = (this.stateTimer || 0) + (dt / 1000);

      // Determine effective audio level:
      // If real microphone audio is active (audioLevel > 0.02), use it.
      // If state === 'speaking' and no mic is active, simulate rich natural speech cadence & voice modulation.
      let effectiveAudio = this.audioLevel;
      if (this.state === 'speaking' && this.audioLevel < 0.02) {
        const t = this.time;
        const speechCadence = Math.sin(t * 2.2);
        if (speechCadence > -0.3) {
          const syllableWave = Math.sin(t * 8.5) * 0.35 + Math.sin(t * 14.2) * 0.22 + Math.cos(t * 4.1) * 0.18;
          effectiveAudio = Math.max(0.12, Math.min(0.9, 0.38 + syllableWave));
        } else {
          effectiveAudio = 0.05; // brief breath pause between phrases
        }
      }
      this.effectiveAudio = effectiveAudio;

      if (this.state === 'listening') {
        const pull = this.options.listeningPullStrength !== undefined ? this.options.listeningPullStrength : 2.0;
        this.inwardWaveTimer = (this.inwardWaveTimer || 0) + (dt / 1000) * (0.8 + pull * 0.4);
      }

      // Idea Lightning Arcs (electric synapses flashing between bits during thinking)
      if (this.state === 'thinking' && this.options.enableIdeaLightning && !this.options.reducedMotion) {
        this.ideaLightningTimer = (this.ideaLightningTimer || 0) + (dt / 1000);
        if (this.ideaLightningTimer >= (this.nextLightningStrike || 0.45)) {
          this.triggerIdeaLightning();
          // 30% chance of double simultaneous idea lightning flash in different neural clusters
          if (Math.random() < 0.3) {
            this.triggerIdeaLightning();
          }
          const baseInterval = this.options.ideaLightningInterval || 0.50;
          this.nextLightningStrike = (baseInterval * 0.4) + (Math.random() * baseInterval * 1.2);
          this.ideaLightningTimer = 0;
        }
      }

      // Update active lightning arcs
      for (let i = this.lightningArcs.length - 1; i >= 0; i--) {
        const arc = this.lightningArcs[i];
        if (!arc.update(dt)) {
          this.lightningArcs.splice(i, 1);
        }
      }

      // Update dust
      for (let i = 0; i < this.dust.length; i++) {
        this.dust[i].update(dt, this.pointer, this.state, effectiveAudio * 0.3);
      }

      // Update primary particles
      for (let i = 0; i < this.particles.length; i++) {
        this.particles[i].update(dt, this.pointer, this.state, effectiveAudio);
      }

      // Update shockwaves
      for (let i = this.shockwaves.length - 1; i >= 0; i--) {
        const sw = this.shockwaves[i];
        sw.radius += sw.speed * (dt / 16.6);
        sw.alpha *= 0.94;
        if (sw.alpha < 0.01 || sw.radius > sw.maxRadius) {
          this.shockwaves.splice(i, 1);
        }
      }
    }

    draw() {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.width, this.height);

      const audio = this.effectiveAudio !== undefined ? this.effectiveAudio : (this.audioLevel || 0);
      const glowIntensity = this.options.glowIntensity || 1.2;

      // 1. Draw subtle ambient zero-g gradient orb in center (swells and blooms with voice volume and states)
      if (this.theme.ambientGlow) {
        const center = this.getPullCenter();
        const cx = center.x;
        const cy = center.y;
        let auraRadius = Math.max(this.width, this.height) * (0.7 + audio * 0.35);

        if (this.state === 'thinking') {
          const breathing = 1.0 + Math.sin(this.time * 0.8) * 0.07;
          auraRadius = Math.min(this.width, this.height) * 0.55 * breathing;
        }

        const grad = ctx.createRadialGradient(cx, cy, 20, cx, cy, auraRadius);
        if (audio > 0.05 && this.theme.colors && this.theme.colors.length > 0) {
          const c = this.theme.colors[0];
          const auraAlpha = Math.min(0.32, 0.04 + audio * 0.24 * glowIntensity);
          grad.addColorStop(0, `rgba(${c.r}, ${c.g}, ${c.b}, ${auraAlpha})`);
        } else if (this.state === 'thinking' && this.theme.colors && this.theme.colors.length > 0) {
          const c = this.theme.colors[0];
          const pulseAlpha = 0.04 + Math.max(0, Math.sin(this.time * 0.8)) * 0.06;
          grad.addColorStop(0, `rgba(${c.r}, ${c.g}, ${c.b}, ${pulseAlpha})`);
        } else {
          grad.addColorStop(0, this.theme.ambientGlow);
        }
        grad.addColorStop(1, 'transparent');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, this.width, this.height);
      }

      // 2. Draw shockwaves
      for (let i = 0; i < this.shockwaves.length; i++) {
        const sw = this.shockwaves[i];
        ctx.save();
        ctx.beginPath();
        ctx.arc(sw.x, sw.y, sw.radius, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${sw.color.r}, ${sw.color.g}, ${sw.color.b}, ${sw.alpha})`;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
      }

      // 3. Draw Constellation Links (Neural Network Web - reacts dynamically to states)
      if (this.options.connectConstellations && !this.options.reducedMotion) {
        let maxDist = this.options.connectionDistance;
        let lineWidth = 0.75;

        if (this.state === 'thinking') {
          maxDist *= 1.25; // Expand constellation web in thinking mode
          lineWidth = 1.0;
        } else if (this.state === 'speaking') {
          maxDist *= (1.0 + audio * 0.25);
          lineWidth = 0.75 + audio * 1.8;
        } else if (audio > 0.02) {
          maxDist *= (1.0 + audio * 0.25);
          lineWidth = 0.75 + audio * 1.5;
        }

        const maxDistSq = maxDist * maxDist;
        const len = this.particles.length;

        for (let i = 0; i < len; i++) {
          const pi = this.particles[i];
          for (let j = i + 1; j < len; j++) {
            const pj = this.particles[j];
            const dx = pi.x - pj.x;
            const dy = pi.y - pj.y;
            const distSq = dx * dx + dy * dy;

            if (distSq < maxDistSq) {
              const dist = Math.sqrt(distSq);
              let alpha = (1 - dist / maxDist) * 0.35;

              if (this.state === 'thinking') {
                // Gentle traveling cognitive neural wave along links
                const pulseWave = Math.sin((pi.x + pj.y) * 0.006 - this.time * 1.2);
                const neuralBoost = Math.max(0, pulseWave) * 0.45;
                alpha = Math.min(0.95, alpha * 1.3 + neuralBoost);
              } else if (this.state === 'speaking' || audio > 0.02) {
                alpha = Math.min(1.0, alpha * (0.8 + audio * 1.8 * glowIntensity));
              }

              ctx.beginPath();
              ctx.moveTo(pi.x, pi.y);
              ctx.lineTo(pj.x, pj.y);
              ctx.strokeStyle = `${this.theme.lineColor}${Math.min(1.0, alpha)})`;
              ctx.lineWidth = lineWidth;
              ctx.stroke();
            }
          }

          // Link to cursor if nearby
          if (this.pointer.active) {
            const dx = pi.x - this.pointer.x;
            const dy = pi.y - this.pointer.y;
            const distSq = dx * dx + dy * dy;
            const pointerMax = this.options.repulsionRadius;
            if (distSq < pointerMax * pointerMax) {
              const dist = Math.sqrt(distSq);
              const alpha = (1 - dist / pointerMax) * (0.45 + audio * 0.5 * glowIntensity);
              ctx.beginPath();
              ctx.moveTo(pi.x, pi.y);
              ctx.lineTo(this.pointer.x, this.pointer.y);
              ctx.strokeStyle = `${this.theme.lineColor}${Math.min(1.0, alpha)})`;
              ctx.lineWidth = lineWidth + 0.5;
              ctx.stroke();
            }
          }
        }
      }

      // 4. Draw Idea Lightning Arcs (Synaptic sparks flashing between bits like ideas)
      for (let i = 0; i < this.lightningArcs.length; i++) {
        this.lightningArcs[i].draw(ctx);
      }

      // 5. Draw dust particles
      for (let i = 0; i < this.dust.length; i++) {
        this.dust[i].draw(ctx);
      }

      // 6. Draw primary floating nodes (with synaptic flash flares on endpoints)
      for (let i = 0; i < this.particles.length; i++) {
        this.particles[i].draw(ctx);
      }
    }

    start() {
      if (this.running) return;
      this.running = true;
      this.lastTime = performance.now();

      const loop = (currentTime) => {
        if (!this.running) return;
        const dt = Math.min(currentTime - this.lastTime, 50); // Cap delta time
        this.lastTime = currentTime;

        this.update(dt);
        this.draw();

        this._animationFrame = requestAnimationFrame(loop);
      };

      this._animationFrame = requestAnimationFrame(loop);
    }

    pause() {
      this.running = false;
      if (this._animationFrame) {
        cancelAnimationFrame(this._animationFrame);
      }
    }

    destroy() {
      this.pause();
      if (this.options.autoResize) {
        window.removeEventListener('resize', this._onResize);
        if (this._resizeObserver) {
          this._resizeObserver.disconnect();
          this._resizeObserver = null;
        }
      }
      window.removeEventListener('mousemove', this._onPointerMove);
      window.removeEventListener('touchmove', this._onPointerMove);
      window.removeEventListener('touchstart', this._onPointerMove);
      window.removeEventListener('touchend', this._onPointerLeave);
      document.removeEventListener('mouseleave', this._onPointerLeave);
      document.removeEventListener('visibilitychange', this._onVisibilityChange);
    }
  }

  // Export themes and class
  AntigravityField.THEMES = THEMES;
  return AntigravityField;
}));
