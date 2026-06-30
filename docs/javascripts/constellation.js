/*
 * Firefly constellation — the landing-page signature.
 * Amber fireflies drift through the dark; when they pass near one another a
 * faint violet edge is drawn between them. Read it two ways at once: fireflies
 * in the night, and a network of agents delegating. One ambient animation,
 * nothing else moves.
 *
 * - Honours prefers-reduced-motion (renders a single static frame).
 * - Pauses when the hero scrolls out of view.
 * - Re-inits on Material's instant navigation.
 */
(function () {
  "use strict";

  function start() {
    var canvas = document.getElementById("ff-constellation");
    if (!canvas || canvas.dataset.ffInit === "1") return;
    canvas.dataset.ffInit = "1";

    var ctx = canvas.getContext("2d");
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var host = canvas.parentElement;
    var w = 0, h = 0, dpr = 1, nodes = [], raf = null, running = true;
    var LINK = 150;

    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = host.clientWidth;
      h = host.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function seed() {
      var count = Math.max(16, Math.min(46, Math.round((w * h) / 26000)));
      nodes = [];
      for (var i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.25,
          vy: (Math.random() - 0.5) * 0.25,
          r: Math.random() * 1.5 + 0.8,
          p: Math.random() * Math.PI * 2
        });
      }
    }

    function frame(t) {
      ctx.clearRect(0, 0, w, h);

      // edges (the agent network)
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var a = nodes[i], b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < LINK) {
            ctx.strokeStyle = "rgba(167,139,250," + (1 - d / LINK) * 0.22 + ")";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      }

      // fireflies
      for (var k = 0; k < nodes.length; k++) {
        var n = nodes[k];
        if (!reduce) {
          n.x += n.vx; n.y += n.vy;
          if (n.x < 0 || n.x > w) n.vx *= -1;
          if (n.y < 0 || n.y > h) n.vy *= -1;
        }
        var tw = reduce ? 0.85 : 0.55 + 0.45 * Math.sin(t * 0.001 + n.p);
        var halo = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 6);
        halo.addColorStop(0, "rgba(255,249,193," + 0.9 * tw + ")");
        halo.addColorStop(0.4, "rgba(246,168,33," + 0.5 * tw + ")");
        halo.addColorStop(1, "rgba(246,128,0,0)");
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * 6, 0, 6.2832);
        ctx.fill();
        ctx.fillStyle = "rgba(255,253,240," + 0.95 * tw + ")";
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r * 0.9, 0, 6.2832);
        ctx.fill();
      }

      if (running && !reduce) raf = requestAnimationFrame(frame);
    }

    function play() {
      if (reduce) { frame(0); return; }
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(frame);
    }

    size();
    seed();
    play();

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          running = e.isIntersecting;
          if (running) play(); else cancelAnimationFrame(raf);
        });
      }).observe(canvas);
    }

    var rt;
    window.addEventListener("resize", function () {
      clearTimeout(rt);
      rt = setTimeout(function () { size(); seed(); if (reduce) frame(0); }, 200);
    });
  }

  // Copy-to-clipboard for the install command.
  function copyInstall() {
    var btn = document.querySelector(".ff-install__copy");
    if (!btn || btn.dataset.ffBound === "1") return;
    btn.dataset.ffBound = "1";
    btn.addEventListener("click", function () {
      var cmd = btn.getAttribute("data-copy") || "";
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(cmd).then(function () {
        btn.classList.add("is-copied"); // CSS swaps the glyph; no innerHTML
        setTimeout(function () { btn.classList.remove("is-copied"); }, 1400);
      });
    });
  }

  function boot() { start(); copyInstall(); }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot); // Material instant navigation
  } else if (document.readyState !== "loading") {
    boot();
  } else {
    document.addEventListener("DOMContentLoaded", boot);
  }
})();
