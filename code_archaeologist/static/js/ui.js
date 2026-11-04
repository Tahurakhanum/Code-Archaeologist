// =============================================================================
// ui.js: every shared visual effect for Code Archaeologist.
//
// Each feature is one small init function, listed at the bottom of this file.
// Each one is progressive enhancement: the app still works if this file fails,
// and each init quietly stops if its elements are not on the current page.
// =============================================================================
(() => {
  'use strict';

  // Tells the safety timer in base.html that this file loaded.
  window.uiReady = true;

  const root = document.documentElement;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // True only for a real mouse. Touch devices skip the cursor, magnet and parallax.
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  // Smooth motion that does not depend on the screen's refresh rate.
  // Each frame closes a share of the gap, and that share is worked out from the time
  // that really passed. So 60 Hz and 165 Hz screens feel the same, and a skipped
  // frame does not make things slow down and jump. "smoothing" is in milliseconds:
  // a bigger number means a softer, slower follow.
  const ease = (current, target, elapsed, smoothing) => target + (current - target) * Math.exp(-elapsed / smoothing);
  // Time since the last frame, capped so that returning to a paused tab never causes a jump.
  const frameTime = (now, last) => Math.min(Math.max(now - last, 1), 50);


  // ---------------------------------------------------------------------------
  // Star field: a lightweight canvas behind everything.
  // Landing and auth pages twinkle. App pages get one calm, static drawing.
  // ---------------------------------------------------------------------------
  function initStarfield() {
    const canvas = $('#starfield');
    if (!canvas) return;
    const context = canvas.getContext('2d');
    const calm = document.body.classList.contains('page-app');
    const animated = !calm && !reduceMotion;

    // Star positions are stored as 0..1 so a resize never reshuffles the sky.
    const count = calm ? 70 : Math.min(320, Math.round((window.innerWidth * window.innerHeight) / 5200));
    const stars = Array.from({ length: count }, () => ({
      x: Math.random(),
      y: Math.random(),
      size: 0.6 + Math.random() * 1.2,
      depth: 0.2 + Math.random() * 0.8, // nearer stars move further in the parallax
      alpha: (calm ? 0.12 : 0.25) + Math.random() * (calm ? 0.25 : 0.6),
      speed: 0.4 + Math.random() * 1.4,
      phase: Math.random() * Math.PI * 2,
    }));

    let width = 0;
    let height = 0;
    let mouseX = 0;        // the parallax position being drawn
    let mouseY = 0;
    let targetX = 0;       // where the mouse says the parallax should end up
    let targetY = 0;
    let scrollShift = 0;

    const draw = (time) => {
      context.clearRect(0, 0, width, height);
      for (const star of stars) {
        const twinkle = animated ? 0.65 + 0.35 * Math.sin(time * 0.001 * star.speed + star.phase) : 1;
        // The modulo wraps stars around the screen edges as they shift.
        const x = (star.x * width + mouseX * star.depth * 14 + width) % width;
        const y = (star.y * height - scrollShift * star.depth + mouseY * star.depth * 14 + height * 4) % height;
        context.globalAlpha = star.alpha * twinkle;
        context.fillStyle = star.depth > 0.6 ? '#dbe6ff' : '#93b4ff';
        context.fillRect(x, y, star.size, star.size);
      }
    };

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5); // caps the pixel work
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      if (!animated) draw(0);
    };
    resize();
    window.addEventListener('resize', resize);
    if (!animated) return;

    if (finePointer) {
      window.addEventListener('pointermove', (event) => {
        targetX = event.clientX / width - 0.5;
        targetY = event.clientY / height - 0.5;
      }, { passive: true });
    }

    // While the stars are moving they are drawn every frame, so they glide. When nothing
    // is moving, about 30 frames per second is plenty for a slow twinkle.
    let frame = 0;
    let lastFrame = 0;
    let lastDraw = 0;
    const loop = (time) => {
      frame = requestAnimationFrame(loop);
      const elapsed = frameTime(time, lastFrame);
      lastFrame = time;
      const moving = Math.abs(targetX - mouseX) + Math.abs(targetY - mouseY) > 0.0002
        || window.scrollY * 0.04 !== scrollShift;
      if (!moving && time - lastDraw < 30) return;
      mouseX = ease(mouseX, targetX, elapsed, 140);
      mouseY = ease(mouseY, targetY, elapsed, 140);
      scrollShift = window.scrollY * 0.04;
      lastDraw = time;
      draw(time);
    };
    frame = requestAnimationFrame(loop);

    // Stop drawing completely while the tab is hidden.
    document.addEventListener('visibilitychange', () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) frame = requestAnimationFrame(loop);
    });
  }


  // ---------------------------------------------------------------------------
  // Custom cursor: a dot that follows exactly, and a ring that eases behind it.
  // Only transforms are written, and the loop stops once the ring has settled.
  // ---------------------------------------------------------------------------
  function initCursor() {
    const dot = $('#cursorDot');
    const ring = $('#cursorRing');
    const label = $('#cursorLabel');
    if (!dot || !ring || !finePointer || reduceMotion) return;

    root.classList.add('has-cursor');

    const TEXT_FIELDS = 'input:not([type="radio"], [type="checkbox"], [type="file"], [type="hidden"]), textarea, select';
    const INTERACTIVE = 'a, button, summary, label, input[type="file"]';
    let mouseX = 0;
    let mouseY = 0;
    let dotX = 0;
    let dotY = 0;
    let ringX = 0;
    let ringY = 0;
    let frame = 0;
    let lastFrame = 0;

    const render = (now) => {
      const elapsed = frameTime(now, lastFrame);
      lastFrame = now;
      // The dot stays almost exactly on the pointer. The tiny smoothing hides the uneven
      // steps that appear because the mouse and the screen update at different rates.
      dotX = ease(dotX, mouseX, elapsed, 8);
      dotY = ease(dotY, mouseY, elapsed, 8);
      // The ring trails behind with a softer follow.
      ringX = ease(ringX, mouseX, elapsed, 35);
      ringY = ease(ringY, mouseY, elapsed, 35);
      dot.style.transform = `translate3d(${dotX}px, ${dotY}px, 0)`;
      ring.style.transform = `translate3d(${ringX}px, ${ringY}px, 0)`;
      const settled = Math.abs(mouseX - ringX) < 0.05 && Math.abs(mouseY - ringY) < 0.05;
      frame = settled ? 0 : requestAnimationFrame(render);
    };

    window.addEventListener('pointermove', (event) => {
      mouseX = event.clientX;
      mouseY = event.clientY;
      if (!root.classList.contains('cursor-on')) {
        dotX = mouseX; // first movement: start on the pointer instead of flying in from the corner
        dotY = mouseY;
        ringX = mouseX;
        ringY = mouseY;
        root.classList.add('cursor-on');
      }
      if (!frame) {
        lastFrame = performance.now();
        frame = requestAnimationFrame(render);
      }
    }, { passive: true });

    // One listener on the document also covers elements added later.
    document.addEventListener('pointerover', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const onText = Boolean(target.closest(TEXT_FIELDS));
      const onControl = !onText && Boolean(target.closest(INTERACTIVE));
      const labelled = !onText && !onControl ? target.closest('[data-cursor]') : null;
      root.classList.toggle('cursor-off-text', onText);
      ring.classList.toggle('is-hover', onControl || Boolean(labelled));
      ring.classList.toggle('is-card', !onControl && !labelled && Boolean(target.closest('.card')));
      // Only touch the text when it changes, so moving over a row never forces a layout.
      const text = labelled ? labelled.dataset.cursor : '';
      if (label.textContent !== text) label.textContent = text;
    });

    window.addEventListener('pointerdown', () => ring.classList.add('is-down'));
    window.addEventListener('pointerup', () => ring.classList.remove('is-down'));
    root.addEventListener('mouseleave', () => root.classList.remove('cursor-on'));

    // Data rows and charts show a small label inside the ring.
    $$('tbody tr:not([data-cursor])').forEach((row) => { row.dataset.cursor = 'VIEW'; });
  }


  // ---------------------------------------------------------------------------
  // Page transitions: the CSS @view-transition rule handles modern browsers.
  // Others get this overlay, which fades in on click and fades out on arrival.
  // ---------------------------------------------------------------------------
  function initPageTransitionFallback() {
    const wipe = $('#pageWipe');

    // Native transitions run for every same-origin navigation, so form submissions
    // cancel theirs here. "pageswap" fires just before the old page is captured.
    let submittingForm = false;
    document.addEventListener('submit', () => { submittingForm = true; });
    window.addEventListener('pageswap', (event) => {
      if (!submittingForm || !event.viewTransition) return;
      const transition = event.viewTransition;
      // Skipping makes these promises reject, which is expected, so mark them as handled.
      [transition.ready, transition.finished, transition.updateCallbackDone].forEach((promise) => promise.catch(() => {}));
      transition.skipTransition();
    });

    if (!wipe || reduceMotion || 'CSSViewTransitionRule' in window) return;
    const FLAG = 'code-archaeologist-wipe';

    // sessionStorage can throw in private windows, so it is wrapped in try/catch.
    try {
      if (sessionStorage.getItem(FLAG)) {
        sessionStorage.removeItem(FLAG);
        wipe.classList.add('is-active', 'no-transition');
        requestAnimationFrame(() => requestAnimationFrame(() => wipe.classList.remove('is-active', 'no-transition')));
      }
    } catch (error) { /* the fade-out on arrival is optional */ }

    document.addEventListener('click', (event) => {
      const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
      if (!link || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if ((link.target && link.target !== '_self') || link.hasAttribute('download')) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.endsWith('.pdf')) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return; // "#" links
      event.preventDefault();
      wipe.classList.add('is-active');
      try { sessionStorage.setItem(FLAG, '1'); } catch (error) { /* optional */ }
      setTimeout(() => { window.location.href = link.href; }, 260);
    });

    // The back button can restore a frozen page with the overlay still showing.
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) wipe.classList.remove('is-active');
    });
  }


  // ---------------------------------------------------------------------------
  // Scroll reveals: [data-reveal] elements fade up as they enter the viewport.
  // ---------------------------------------------------------------------------
  function initReveals() {
    const items = $$('[data-reveal]');
    if (!items.length) return;
    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach((item) => item.classList.add('is-in'));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.filter((entry) => entry.isIntersecting).forEach((entry, index) => {
        entry.target.style.transitionDelay = `${index * 70}ms`; // stagger each batch
        entry.target.classList.add('is-in');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -6% 0px' });
    items.forEach((item) => observer.observe(item));
  }


  // ---------------------------------------------------------------------------
  // Count-up numbers. Handles text like "3 / 1", and the final text is always
  // exactly what the server sent. Pads with zeros for the "000" counter look.
  // ---------------------------------------------------------------------------
  function initCounters() {
    const items = $$('[data-count]');
    if (!items.length || reduceMotion || !('IntersectionObserver' in window)) return;

    const run = (element) => {
      const finalText = element.textContent;
      const start = performance.now();
      const duration = 1100;
      const step = (now) => {
        const progress = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 4);
        element.textContent = progress === 1 ? finalText : finalText.replace(/\d+/g, (number) =>
          String(Math.round(Number(number) * eased)).padStart(number.length, '0'));
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    const observer = new IntersectionObserver((entries) => {
      entries.filter((entry) => entry.isIntersecting).forEach((entry) => {
        observer.unobserve(entry.target);
        run(entry.target);
      });
    });
    items.forEach((item) => observer.observe(item));
  }


  // ---------------------------------------------------------------------------
  // Magnetic buttons: buttons lean a little towards the mouse.
  // The size is measured once on entry, so moving the mouse never forces layout.
  // ---------------------------------------------------------------------------
  function initMagneticButtons() {
    if (!finePointer || reduceMotion) return;
    $$('.button, .danger-button').forEach((button) => {
      let rect = null;
      button.addEventListener('pointerenter', () => { rect = button.getBoundingClientRect(); });
      button.addEventListener('pointermove', (event) => {
        if (!rect) return;
        const x = (event.clientX - (rect.left + rect.width / 2)) * 0.22;
        const y = (event.clientY - (rect.top + rect.height / 2)) * 0.32;
        button.style.setProperty('--mx', `${x.toFixed(1)}px`);
        button.style.setProperty('--my', `${y.toFixed(1)}px`);
      });
      button.addEventListener('pointerleave', () => {
        rect = null;
        button.style.setProperty('--mx', '0px');
        button.style.setProperty('--my', '0px');
      });
    });
  }


  // ---------------------------------------------------------------------------
  // Toasts: a close button, and auto-dismiss after 5s. Hovering or focusing a
  // toast pauses its timer, so a message never vanishes while being read.
  // ---------------------------------------------------------------------------
  function initToasts() {
    $$('.toast-stack .flash').forEach((toast) => {
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'toast-close';
      close.setAttribute('aria-label', 'Dismiss message');
      close.textContent = '×';
      toast.append(close);

      let timer = 0;
      const dismiss = () => {
        clearTimeout(timer);
        toast.classList.add('is-leaving');
        setTimeout(() => toast.remove(), reduceMotion ? 0 : 300);
      };
      const startTimer = () => { timer = setTimeout(dismiss, 5000); };

      close.addEventListener('click', dismiss);
      toast.addEventListener('pointerenter', () => clearTimeout(timer));
      toast.addEventListener('pointerleave', startTimer);
      toast.addEventListener('focusin', () => clearTimeout(timer));
      toast.addEventListener('focusout', startTimer);
      startTimer();
    });
  }


  // ---------------------------------------------------------------------------
  // Live local-time readout, in [data-clock] elements.
  // ---------------------------------------------------------------------------
  function initClock() {
    const clocks = $$('[data-clock]');
    if (!clocks.length) return;
    const pad = (number) => String(number).padStart(2, '0');
    const tick = () => {
      const now = new Date();
      const offset = -now.getTimezoneOffset();
      const sign = offset >= 0 ? '+' : '-';
      const zone = `GMT${sign}${Math.floor(Math.abs(offset) / 60)}${offset % 60 ? `:${pad(Math.abs(offset) % 60)}` : ''}`;
      const text = `LOCAL ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())} ${zone}`;
      clocks.forEach((clock) => { clock.textContent = text; });
    };
    tick();
    setInterval(tick, 1000);
  }


  // ---------------------------------------------------------------------------
  // "On this page" index: built from [data-toc] sections, so it can never list
  // a section the server did not render. Highlights the section being read.
  // ---------------------------------------------------------------------------
  function initPageIndex() {
    const index = $('[data-page-index]');
    if (!index) return;
    const sections = $$('[data-toc]');
    if (sections.length < 2) return;

    // Use the same number as the CSS counter that writes the S.0x section codes.
    const codes = $$('.sec-code');
    const firstNumber = Number(index.dataset.start || 1);
    const list = document.createElement('ol');
    const links = new Map();
    sections.forEach((section, position) => {
      if (!section.id) section.id = `section-${position + 1}`;
      const code = section.matches('.sec-code') ? section : $('.sec-code', section);
      const number = (code ? codes.indexOf(code) : position) + firstNumber;
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = `#${section.id}`;
      const badge = document.createElement('b');
      badge.textContent = `S.${String(number).padStart(2, '0')}`;
      link.append(badge, document.createTextNode(section.dataset.toc));
      item.append(link);
      list.append(item);
      links.set(section, link);
    });

    const title = document.createElement('p');
    title.className = 'page-index-title';
    title.textContent = 'On this page';
    index.append(title, list);

    if (!('IntersectionObserver' in window)) return;
    // The thin band across the middle of the screen decides the current section.
    const observer = new IntersectionObserver((entries) => {
      entries.filter((entry) => entry.isIntersecting).forEach((entry) => {
        links.forEach((link) => {
          link.classList.remove('is-current');
          link.removeAttribute('aria-current');
        });
        const current = links.get(entry.target);
        current.classList.add('is-current');
        current.setAttribute('aria-current', 'true');
      });
    }, { rootMargin: '-38% 0px -58% 0px' });
    sections.forEach((section) => observer.observe(section));
  }


  // ---------------------------------------------------------------------------
  // Mobile menu: the sidebar's slide-down panel.
  // ---------------------------------------------------------------------------
  function initSidebarMenu() {
    const sidebar = $('.sidebar');
    const toggle = $('.menu-toggle');
    if (!sidebar || !toggle) return;
    const setOpen = (open) => {
      sidebar.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
    };
    toggle.addEventListener('click', () => setOpen(!sidebar.classList.contains('is-open')));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
        setOpen(false);
        toggle.focus();
      }
    });
  }


  // ---------------------------------------------------------------------------
  // Landing page: the hero orb leans gently towards the mouse.
  // ---------------------------------------------------------------------------
  function initOrb() {
    const orb = $('.orb');
    if (!orb || !finePointer || reduceMotion) return;
    let targetX = 0;
    let targetY = 0;
    let x = 0;
    let y = 0;
    let frame = 0;
    let lastFrame = 0;
    const render = (now) => {
      const elapsed = frameTime(now, lastFrame);
      lastFrame = now;
      x = ease(x, targetX, elapsed, 200);
      y = ease(y, targetY, elapsed, 200);
      orb.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`;
      const settled = Math.abs(targetX - x) < 0.1 && Math.abs(targetY - y) < 0.1;
      frame = settled ? 0 : requestAnimationFrame(render);
    };
    window.addEventListener('pointermove', (event) => {
      targetX = (event.clientX / window.innerWidth - 0.5) * 46;
      targetY = (event.clientY / window.innerHeight - 0.5) * 46;
      if (!frame) {
        lastFrame = performance.now();
        frame = requestAnimationFrame(render);
      }
    }, { passive: true });
  }


  // ---------------------------------------------------------------------------
  // Landing page: the glowing thread that draws itself along the scroll,
  // passing through each numbered feature's node.
  // ---------------------------------------------------------------------------
  function initThread() {
    const scope = $('.thread-scope');
    const line = $('.thread-line');
    if (!scope || !line) return;
    const svg = line.ownerSVGElement;
    const base = $('.thread-base', svg);
    const nodes = $$('.feature-node', scope);
    if (nodes.length < 2) return;

    let top = 0;      // the scope's distance from the top of the document
    let points = [];  // node centres, relative to the scope

    // Measure the nodes and draw a smooth curve through them. pathLength="1" in the
    // HTML means the dash offset below can be written as a simple 0..1 fraction.
    const layout = () => {
      const rect = scope.getBoundingClientRect();
      top = rect.top + window.scrollY;
      points = nodes.map((node) => {
        const box = node.getBoundingClientRect();
        return { x: box.left - rect.left + box.width / 2, y: box.top - rect.top + box.height / 2 };
      });
      svg.setAttribute('viewBox', `0 0 ${rect.width} ${rect.height}`);
      let path = `M ${points[0].x} ${points[0].y}`;
      for (let i = 1; i < points.length; i += 1) {
        const middle = (points[i - 1].y + points[i].y) / 2;
        path += ` C ${points[i - 1].x} ${middle}, ${points[i].x} ${middle}, ${points[i].x} ${points[i].y}`;
      }
      line.setAttribute('d', path);
      base.setAttribute('d', path);
      update();
    };

    const update = () => {
      // The pen tip sits 65% of the way down the screen.
      const penY = reduceMotion ? Infinity : window.scrollY + window.innerHeight * 0.65 - top;
      const first = points[0].y;
      const lastY = points[points.length - 1].y;
      const progress = Math.max(0, Math.min(1, (penY - first) / (lastY - first)));
      line.style.strokeDashoffset = String(1 - progress);
      nodes.forEach((node, i) => node.classList.toggle('is-lit', penY >= points[i].y));
    };

    let queued = false;
    window.addEventListener('scroll', () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; update(); });
    }, { passive: true });
    window.addEventListener('resize', layout);
    window.addEventListener('load', layout);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout); // fonts shift the layout
    layout();
  }


  // ---------------------------------------------------------------------------
  // Horizontal strip that can be dragged with the mouse.
  // Touch screens already scroll it natively, and keyboards use the arrow keys.
  // ---------------------------------------------------------------------------
  function initDragStrips() {
    $$('.drag-strip').forEach((strip) => {
      let startX = 0;
      let startScroll = 0;
      let dragging = false;
      strip.addEventListener('pointerdown', (event) => {
        if (event.pointerType !== 'mouse') return;
        dragging = true;
        startX = event.clientX;
        startScroll = strip.scrollLeft;
        strip.setPointerCapture(event.pointerId);
        strip.classList.add('is-dragging');
      });
      strip.addEventListener('pointermove', (event) => {
        if (dragging) strip.scrollLeft = startScroll - (event.clientX - startX);
      });
      const stop = () => {
        dragging = false;
        strip.classList.remove('is-dragging');
      };
      strip.addEventListener('pointerup', stop);
      strip.addEventListener('pointercancel', stop);
    });
  }


  // ---------------------------------------------------------------------------
  // <details> elements open and close with a smooth height animation.
  // ---------------------------------------------------------------------------
  function initDetails() {
    if (reduceMotion) return; // the native instant toggle is the right behaviour here
    $$('details.note').forEach((details) => {
      const summary = $('summary', details);
      let animation = null;

      const run = (from, to, onDone) => {
        if (animation) animation.cancel();
        details.style.overflow = 'hidden';
        animation = details.animate({ height: [from, to] }, { duration: 420, easing: 'cubic-bezier(.16, 1, .3, 1)' });
        animation.onfinish = () => {
          animation = null;
          details.style.overflow = '';
          if (onDone) onDone();
        };
      };

      summary.addEventListener('click', (event) => {
        event.preventDefault();
        const startHeight = `${details.offsetHeight}px`;
        if (details.open && !details.classList.contains('is-closing')) {
          details.classList.add('is-closing');
          run(startHeight, `${summary.offsetHeight}px`, () => {
            details.open = false;
            details.classList.remove('is-closing');
          });
        } else {
          details.classList.remove('is-closing');
          details.open = true;
          run(startHeight, `${details.scrollHeight}px`);
        }
      });
    });
  }


  // ---------------------------------------------------------------------------
  // Code panels: split <pre> text into numbered lines and colour diff lines.
  // Uses textContent only, so repository code can never become real HTML.
  // ---------------------------------------------------------------------------
  function initCodeLines() {
    $$('pre[data-lines]').forEach((pre) => {
      const code = $('code', pre) || pre;
      const isDiff = pre.classList.contains('diff');
      let number = Number(pre.dataset.start || 1);
      const lines = code.textContent.replace(/\n$/, '').split('\n');
      const fragment = document.createDocumentFragment();
      lines.forEach((text) => {
        const line = document.createElement('span');
        line.className = 'code-line';
        line.dataset.n = String(number);
        line.textContent = text;
        if (isDiff) {
          if (text.startsWith('@@')) line.classList.add('line-hunk');
          else if (text.startsWith('+') && !text.startsWith('+++')) line.classList.add('line-add');
          else if (text.startsWith('-') && !text.startsWith('---')) line.classList.add('line-del');
        }
        fragment.append(line);
        number += 1;
      });
      code.replaceChildren(fragment);
    });
  }


  // ---------------------------------------------------------------------------
  // New analysis page: source cards and the drag-and-drop ZIP zone.
  // ---------------------------------------------------------------------------
  function initIngestionForm() {
    const form = $('.ingestion-form');
    if (!form) return;
    const github = $('input[value="github"]', form);
    const zip = $('input[value="zip"]', form);
    const url = $('input[name="repository_url"]', form);
    const file = $('input[name="archive"]', form);
    const zone = $('.dropzone', form);
    const fileName = $('[data-file-name]', form);

    // The CSS hides the panel for the unselected source. Browsers refuse to submit
    // a form if a hidden field is invalid, and they show no error, so the hidden
    // field is disabled too. The server only reads the field for the chosen source.
    const sync = () => {
      url.disabled = !github.checked;
      file.disabled = !zip.checked;
    };
    [github, zip].forEach((radio) => radio.addEventListener('change', sync));
    window.addEventListener('pageshow', sync); // the back button can restore the radios
    sync();

    file.addEventListener('change', () => {
      fileName.textContent = file.files.length ? file.files[0].name : '';
      zone.classList.toggle('has-file', file.files.length > 0);
    });

    // The file input covers the whole zone, so dropping onto it just works.
    // These listeners only drive the highlight.
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, () => zone.classList.add('is-over')));
    ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, () => zone.classList.remove('is-over')));
  }


  // ---------------------------------------------------------------------------
  // Progress page: types each new status message like a terminal line and ticks
  // the checklist. #progressMessage stays the real element that the polling script
  // updates and screen readers announce. This only watches it and draws a copy,
  // so screen readers hear whole messages, not one letter at a time.
  // ---------------------------------------------------------------------------
  function initProgressTerminal() {
    const message = $('#progressMessage');
    const log = $('#terminalLog');
    if (!message || !log) return;
    const steps = $$('.step-list li');
    let shown = '';
    let finishTyping = () => {};

    const typeInto = (element, text) => {
      finishTyping();
      if (reduceMotion) {
        element.textContent = text;
        return;
      }
      let position = 0;
      let timer = 0;
      finishTyping = () => {
        clearTimeout(timer);
        element.textContent = text;
        finishTyping = () => {};
      };
      const next = () => {
        position += 1;
        element.textContent = text.slice(0, position);
        if (position < text.length) timer = setTimeout(next, 18);
        else finishTyping = () => {};
      };
      next();
    };

    const show = (text) => {
      if (!text || text === shown) return;
      shown = text;
      finishTyping();

      // The previous line is finished: tick it if it was a real step.
      const previous = log.lastElementChild;
      if (previous && previous.dataset.step === 'true') previous.classList.add('is-done');

      const index = steps.findIndex((step) => text.includes(step.dataset.match));
      const line = document.createElement('div');
      line.className = 'terminal-line';
      line.dataset.step = String(index >= 0);
      const body = document.createElement('span');
      line.append(body);
      log.append(line);
      while (log.children.length > 10) log.firstElementChild.remove();
      typeInto(body, text);

      if (index >= 0) {
        steps.forEach((step, position) => {
          step.classList.toggle('is-done', position < index);
          step.classList.toggle('is-active', position === index);
        });
      }
    };

    new MutationObserver(() => show(message.textContent.trim()))
      .observe(message, { childList: true, characterData: true, subtree: true });
    show(message.textContent.trim());
  }


  // ---------------------------------------------------------------------------
  // Dashboard table: clicking anywhere on a row opens it, like its first link.
  // ---------------------------------------------------------------------------
  function initRowLinks() {
    $$('tr[data-cursor="OPEN"]').forEach((row) => {
      row.addEventListener('click', (event) => {
        if (event.target.closest('a, button') || String(window.getSelection())) return;
        const link = $('a', row);
        if (link) link.click();
      });
    });
  }


  // ---------------------------------------------------------------------------
  // Delete confirmation: a mouse must rest on the button until it has filled with
  // red, which prevents an accidental click. Keyboard and touch are not delayed.
  // ---------------------------------------------------------------------------
  function initDeliberateButtons() {
    if (reduceMotion) return;
    const HOLD = 650;
    $$('[data-deliberate]').forEach((button) => {
      let timer = 0;
      let lastPointer = '';
      button.addEventListener('pointerdown', (event) => { lastPointer = event.pointerType; });
      button.addEventListener('pointerenter', (event) => {
        if (event.pointerType !== 'mouse') return;
        timer = setTimeout(() => button.classList.add('is-armed'), HOLD);
      });
      button.addEventListener('pointerleave', () => {
        clearTimeout(timer);
        button.classList.remove('is-armed');
      });
      button.addEventListener('click', (event) => {
        if (lastPointer === 'mouse' && !button.classList.contains('is-armed')) event.preventDefault();
        lastPointer = '';
      });
    });
  }


  // ---------------------------------------------------------------------------
  // Timeline: the rail scrolls on its own, so bring the selected commit into view.
  // ---------------------------------------------------------------------------
  function initTimelineRail() {
    const list = $('.timeline-list');
    const selected = $('.timeline-item.selected');
    if (list && selected) list.scrollTop = selected.offsetTop - list.offsetTop - 12;
  }


  // ---------------------------------------------------------------------------
  // Investigate page: a new answer can be far below the fold, so scroll it into view.
  // ---------------------------------------------------------------------------
  function initAnswerScroll() {
    const answer = $('.ask-panel .answer-box');
    if (answer) answer.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
  }


  // ---------------------------------------------------------------------------
  // Start everything. One failing feature must never stop the others.
  // ---------------------------------------------------------------------------
  [
    initStarfield, initCursor, initPageTransitionFallback, initCodeLines, initReveals,
    initCounters, initMagneticButtons, initToasts, initClock, initPageIndex,
    initSidebarMenu, initOrb, initThread, initDragStrips, initDetails,
    initIngestionForm, initProgressTerminal, initRowLinks, initDeliberateButtons, initTimelineRail,
    initAnswerScroll,
  ].forEach((init) => {
    try {
      init();
    } catch (error) {
      console.error(`${init.name} failed:`, error);
    }
  });
})();
