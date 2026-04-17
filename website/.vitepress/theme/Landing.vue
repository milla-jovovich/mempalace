<script setup>
import { onMounted, onBeforeUnmount } from 'vue'

onMounted(() => {
  if (typeof document === 'undefined') return

  // Hide VitePress chrome while the landing component is live, restore on leave.
  document.body.classList.add('mempalace-active')

  /* ---------- Waitlist submission ---------- */
  ;(function initWaitlist(){
    const ENDPOINT = 'https://br.staging.mempalaceofficial.com/waitlist'
    const forms = document.querySelectorAll('.mempalace-landing .waitlist')
    const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

    forms.forEach(form => {
      const input  = form.querySelector('.waitlist-input')
      const button = form.querySelector('.waitlist-submit')
      const msg    = form.querySelector('.waitlist-msg')
      const source = form.dataset.source || 'landing'

      function setState(state, text) {
        form.classList.remove('is-pending', 'is-success', 'is-error')
        if (state) form.classList.add('is-' + state)
        if (text != null) msg.textContent = text
      }

      form.addEventListener('submit', async (e) => {
        e.preventDefault()
        if (form.classList.contains('is-success') || form.classList.contains('is-pending')) return

        const email = (input.value || '').trim()
        if (!emailRe.test(email)) {
          setState('error', 'Please provide a valid email address.')
          input.focus()
          return
        }

        setState('pending', 'Sending…')
        button.disabled = true
        input.disabled = true

        try {
          const res = await fetch(ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, source })
          })
          let data = null
          try { data = await res.json() } catch (_) { /* no body */ }

          if (res.ok) {
            setState('success', (data && data.message) || "You're on the list! We'll be in touch.")
            // keep inputs disabled so they can't resubmit accidentally
            input.value = email
            return
          }

          if (res.status === 429) {
            setState('error', 'Whoa — slow down a moment, then try again.')
          } else if (res.status === 400) {
            setState('error', (data && data.message) || 'Please provide a valid email address.')
          } else {
            setState('error', (data && data.message) || 'Something went wrong. Please try again later.')
          }
          button.disabled = false
          input.disabled = false
        } catch (_err) {
          setState('error', 'Network error — please try again.')
          button.disabled = false
          input.disabled = false
        }
      })

      // Clear error state as soon as the user edits
      input.addEventListener('input', () => {
        if (form.classList.contains('is-error')) setState(null, '')
      })
    })
  })()



  /* ---------- Reveal-on-scroll for cards ---------- */
  ;(function(){
    if (!('IntersectionObserver' in window)) return
    const items = document.querySelectorAll('.mempalace-landing .stratum, .mempalace-landing .mech, .mempalace-landing .slab')
    items.forEach(el => {
      el.style.opacity = '0'
      el.style.transform = 'translateY(20px)'
      el.style.transition = 'opacity 0.9s ease, transform 0.9s ease'
    })
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting){
          const idx = [...entry.target.parentElement.children].indexOf(entry.target)
          entry.target.style.transitionDelay = (idx * 80) + 'ms'
          entry.target.style.opacity = '1'
          entry.target.style.transform = 'translateY(0)'
          io.unobserve(entry.target)
        }
      })
    }, { rootMargin: '0px 0px -80px 0px' })
    items.forEach(el => io.observe(el))
  })()

  /* ---------- Forgetting demo ---------- */
  ;(function initForgettingDemo(){
    const compare = document.getElementById('forgetting-compare')
    if (!compare) return
    const leftChat  = compare.querySelector('[data-pane="forget"]')
    const rightChat = compare.querySelector('[data-pane="remember"]')
    const replayBtn = document.getElementById('replay-demo')
    const reduced   = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const delay = ms => new Promise(r => setTimeout(r, reduced ? Math.min(ms, 60) : ms))

    function clear() {
      leftChat.innerHTML = ''
      rightChat.innerHTML = ''
      if (replayBtn) replayBtn.classList.remove('visible')
    }

    function addMsg(chat, who, opts = {}) {
      const row = document.createElement('div')
      row.className = 'msg ' + (who === 'You' ? 'you' : 'ai')
      if (opts.id) row.dataset.id = opts.id
      row.innerHTML = '<span class="who">' + who + '</span><span class="body"></span>'
      chat.appendChild(row)
      chat.scrollTop = chat.scrollHeight
      return row
    }

    async function typeInto(row, text, speed = 14) {
      const body = row.querySelector('.body')
      const parts = text.split(/(<[^>]+>)/)
      row.classList.add('typing')
      for (const part of parts) {
        if (!part) continue
        if (part.startsWith('<')) { body.insertAdjacentHTML('beforeend', part); continue }
        for (const ch of part) {
          body.insertAdjacentText('beforeend', ch)
          if (!reduced) await delay(speed + (Math.random() < 0.08 ? 40 : 0))
        }
      }
      row.classList.remove('typing')
    }

    function addDivider(chat, text) {
      const d = document.createElement('div')
      d.className = 'divider-time'
      d.textContent = '— ' + text + ' —'
      chat.appendChild(d)
      return d
    }

    function addRetrieval(chat, callNumber, ms) {
      const row = document.createElement('div')
      row.className = 'retrieval'
      row.innerHTML =
        '<span class="who">mem</span>' +
        '<span class="l">retrieved &middot; <span class="r">' + callNumber + '</span></span>' +
        '<span>' + ms + '&nbsp;ms</span>'
      chat.appendChild(row)
      return row
    }

    function addStamp(chat, text, callNumber) {
      const el = document.createElement('div')
      el.className = 'stamp'
      el.innerHTML = '<span>— ' + text + '</span>' +
        (callNumber ? '<span class="call">' + callNumber + '</span>' : '')
      chat.appendChild(el)
      return el
    }

    function disintegrate(target) {
      return new Promise(resolve => {
        const parent = target.closest('.chat')
        if (!parent) { resolve(); return }
        const parentRect = parent.getBoundingClientRect()
        const style = getComputedStyle(target)
        const font = style.font ||
          (style.fontStyle + ' ' + style.fontWeight + ' ' + style.fontSize + '/' + style.lineHeight + ' ' + style.fontFamily)
        const color = style.color

        let overlay = parent.querySelector('.dust-overlay')
        if (!overlay) {
          overlay = document.createElement('div')
          overlay.className = 'dust-overlay'
          parent.appendChild(overlay)
        }

        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT)
        const range = document.createRange()
        const spans = []
        let node
        while ((node = walker.nextNode())) {
          const chars = node.textContent
          for (let i = 0; i < chars.length; i++) {
            if (chars[i] === ' ') continue
            range.setStart(node, i)
            range.setEnd(node, i + 1)
            const r = range.getBoundingClientRect()
            if (r.width === 0 || r.height === 0) continue
            const span = document.createElement('span')
            span.className = 'dust'
            span.textContent = chars[i]
            span.style.left = (r.left - parentRect.left) + 'px'
            span.style.top  = (r.top  - parentRect.top)  + 'px'
            span.style.width  = r.width  + 'px'
            span.style.height = r.height + 'px'
            span.style.font = font
            span.style.color = color
            span.style.opacity = '1'
            span.style.transform = 'translate(0,0)'
            span.style.transitionDuration = (1500 + Math.random() * 900) + 'ms'
            overlay.appendChild(span)
            spans.push(span)
          }
        }

        target.style.transition = 'color 0.35s ease, opacity 0.35s ease'
        target.style.color = 'transparent'

        void overlay.offsetHeight
        const cx = parentRect.width / 2
        spans.forEach((s) => {
          s.style.transitionDelay = (Math.random() * 500) + 'ms'
          const x0 = parseFloat(s.style.left)
          const dx = (x0 - cx) * 0.06 + (Math.random() - 0.5) * 36
          const dy = 30 + Math.random() * 80
          const rot = (Math.random() - 0.5) * 44
          s.style.transform = 'translate(' + dx + 'px,' + dy + 'px) rotate(' + rot + 'deg)'
          s.style.opacity = '0'
          s.style.filter = 'blur(2px)'
        })

        setTimeout(() => {
          spans.forEach(s => s.remove())
          resolve()
        }, reduced ? 200 : 2600)
      })
    }

    const NOAH_TEXT = "My son's name is Noah. He turns six on September 12th."

    async function runForget() {
      const you1 = addMsg(leftChat, 'You', { id: 'noah' })
      await delay(200)
      await typeInto(you1, NOAH_TEXT, 16)
      await delay(500)
      const ai1 = addMsg(leftChat, 'Model')
      await typeInto(ai1, "Noted. I'll remember that for next time we talk.", 14)
      await delay(900)
      addDivider(leftChat, 'two weeks later')
      await delay(700)
      const you2 = addMsg(leftChat, 'You')
      await typeInto(you2, "Help me plan Noah's birthday.", 18)
      await delay(700)
      const target = leftChat.querySelector('.msg[data-id="noah"] .body')
      if (target) await disintegrate(target)
      await delay(250)
      const ai2 = addMsg(leftChat, 'Model')
      await typeInto(ai2, "Of course. Who is Noah? How old is he turning?", 16)
      await delay(500)
      addStamp(leftChat, 'forgotten.')
    }

    async function runRemember() {
      const you1 = addMsg(rightChat, 'You', { id: 'noah' })
      await delay(200)
      await typeInto(you1, NOAH_TEXT, 16)
      await delay(500)
      const ai1 = addMsg(rightChat, 'Model')
      await typeInto(ai1, "Noted. Filed — <strong>W-042/R-01/D-003</strong>.", 14)
      await delay(900)
      addDivider(rightChat, 'two weeks later')
      await delay(700)
      const you2 = addMsg(rightChat, 'You')
      await typeInto(you2, "Help me plan Noah's birthday.", 18)
      await delay(600)
      addRetrieval(rightChat, 'W-042/R-01/D-003', 42)
      await delay(700)
      const ai2 = addMsg(rightChat, 'Model')
      await typeInto(ai2,
        "Of course — <strong>Noah</strong> turns <strong>six</strong> on <strong>September 12th</strong>. " +
        "You mentioned he loves the <strong>therizinosaurus</strong>, and a park on " +
        "<strong>Glebe Point Road</strong>. Shall we build from there?",
        11)
      await delay(500)
      addStamp(rightChat, 'remembered.', 'W-042/R-01/D-003')
    }

    let running = { forget: false, remember: false }
    let started = { forget: false, remember: false }

    async function runBoth() {
      if (running.forget || running.remember) return
      running.forget = running.remember = true
      started.forget = started.remember = true
      clear()
      await delay(200)
      await Promise.all([runForget(), runRemember()])
      running.forget = running.remember = false
      if (replayBtn) replayBtn.classList.add('visible')
    }

    async function runSide(side) {
      if (running[side] || started[side]) return
      running[side] = true
      started[side] = true
      const chat = side === 'forget' ? leftChat : rightChat
      chat.innerHTML = ''
      await delay(200)
      await (side === 'forget' ? runForget() : runRemember())
      running[side] = false
      if (started.forget && started.remember && !running.forget && !running.remember && replayBtn) {
        replayBtn.classList.add('visible')
      }
    }

    function resetAll() {
      started.forget = started.remember = false
      clear()
    }

    const stackedMQ = window.matchMedia('(max-width: 900px)')
    const isStacked = () => stackedMQ.matches

    function observeOnce(el, onReach) {
      if (!('IntersectionObserver' in window)) { onReach(); return null }
      let done = false
      const io = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (done || !entry.isIntersecting) return
          const rect = entry.boundingClientRect
          const elementCoverage  = entry.intersectionRatio
          const viewportCoverage = entry.intersectionRect.height / window.innerHeight
          const mostlyVisible  = elementCoverage >= 0.65
          const dominatesView  = viewportCoverage >= 0.60 && rect.top <= window.innerHeight * 0.15
          if (mostlyVisible || dominatesView) {
            done = true
            onReach()
            io.disconnect()
          }
        })
      }, {
        threshold: [0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0],
        rootMargin: '-8% 0px -8% 0px'
      })
      io.observe(el)
      return io
    }

    let observers = []
    function disconnectObservers() {
      observers.forEach(io => io && io.disconnect())
      observers = []
    }

    function armObservers() {
      disconnectObservers()
      if (isStacked()) {
        observers.push(observeOnce(compare.querySelector('.demo-forget'),   () => runSide('forget')))
        observers.push(observeOnce(compare.querySelector('.demo-remember'), () => runSide('remember')))
      } else {
        observers.push(observeOnce(compare, runBoth))
      }
    }

    if (replayBtn) replayBtn.addEventListener('click', () => {
      resetAll()
      armObservers()
    })

    armObservers()
  })()
})

onBeforeUnmount(() => {
  if (typeof document === 'undefined') return
  document.body.classList.remove('mempalace-active')
})
</script>

<template>
<div class="mempalace-landing">
<div class="page" v-pre>

  <!-- FOLIO — running head -->
  <header class="folio" role="banner">
    <div class="mark" aria-label="MemPalace">
      <img src="/mempalace_logo.png" alt="" aria-hidden="true" />
      <span>MemPalace</span>
    </div>
    <nav class="right" aria-label="Primary">
      <a href="#anatomy" class="hide-mobile">Anatomy</a>
      <a href="#dialect" class="hide-mobile">Dialect</a>
      <a href="#mechanics" class="hide-mobile">Mechanics</a>
      <a href="#install" class="hide-mobile">Install</a>
      <a href="/guide/getting-started">Docs</a>
      <a href="https://github.com/MemPalace/mempalace">GitHub ↗</a>
    </nav>
  </header>

  <!-- HERO -->
  <section class="hero" id="hero">
    <span class="corner-ticks" aria-hidden="true"><span></span></span>

    <div class="hero-copy">
      <h1 class="display">
        <span class="line">Memory is</span>
        <span class="line line-2">identity.</span>
      </h1>
      <p class="lede">
        An AI that forgets cannot know you. MemPalace keeps every word you have
        shared — verbatim, on your machine, forever available. One hundred
        percent recall by design.
      </p>
      <form class="waitlist waitlist-hero" data-source="hero" novalidate>
        <div class="waitlist-head">
          <span class="waitlist-pulse" aria-hidden="true"></span>
          <span class="waitlist-eyebrow">Subscribe for updates</span>
        </div>
        <div class="waitlist-row">
          <input
            type="email"
            class="waitlist-input"
            name="email"
            placeholder="you@example.com"
            autocomplete="email"
            aria-label="Email address"
            required
          />
          <button type="submit" class="waitlist-submit">
            <span class="waitlist-label-default">Join the list</span>
            <span class="waitlist-label-pending" aria-hidden="true">Joining…</span>
            <svg class="waitlist-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M5 12h14M13 6l6 6-6 6"/>
            </svg>
            <svg class="waitlist-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <path d="M5 12l5 5 9-11"/>
            </svg>
          </button>
        </div>
        <p class="waitlist-msg" aria-live="polite"></p>
      </form>

      <div class="hero-secondary">
        <a href="/guide/getting-started">Read the docs</a>
        <span class="sep" aria-hidden="true">·</span>
        <a href="https://github.com/MemPalace/mempalace">GitHub ↗</a>
      </div>

    </div>

    <!-- Palace video visual -->
    <div class="palace-stage" aria-hidden="true">
      <div class="halo"></div>

      <div class="stars">
        <i style="top:12%; left:22%;  --t:5s;   --d:0.0s"></i>
        <i style="top:18%; left:74%;  --t:6s;   --d:1.2s"></i>
        <i style="top:34%; left:8%;   --t:4s;   --d:0.6s"></i>
        <i style="top:44%; left:88%;  --t:7s;   --d:0.3s"></i>
        <i style="top:62%; left:14%;  --t:5.5s; --d:1.8s"></i>
        <i style="top:72%; left:82%;  --t:4.5s; --d:0.9s"></i>
        <i style="top:82%; left:38%;  --t:6.2s; --d:2.4s"></i>
        <i style="top:28%; left:52%;  --t:5.2s; --d:3.0s"></i>
        <i style="top:88%; left:60%;  --t:4.8s; --d:1.5s"></i>
        <i style="top:6%;  left:48%;  --t:6.8s; --d:0.4s"></i>
      </div>

      <video
        class="palace-video"
        src="/hero_video.mp4"
        autoplay
        muted
        loop
        playsinline
        disablepictureinpicture
      ></video>
    </div>
  </section>

  <!-- THE FORGETTING -->
  <section id="forgetting" class="forgetting">
    <div class="section-mark"><span class="roman">i</span> <span>the forgetting</span></div>

    <header class="forgetting-head">
      <div class="copy">
        <span class="eyebrow">before &middot; after</span>
        <h2 class="display">
          The same conversation, <em>twice.</em>
        </h2>
        <p class="lede" style="margin:0;">
          Scroll down and watch. On the left, a model without memory. On the right,
          the same model with MemPalace. The words are identical — until two weeks
          pass.
        </p>
      </div>
      <button class="replay" id="replay-demo" type="button" aria-label="Replay the demo">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 4v6h6"/><path d="M20 20v-6h-6"/><path d="M4 10a8 8 0 0114-5l2 3"/><path d="M20 14a8 8 0 01-14 5l-2-3"/></svg>
        replay
      </button>
    </header>

    <div class="forgetting-compare" id="forgetting-compare" aria-label="Comparison demo">
      <article class="demo-pane demo-forget">
        <header>
          <span class="pane-tag">without mempalace</span>
          <span class="pane-meta">session <em>resets</em> &middot; no recall</span>
        </header>
        <div class="chat" data-pane="forget" aria-live="polite"></div>
      </article>

      <div class="divider" aria-hidden="true"></div>

      <article class="demo-pane demo-remember">
        <header>
          <span class="pane-tag">with mempalace</span>
          <span class="pane-meta">verbatim &middot; retrieved &lt;<em>50&nbsp;ms</em></span>
        </header>
        <div class="chat" data-pane="remember" aria-live="polite"></div>
      </article>
    </div>
  </section>

  <!-- ANATOMY OF A PALACE -->
  <section id="anatomy" class="anatomy">
    <div class="section-mark"><span class="roman">ii</span> <span>anatomy of a palace</span></div>

    <div class="anatomy-head">
      <div>
        <span class="eyebrow">the method of loci, updated</span>
        <h2 class="display">
          Wings. Rooms. <em>Drawers.</em>
        </h2>
      </div>
      <p class="lede">
        A two-thousand-year-old memory technique, reworked for a machine.
        Broad categories nest time-based groupings; time-based groupings hold
        verbatim drawers. A symbolic index lets the model scan thousands of
        drawers in a single breath and open only the ones it needs.
      </p>
    </div>

    <div class="anatomy-diagram">
      <article class="stratum">
        <span class="n">W — wing</span>
        <h3>The <em>Wing</em></h3>
        <p class="sub">people · projects · topics</p>
        <p>A broad region of the palace, keyed to a real entity — a person by name, a project by codename, a domain of your life. Entity-first, always.</p>
        <div class="diagram">
          <svg viewBox="0 0 200 80" fill="none" stroke="currentColor" stroke-width="1" style="color:var(--prism);">
            <rect x="5" y="20" width="190" height="50" opacity="0.4"/>
            <rect x="15" y="28" width="50" height="34" />
            <rect x="75" y="28" width="50" height="34" />
            <rect x="135" y="28" width="50" height="34" />
            <line x1="5" y1="12" x2="195" y2="12" stroke-dasharray="2 3" opacity="0.5"/>
          </svg>
        </div>
      </article>

      <article class="stratum">
        <span class="n">R — room</span>
        <h3>The <em>Room</em></h3>
        <p class="sub">days · sessions · threads</p>
        <p>Inside a wing sit rooms — discrete units of time. One room per day, or one per session. Walk the corridor and the palace unfolds chronologically, room by room.</p>
        <div class="diagram">
          <svg viewBox="0 0 200 80" fill="none" stroke="currentColor" stroke-width="1" style="color:var(--prism);">
            <rect x="10" y="20" width="36" height="44" />
            <rect x="56" y="20" width="36" height="44" />
            <rect x="102" y="20" width="36" height="44" />
            <rect x="148" y="20" width="36" height="44" />
            <line x1="10" y1="70" x2="184" y2="70" stroke-dasharray="1 3" opacity="0.6"/>
          </svg>
        </div>
      </article>

      <article class="stratum">
        <span class="n">D — drawer</span>
        <h3>The <em>Drawer</em></h3>
        <p class="sub">verbatim · permanent · exact</p>
        <p>Each room holds drawers. A drawer is a single chunk of verbatim content — the exact words, untouched. The palace's promise is kept here.</p>
        <div class="diagram">
          <svg viewBox="0 0 200 80" fill="none" stroke="currentColor" stroke-width="1" style="color:var(--prism);">
            <rect x="40" y="14" width="120" height="16" />
            <rect x="40" y="34" width="120" height="16" />
            <rect x="40" y="54" width="120" height="16" />
            <circle cx="150" cy="22" r="1.5" fill="currentColor"/>
            <circle cx="150" cy="42" r="1.5" fill="currentColor"/>
            <circle cx="150" cy="62" r="1.5" fill="currentColor"/>
          </svg>
        </div>
      </article>
    </div>
  </section>

  <!-- DIALECT -->
  <section id="dialect" class="dialect">
    <div class="section-mark"><span class="roman">iii</span> <span>the aaak dialect</span></div>

    <div class="dialect-head">
      <span class="eyebrow">index &larr; verbatim</span>
      <h2 class="display">
        A compressed symbolic language <em>for finding</em>, not remembering.
      </h2>
      <p class="lede">
        The content stays verbatim — always. The <em>index</em> above it is written
        in AAAK: a dense symbolic dialect an LLM can scan at a glance. Tens of
        thousands of entries, one pass, exact drawer located.
      </p>
    </div>

    <div class="dialect-grid">
      <article class="slab">
        <header class="card-head">
          <span class="l">drawer · D-007</span>
          <span>verbatim · exact · permanent</span>
        </header>
        <p class="label">The drawer, as stored.</p>
        <p>
          "My son's name is <strong>Noah</strong>. He turns <strong>six</strong>
          on <strong>September 12th</strong>. He loves dinosaurs —
          especially the <strong>therizinosaurus</strong> because of the
          claws. We want to do a small party at <strong>the park on Glebe
          Point Road</strong>, maybe eight kids."
        </p>
        <p style="color:var(--ice-ghost); font-size: 13.5px; font-family: var(--f-mono); letter-spacing: 0.05em; margin-top:1.5rem;">
          &mdash; kept as spoken. never rewritten.
        </p>
      </article>

      <div class="dialect-arrow" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3">
          <path d="M12 3v18M7 8l5-5 5 5M7 16l5 5 5-5"/>
        </svg>
        <span>index · AAAK</span>
      </div>

      <article class="slab mono">
        <header class="card-head">
          <span class="l">index · AAAK</span>
          <span>indexes · compressed · addressable</span>
        </header>
        <p class="label">The pointer, as indexed.</p>
<pre><span class="c">§ W-042/R-11/D-007</span>
<span class="k">@p</span> <span class="t">noah</span>~<span class="v">son.age=6</span>~<span class="v">dob=09-12</span>
<span class="k">@l</span> <span class="t">glebe-pt-rd.park</span>
<span class="k">@e</span> <span class="t">birthday</span>~<span class="v">party(n≈8)</span>
<span class="k">@i</span> <span class="t">therizinosaurus</span>~<span class="v">claws</span>
<span class="k">@t</span> <span class="v">2026-04-14T09:41</span>
<span class="c">§ ptr → D-007 (verbatim)</span></pre>
      </article>
    </div>

    <p class="dialect-caption">
      Ninety-plus percent compression on the pointer layer. One hundred percent
      fidelity on the content layer. You get speed without ever losing a word.
    </p>
  </section>

  <!-- MECHANICS -->
  <section id="mechanics">
    <div class="section-mark"><span class="roman">iv</span> <span>how it works</span></div>

    <div class="mechanics-head">
      <span class="eyebrow">mechanism · architecture</span>
      <h2 class="display">
        Four pieces. <em>No cloud.</em> No keys.
      </h2>
    </div>

    <div class="mechanics">
      <article class="mech">
        <div class="icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.3">
            <rect x="8" y="10" width="32" height="22" rx="1"/>
            <path d="M8 16h32"/>
            <path d="M14 24h20M14 28h12"/>
            <path d="M16 38h16M20 32v6M28 32v6"/>
          </svg>
        </div>
        <span class="eyebrow no-rule"><span class="n">— 01</span></span>
        <h3>Local-<em>first</em></h3>
        <p>ChromaDB on disk. SQLite for the knowledge graph. Nothing is uploaded. Nothing is synced. Your palace lives under a single directory on your machine.</p>
        <div class="metric">path · <b>~/.mempalace</b></div>
      </article>

      <article class="mech">
        <div class="icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.3">
            <circle cx="24" cy="24" r="14"/>
            <path d="M16 24h16M24 16v16"/>
            <path d="M10 10l28 28" stroke-width="1.5"/>
          </svg>
        </div>
        <span class="eyebrow no-rule"><span class="n">— 02</span></span>
        <h3>Zero <em>API</em></h3>
        <p>Extraction, chunking, and embedding all run locally. No OpenAI key, no Anthropic key, no sentence-transformers endpoint. The memory works even offline, on a plane.</p>
        <div class="metric">keys required · <b>none</b></div>
      </article>

      <article class="mech">
        <div class="icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.3">
            <path d="M8 36V18l8-8h16l8 8v18"/>
            <path d="M8 36h32"/>
            <circle cx="24" cy="26" r="4"/>
            <path d="M24 22v-4M24 30v4M20 26h-4M28 26h4"/>
          </svg>
        </div>
        <span class="eyebrow no-rule"><span class="n">— 03</span></span>
        <h3>Background <em>hooks</em></h3>
        <p>Filing and indexing happen silently through Claude Code hooks. On session end, on pre-compaction. You write. The palace fills itself behind the curtain.</p>
        <div class="metric">hook budget · <b>&lt;500 ms</b></div>
      </article>

      <article class="mech">
        <div class="icon" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.3">
            <circle cx="10" cy="12" r="3"/>
            <circle cx="38" cy="10" r="3"/>
            <circle cx="24" cy="26" r="3"/>
            <circle cx="12" cy="38" r="3"/>
            <circle cx="38" cy="36" r="3"/>
            <path d="M12 14l10 10M36 12L26 24M14 36l8-8M36 34l-10-6" opacity="0.6"/>
          </svg>
        </div>
        <span class="eyebrow no-rule"><span class="n">— 04</span></span>
        <h3>Temporal <em>graph</em></h3>
        <p>Relationships across entities with valid-from and valid-to dates. Who worked on what. When did this change. Facts that were true then, and may not be now.</p>
        <div class="metric">store · <b>sqlite</b></div>
      </article>
    </div>
  </section>

  <!-- INSTALL -->
  <section id="install" class="install">
    <div class="section-mark" style="left:50%; transform:translateX(-50%);"><span class="roman">v</span> <span>begin</span></div>
    <span class="eyebrow" style="justify-content:center;">open a drawer</span>
    <h2 class="display">
      Build your <em>palace.</em>
    </h2>
    <p class="lede" style="margin-left:auto;margin-right:auto;text-align:center;">
      One command to install. One to initialize. Your words — yours, permanent,
      instantly recallable — from that moment on.
    </p>

    <div class="terminal" role="figure" aria-label="Installation commands">
      <div class="terminal-head">
        <span class="lights"><i></i><i></i><i></i></span>
        <span>~/mempalace &middot; bash</span>
      </div>
<pre><span class="prompt">$</span> pip install -e <span class="dim">".[dev]"</span>
<span class="c">Successfully installed mempalace</span>
<span class="prompt">$</span> mempalace init
<span class="ok">  ✓</span> palace created at <span class="dim">~/.mempalace</span>
<span class="ok">  ✓</span> hooks registered <span class="dim">(stop, precompact)</span>
<span class="ok">  ✓</span> knowledge graph initialized
<span class="prompt">$</span> mempalace remember <span class="dim">"memory is identity."</span>
<span class="ok">  ✓</span> filed · <span class="c">W-001/R-01/D-001</span></pre>
    </div>

    <div class="install-cta">
      <a href="/guide/getting-started" class="btn btn-primary">
        Read the docs
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </a>
      <a href="https://github.com/MemPalace/mempalace" class="btn">
        Visit the repository
      </a>
    </div>
  </section>

  <!-- FOOTER -->
  <footer class="catalog">
    <form class="waitlist waitlist-footer" data-source="footer" novalidate>
      <div class="waitlist-head">
        <span class="waitlist-pulse" aria-hidden="true"></span>
        <span class="waitlist-eyebrow">Last call &middot; subscribe for updates</span>
      </div>
      <div class="waitlist-row">
        <input type="email" class="waitlist-input" name="email" placeholder="you@example.com" autocomplete="email" aria-label="Email address" required />
        <button type="submit" class="waitlist-submit">
          <span class="waitlist-label-default">Join the list</span>
          <span class="waitlist-label-pending" aria-hidden="true">Joining…</span>
          <svg class="waitlist-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          <svg class="waitlist-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 12l5 5 9-11"/></svg>
        </button>
      </div>
      <p class="waitlist-msg" aria-live="polite"></p>
    </form>

    <div class="catalog-card">
      <div>
        <p class="catalog-title">MemPalace <em>&mdash;</em> a memory palace for AI.</p>
        <p class="catalog-desc">Verbatim storage, local-first, zero telemetry. Built for people who believe their words are theirs.</p>
      </div>
      <div>
        <h4>Documentation</h4>
        <ul>
          <li><a href="/guide/getting-started">Getting started</a></li>
          <li><a href="/concepts/the-palace">The palace</a></li>
          <li><a href="/reference/cli">CLI reference</a></li>
          <li><a href="/reference/benchmarks">Benchmarks</a></li>
        </ul>
      </div>
      <div>
        <h4>The project</h4>
        <ul>
          <li><a href="https://github.com/MemPalace/mempalace">GitHub</a></li>
          <li><a href="https://github.com/MemPalace/mempalace/blob/main/README.md">Readme</a></li>
          <li><a href="https://github.com/MemPalace/mempalace/blob/main/ROADMAP.md">Roadmap</a></li>
          <li><a href="https://github.com/MemPalace/mempalace/blob/main/CHANGELOG.md">Changelog</a></li>
        </ul>
      </div>
    </div>
  </footer>

</div>
</div>
</template>

<style>
/* ==========================================================
   MEMPALACE — THE CRYSTALLINE PALACE
   Styles live behind .mempalace-landing so they don't leak
   onto the docs pages.
   ========================================================== */

/* When the landing component is mounted, hide VitePress chrome so our
   own folio header is the only one showing. The class is toggled
   via onMounted/onBeforeUnmount and does not affect other pages. */
body.mempalace-active .VPNav,
body.mempalace-active .VPLocalNav,
body.mempalace-active .VPFooter { display: none !important; }
body.mempalace-active .VPContent {
  padding: 0 !important;
  margin: 0 !important;
  max-width: none !important;
}
body.mempalace-active .VPPage,
body.mempalace-active .VPDoc {
  padding: 0 !important;
  margin: 0 !important;
  max-width: none !important;
}
body.mempalace-active { overflow-x: hidden; }

.mempalace-landing {
  --void:        #05070A;
  --obsidian:    #0A0D12;
  --obsidian-2:  #11151C;
  --ink:         #181D26;
  --hair:        rgba(158, 216, 255, 0.14);
  --hair-strong: rgba(158, 216, 255, 0.28);
  --ice:         #EAF4FF;
  --ice-dim:     #B8C7D9;
  --ice-ghost:   rgba(234, 244, 255, 0.56);
  --prism:       #9ED8FF;
  --prism-core:  #4AA3FF;
  --refract:     #A8B5FF;
  --stellar:     #F3E7B0;
  --ember:       #E28A6B;

  --f-display: "Cormorant Garamond", "Times New Roman", serif;
  --f-body:    "Geist", ui-sans-serif, system-ui, sans-serif;
  --f-mono:    "JetBrains Mono", ui-monospace, monospace;

  --measure: 68ch;
  --gutter: clamp(1.25rem, 3vw, 2.5rem);
  --rule: 1px;

  background: var(--void);
  color: var(--ice);
  font-family: var(--f-body);
  font-weight: 300;
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  overflow-x: hidden;
  min-height: 100vh;
  position: relative;
}
.mempalace-landing * { box-sizing: border-box; }
.mempalace-landing ::selection { background: var(--prism-core); color: var(--void); }

.mempalace-landing::before {
  content: "";
  position: fixed; inset: 0;
  pointer-events: none;
  background:
    radial-gradient(80% 60% at 50% -10%, rgba(74,163,255,0.18), transparent 60%),
    radial-gradient(40% 40% at 85% 20%, rgba(168,181,255,0.08), transparent 70%),
    radial-gradient(50% 50% at 15% 80%, rgba(158,216,255,0.06), transparent 70%);
  z-index: 0;
}
.mempalace-landing::after {
  content: "";
  position: fixed; inset: 0;
  pointer-events: none;
  z-index: 1;
  opacity: 0.35;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.62 0 0 0 0 0.85 0 0 0 0 1 0 0 0 0.07 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
}

.mempalace-landing .page { position: relative; z-index: 2; padding-top: 54px; }

.mempalace-landing main,
.mempalace-landing header,
.mempalace-landing footer { position: relative; }

/* Folio */
.mempalace-landing .folio {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 40;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 2rem;
  padding: 14px var(--gutter);
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ice-ghost);
  background: linear-gradient(to bottom, rgba(5,7,10,0.92), rgba(5,7,10,0.72) 70%, rgba(5,7,10,0.4));
  backdrop-filter: blur(10px) saturate(140%);
  -webkit-backdrop-filter: blur(10px) saturate(140%);
  border-bottom: var(--rule) solid var(--hair);
}
.mempalace-landing .folio .right { display: flex; gap: 1.5rem; align-items: center; }
.mempalace-landing .folio .mark {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  color: var(--ice);
}
.mempalace-landing .folio .mark img {
  width: 22px; height: 22px;
  object-fit: contain;
  filter: drop-shadow(0 0 8px rgba(74,163,255,0.45));
}
.mempalace-landing .folio a {
  color: var(--ice-ghost);
  text-decoration: none;
  transition: color 0.25s ease;
}
.mempalace-landing .folio a:hover { color: var(--prism); }

/* Typography helpers */
.mempalace-landing .eyebrow {
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--prism);
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
}
.mempalace-landing .eyebrow::before {
  content: "";
  display: inline-block;
  width: 36px; height: 1px;
  background: var(--prism);
  opacity: 0.6;
}
.mempalace-landing .eyebrow.no-rule::before { display: none; }
.mempalace-landing .display {
  font-family: var(--f-display);
  font-weight: 400;
  letter-spacing: -0.01em;
  line-height: 0.95;
  color: var(--ice);
}
.mempalace-landing .display em { font-style: italic; color: var(--prism); }
.mempalace-landing .lede {
  font-family: var(--f-display);
  font-style: italic;
  font-weight: 300;
  color: var(--ice-dim);
  font-size: clamp(1.2rem, 1.8vw, 1.55rem);
  line-height: 1.45;
  max-width: 46ch;
}
.mempalace-landing section {
  position: relative;
  padding: clamp(4.5rem, 9vw, 8rem) var(--gutter);
}
.mempalace-landing section + section { border-top: var(--rule) solid var(--hair); }

.mempalace-landing .section-mark {
  position: absolute;
  top: clamp(1.5rem, 3vw, 2.5rem);
  left: var(--gutter);
  display: flex;
  align-items: center;
  gap: 1rem;
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--ice-ghost);
}
.mempalace-landing .section-mark .roman {
  font-family: var(--f-display);
  font-style: italic;
  font-size: 1.1rem;
  color: var(--prism);
  letter-spacing: 0;
}

.mempalace-landing .corner-ticks {
  position: absolute;
  inset: clamp(1rem, 2vw, 2rem);
  pointer-events: none;
  z-index: 0;
}
.mempalace-landing .corner-ticks::before,
.mempalace-landing .corner-ticks::after,
.mempalace-landing .corner-ticks > span::before,
.mempalace-landing .corner-ticks > span::after {
  content: "";
  position: absolute;
  width: 14px; height: 14px;
  border: var(--rule) solid var(--hair-strong);
}
.mempalace-landing .corner-ticks::before { top: 0; left: 0; border-right: 0; border-bottom: 0; }
.mempalace-landing .corner-ticks::after  { top: 0; right: 0; border-left: 0; border-bottom: 0; }
.mempalace-landing .corner-ticks > span::before { bottom: 0; left: 0; border-right: 0; border-top: 0; }
.mempalace-landing .corner-ticks > span::after  { bottom: 0; right: 0; border-left: 0; border-top: 0; }

/* Hero */
.mempalace-landing .hero {
  min-height: calc(100vh - 54px);
  max-height: 900px;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: clamp(2rem, 4vw, 4rem);
  align-items: center;
  padding-top: clamp(2rem, 4vw, 3.5rem);
  padding-bottom: clamp(2rem, 4vw, 3.5rem);
  overflow: hidden;
}
.mempalace-landing .hero-copy { position: relative; z-index: 3; }
.mempalace-landing .hero h1 {
  font-size: clamp(2.5rem, 6vw, 5.25rem);
  margin: 0 0 1.25rem;
}
.mempalace-landing .hero h1 .line { display: block; }
.mempalace-landing .hero h1 .line-2 { font-style: italic; color: var(--prism); font-weight: 300; }
.mempalace-landing .hero .lede { margin-bottom: 0; }
.mempalace-landing .hero-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-top: 2rem;
  align-items: center;
}

/* --- Waitlist form --- */
.mempalace-landing .waitlist {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 1rem 1.25rem 0.9rem;
  margin-top: 1.5rem;
  max-width: 560px;
  border: var(--rule) solid var(--hair-strong);
  background:
    linear-gradient(180deg, rgba(74,163,255,0.14), rgba(10,13,18,0.55)),
    var(--obsidian);
  box-shadow:
    inset 0 0 0 1px rgba(158,216,255,0.12),
    0 30px 70px -30px rgba(74,163,255,0.55),
    0 0 60px -30px rgba(74,163,255,0.4);
  isolation: isolate;
}
.mempalace-landing .waitlist::before,
.mempalace-landing .waitlist::after {
  content: "";
  position: absolute;
  width: 10px; height: 10px;
  border: var(--rule) solid var(--prism);
  opacity: 0.7;
  pointer-events: none;
}
.mempalace-landing .waitlist::before { top: -1px; left: -1px; border-right: 0; border-bottom: 0; }
.mempalace-landing .waitlist::after  { bottom: -1px; right: -1px; border-left: 0; border-top: 0; }

.mempalace-landing .waitlist-head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
}
.mempalace-landing .waitlist-pulse {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--prism);
  box-shadow: 0 0 10px var(--prism-core), 0 0 20px var(--prism-core);
  animation: mpl-breathe 2.2s ease-in-out infinite;
  flex-shrink: 0;
}
.mempalace-landing .waitlist-eyebrow { color: var(--prism); }
.mempalace-landing .waitlist-meta {
  margin-left: auto;
  color: var(--ice-ghost);
  font-size: 9.5px;
  letter-spacing: 0.18em;
}

.mempalace-landing .waitlist-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.55rem;
  align-items: stretch;
}
.mempalace-landing .waitlist-input {
  background: rgba(5,7,10,0.7);
  border: var(--rule) solid var(--hair-strong);
  padding: 0.75rem 0.9rem;
  color: var(--ice);
  font-family: var(--f-mono);
  font-size: 14px;
  letter-spacing: 0.02em;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
  min-width: 0;
  width: 100%;
}
.mempalace-landing .waitlist-input::placeholder { color: var(--ice-ghost); }
.mempalace-landing .waitlist-input:hover { border-color: var(--prism); }
.mempalace-landing .waitlist-input:focus {
  outline: none;
  border-color: var(--prism);
  box-shadow: 0 0 0 3px rgba(74,163,255,0.2);
  background: rgba(10,13,18,0.9);
}
.mempalace-landing .waitlist-input:disabled { opacity: 0.6; cursor: not-allowed; }

.mempalace-landing .waitlist-submit {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.75rem 1.1rem;
  border: var(--rule) solid var(--prism);
  background: rgba(158,216,255,0.14);
  color: var(--prism);
  font-family: var(--f-mono);
  font-size: 11.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.25s, color 0.25s, box-shadow 0.25s, transform 0.25s;
  white-space: nowrap;
  box-shadow: inset 0 0 0 1px rgba(158,216,255,0.15),
              0 10px 40px -20px rgba(74,163,255,0.55);
}
.mempalace-landing .waitlist-submit:hover:not(:disabled) {
  background: rgba(158,216,255,0.22);
  color: var(--ice);
  transform: translateY(-1px);
}
.mempalace-landing .waitlist-submit:disabled { opacity: 0.6; cursor: not-allowed; }
.mempalace-landing .waitlist-submit svg { width: 14px; height: 14px; }
.mempalace-landing .waitlist-submit .waitlist-label-pending,
.mempalace-landing .waitlist-submit .waitlist-check { display: none; }

.mempalace-landing .waitlist.is-pending .waitlist-submit .waitlist-label-default,
.mempalace-landing .waitlist.is-pending .waitlist-submit .waitlist-arrow { display: none; }
.mempalace-landing .waitlist.is-pending .waitlist-submit .waitlist-label-pending { display: inline; }

.mempalace-landing .waitlist.is-success .waitlist-submit .waitlist-label-default,
.mempalace-landing .waitlist.is-success .waitlist-submit .waitlist-label-pending,
.mempalace-landing .waitlist.is-success .waitlist-submit .waitlist-arrow { display: none; }
.mempalace-landing .waitlist.is-success .waitlist-submit .waitlist-check { display: inline; }
.mempalace-landing .waitlist.is-success .waitlist-submit {
  background: rgba(158,216,255,0.28);
  color: var(--ice);
}
.mempalace-landing .waitlist.is-success .waitlist-input { border-color: var(--prism); }

.mempalace-landing .waitlist-msg {
  margin: 0;
  min-height: 1.1em;
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ice-ghost);
  transition: color 0.2s;
}
.mempalace-landing .waitlist.is-success .waitlist-msg {
  color: var(--prism);
  font-family: var(--f-display);
  font-style: italic;
  font-size: 1rem;
  letter-spacing: 0;
}
.mempalace-landing .waitlist.is-error .waitlist-msg { color: var(--ember); }

/* Secondary hero links (shown below the waitlist form) */
.mempalace-landing .hero-secondary {
  margin-top: 1rem;
  display: flex;
  gap: 0.9rem;
  align-items: center;
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ice-ghost);
}
.mempalace-landing .hero-secondary a {
  color: var(--ice-ghost);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  padding-bottom: 2px;
  transition: color 0.2s, border-color 0.2s;
}
.mempalace-landing .hero-secondary a:hover { color: var(--prism); border-color: var(--prism); }
.mempalace-landing .hero-secondary .sep { opacity: 0.5; }

/* Footer variant */
.mempalace-landing .waitlist-footer {
  max-width: 760px;
  margin: 0 auto clamp(2rem, 4vw, 3rem);
}

/* Buttons */
.mempalace-landing .btn {
  --bg: transparent;
  --fg: var(--ice);
  --bd: var(--hair-strong);
  display: inline-flex;
  align-items: center;
  gap: 0.8rem;
  padding: 0.95rem 1.4rem;
  border: var(--rule) solid var(--bd);
  background: var(--bg);
  color: var(--fg);
  text-decoration: none;
  font-family: var(--f-mono);
  font-size: 12px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, color 0.3s ease, transform 0.3s ease;
  position: relative;
  overflow: hidden;
}
.mempalace-landing .btn::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(120% 60% at 50% 120%, rgba(74,163,255,0.35), transparent 70%);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}
.mempalace-landing .btn:hover { border-color: var(--prism); color: var(--ice); }
.mempalace-landing .btn:hover::after { opacity: 1; }
.mempalace-landing .btn svg { width: 14px; height: 14px; }
.mempalace-landing .btn-primary {
  --bg: rgba(158,216,255,0.08);
  --bd: var(--prism);
  color: var(--prism);
  box-shadow: inset 0 0 0 1px rgba(158,216,255,0.2),
              0 0 0 1px rgba(74,163,255,0.15),
              0 20px 60px -20px rgba(74,163,255,0.35);
}
.mempalace-landing .btn-primary:hover { background: rgba(158,216,255,0.14); color: var(--ice); }

.mempalace-landing .hero-stats {
  margin-top: 2.25rem;
  display: grid;
  grid-template-columns: repeat(3, auto);
  gap: clamp(1.5rem, 4vw, 3rem);
  padding-top: 1.4rem;
  border-top: var(--rule) solid var(--hair);
  max-width: 560px;
}
.mempalace-landing .hero-stats dt {
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--ice-ghost);
  margin-bottom: 0.4rem;
}
.mempalace-landing .hero-stats dd {
  margin: 0;
  font-family: var(--f-display);
  font-size: clamp(1.25rem, 2.2vw, 1.75rem);
  color: var(--ice);
  letter-spacing: -0.01em;
}
.mempalace-landing .hero-stats dd em { font-style: italic; color: var(--prism); }

/* Palace visual */
.mempalace-landing .palace-stage {
  position: relative;
  aspect-ratio: 1 / 1.05;
  width: 100%;
  max-width: 640px;
  justify-self: end;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mempalace-landing .palace-stage .halo {
  position: absolute;
  inset: -12% -8% -5% -12%;
  background: radial-gradient(50% 45% at 50% 55%, rgba(74,163,255,0.35), transparent 70%);
  filter: blur(30px);
  opacity: 0.6;
  animation: mpl-haloPulse 7s ease-in-out infinite;
  z-index: 0;
}
@keyframes mpl-haloPulse {
  0%, 100% { opacity: 0.45; transform: scale(1); }
  50%      { opacity: 0.75;  transform: scale(1.06); }
}
.mempalace-landing .palace-stage .palace-video {
  position: relative;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;

  --mask-left: linear-gradient(to right, transparent 0%, black 25%);
  --mask-right: linear-gradient(to left, transparent 0%, black 25%);
  --mask-top: linear-gradient(to bottom, transparent 0%, black 15%);
  --mask-bottom: linear-gradient(to top, transparent 0%, black 15%);

  -webkit-mask-image: var(--mask-left), var(--mask-right), var(--mask-top), var(--mask-bottom);
  -webkit-mask-composite: source-in;
  mask-image: var(--mask-left), var(--mask-right), var(--mask-top), var(--mask-bottom);
  mask-composite: intersect;
}
.mempalace-landing .palace-stage .stars { position: absolute; inset: 0; z-index: 1; pointer-events: none; }
.mempalace-landing .palace-stage .stars i {
  position: absolute;
  width: 2px; height: 2px;
  background: var(--ice);
  border-radius: 50%;
  opacity: 0;
  box-shadow: 0 0 6px rgba(234,244,255,0.8);
  animation: mpl-twinkle var(--t, 5s) ease-in-out infinite;
  animation-delay: var(--d, 0s);
}
@keyframes mpl-twinkle {
  0%, 100% { opacity: 0; transform: scale(0.6); }
  50%      { opacity: 0.9; transform: scale(1); }
}

/* Forgetting */
.mempalace-landing .forgetting {
  display: flex;
  flex-direction: column;
  gap: clamp(2.5rem, 5vw, 4rem);
}
.mempalace-landing .forgetting-head {
  max-width: 820px;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 2rem;
}
.mempalace-landing .forgetting-head .copy { max-width: 62ch; }
.mempalace-landing .forgetting-head h2 {
  font-size: clamp(2rem, 4.5vw, 3.6rem);
  margin: 1rem 0 1.25rem;
}
.mempalace-landing .forgetting-head .replay {
  background: none;
  border: var(--rule) solid var(--hair-strong);
  color: var(--ice-ghost);
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s, color 0.2s, border-color 0.2s;
  display: inline-flex; align-items: center; gap: 0.5rem;
  white-space: nowrap;
}
.mempalace-landing .forgetting-head .replay.visible { opacity: 1; pointer-events: auto; }
.mempalace-landing .forgetting-head .replay:hover { color: var(--prism); border-color: var(--prism); }
.mempalace-landing .forgetting-head .replay svg { width: 11px; height: 11px; }
.mempalace-landing .forgetting-compare {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr);
  gap: 0;
  border: var(--rule) solid var(--hair-strong);
  background: linear-gradient(180deg, rgba(17,21,28,0.65), rgba(10,13,18,0.35));
  min-height: 540px;
  position: relative;
  overflow: hidden;
}
.mempalace-landing .forgetting-compare .divider {
  background: linear-gradient(180deg, transparent, var(--hair-strong) 20%, var(--hair-strong) 80%, transparent);
  position: relative;
}
.mempalace-landing .forgetting-compare .divider::before {
  content: "vs";
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-family: var(--f-display);
  font-style: italic;
  font-size: 14px;
  color: var(--ice-ghost);
  background: var(--void);
  padding: 6px 10px;
  border: var(--rule) solid var(--hair-strong);
  border-radius: 50%;
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  box-sizing: border-box;
}
.mempalace-landing .demo-pane {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 1.25rem 1.5rem 1.75rem;
  min-height: 540px;
}
.mempalace-landing .demo-pane > header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 0.9rem;
  margin-bottom: 1.25rem;
  border-bottom: var(--rule) solid var(--hair);
  gap: 1rem;
}
.mempalace-landing .demo-pane .pane-tag {
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: var(--ice);
  display: inline-flex; align-items: center; gap: 0.6rem;
}
.mempalace-landing .demo-pane.demo-forget .pane-tag::before {
  content: "";
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ember);
  box-shadow: 0 0 6px var(--ember);
}
.mempalace-landing .demo-pane.demo-remember .pane-tag::before {
  content: "";
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--prism);
  box-shadow: 0 0 6px var(--prism-core);
}
.mempalace-landing .demo-pane .pane-meta {
  font-family: var(--f-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--ice-ghost);
  text-align: right;
}
.mempalace-landing .demo-pane.demo-forget .pane-meta em    { color: var(--ember); font-style: normal; }
.mempalace-landing .demo-pane.demo-remember .pane-meta em  { color: var(--prism); font-style: normal; }
.mempalace-landing .chat {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
  position: relative;
  overflow: hidden;
  min-height: 380px;
}
.mempalace-landing .msg {
  display: flex;
  gap: 0.85rem;
  font-size: 14.5px;
  line-height: 1.55;
  color: var(--ice-dim);
  position: relative;
  opacity: 0;
  transform: translateY(6px);
  animation: mpl-msg-in 0.4s cubic-bezier(0.2, 0.7, 0.2, 1) forwards;
}
.mempalace-landing .msg.you { color: var(--ice); }
.mempalace-landing .msg.ai  { color: var(--ice-dim); }
.mempalace-landing .msg .who {
  font-family: var(--f-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  flex: 0 0 52px;
  padding-top: 3px;
  color: var(--prism);
  opacity: 0.85;
}
.mempalace-landing .msg.ai .who { color: var(--ember); }
.mempalace-landing .demo-remember .msg.ai .who { color: var(--prism); }
.mempalace-landing .msg .body {
  flex: 1 1 auto;
  min-width: 0;
  position: relative;
}
.mempalace-landing .msg .body strong {
  color: var(--prism);
  font-weight: 500;
  background: linear-gradient(180deg, transparent 60%, rgba(158,216,255,0.2) 60%);
  padding: 0 1px;
}
.mempalace-landing .demo-forget .msg.ai .body { color: var(--ember); }
.mempalace-landing .demo-remember .msg.ai .body { color: var(--ice); }
@keyframes mpl-msg-in { to { opacity: 1; transform: translateY(0); } }
.mempalace-landing .msg.typing .body::after {
  content: "";
  display: inline-block;
  width: 7px; height: 1.1em;
  margin-left: 3px;
  background: currentColor;
  vertical-align: -2px;
  animation: mpl-caret 0.9s steps(2) infinite;
}
@keyframes mpl-caret { 50% { opacity: 0; } }
.mempalace-landing .chat .divider-time {
  font-family: var(--f-display);
  font-style: italic;
  color: var(--ice-ghost);
  font-size: 0.95rem;
  text-align: center;
  padding: 0.4rem 0;
  position: relative;
  opacity: 0;
  animation: mpl-msg-in 0.5s ease 0.05s forwards;
}
.mempalace-landing .chat .divider-time::before,
.mempalace-landing .chat .divider-time::after {
  content: "";
  display: inline-block;
  width: 24px; height: 1px;
  background: var(--hair-strong);
  vertical-align: middle;
  margin: 0 0.8rem;
}
.mempalace-landing .chat .retrieval {
  display: grid;
  grid-template-columns: 52px 1fr auto;
  gap: 0.85rem;
  align-items: center;
  padding: 0.55rem 0.75rem;
  border: 1px dashed var(--hair-strong);
  background: rgba(74,163,255,0.05);
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--ice-ghost);
  opacity: 0;
  transform: translateY(4px);
  animation: mpl-msg-in 0.5s ease forwards;
}
.mempalace-landing .chat .retrieval .who { color: var(--prism); }
.mempalace-landing .chat .retrieval .l   { color: var(--ice); letter-spacing: 0.22em; }
.mempalace-landing .chat .retrieval .r   { color: var(--prism); }
.mempalace-landing .chat .stamp {
  margin-top: auto;
  padding-top: 0.9rem;
  border-top: var(--rule) solid var(--hair);
  font-family: var(--f-display);
  font-style: italic;
  font-size: 1.15rem;
  opacity: 0;
  animation: mpl-msg-in 0.6s ease forwards;
  display: flex; justify-content: space-between; align-items: baseline;
}
.mempalace-landing .chat .stamp .call {
  font-family: var(--f-mono);
  font-style: normal;
  font-size: 10px;
  letter-spacing: 0.22em;
  color: var(--ice-ghost);
  text-transform: uppercase;
}
.mempalace-landing .demo-forget   .chat .stamp { color: var(--ember); }
.mempalace-landing .demo-remember .chat .stamp { color: var(--prism); }
.mempalace-landing .dust-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  overflow: visible;
}
.mempalace-landing .dust-overlay .dust {
  position: absolute;
  will-change: transform, opacity, filter;
  transition-property: transform, opacity, filter;
  transition-timing-function: cubic-bezier(0.2, 0.55, 0.3, 1);
}

/* Anatomy */
.mempalace-landing .anatomy { padding-top: clamp(5rem, 9vw, 7rem); }
.mempalace-landing .anatomy-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 3rem;
  margin-bottom: clamp(3rem, 6vw, 5rem);
  align-items: end;
}
.mempalace-landing .anatomy h2 {
  font-size: clamp(2.25rem, 5vw, 4.2rem);
  margin: 1rem 0 0;
}
.mempalace-landing .anatomy h2 em { font-style: italic; color: var(--prism); }
.mempalace-landing .anatomy-diagram {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: clamp(1rem, 3vw, 2.5rem);
  padding: 2rem 0;
}
.mempalace-landing .stratum {
  position: relative;
  border: var(--rule) solid var(--hair);
  padding: 2rem 1.5rem;
  background: linear-gradient(180deg, rgba(17,21,28,0.6), rgba(10,13,18,0.2));
  min-height: 360px;
  display: flex;
  flex-direction: column;
  transition: border-color 0.4s ease, transform 0.4s ease;
}
.mempalace-landing .stratum:hover { border-color: var(--prism); transform: translateY(-4px); }
.mempalace-landing .stratum::before {
  content: "";
  position: absolute;
  top: -1px; left: 24px; right: 24px;
  height: 2px;
  background: var(--prism);
  opacity: 0.4;
}
.mempalace-landing .stratum .n {
  font-family: var(--f-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--prism);
}
.mempalace-landing .stratum h3 {
  font-family: var(--f-display);
  font-weight: 400;
  font-size: 2.4rem;
  letter-spacing: -0.01em;
  margin: 1.5rem 0 0.25rem;
  color: var(--ice);
}
.mempalace-landing .stratum h3 em { font-style: italic; color: var(--prism); font-weight: 300; }
.mempalace-landing .stratum .sub {
  font-family: var(--f-display);
  font-style: italic;
  font-size: 1.05rem;
  color: var(--ice-dim);
  margin-bottom: 1.5rem;
}
.mempalace-landing .stratum p {
  color: var(--ice-dim);
  font-size: 14.5px;
  margin: 0 0 1.5rem;
}
.mempalace-landing .stratum .diagram {
  margin-top: auto;
  height: 90px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: var(--rule) solid var(--hair);
  padding-top: 1rem;
}
.mempalace-landing .stratum .diagram svg { width: 100%; height: 100%; }

/* Dialect */
.mempalace-landing .dialect-head { max-width: 780px; margin-bottom: clamp(3rem, 6vw, 5rem); }
.mempalace-landing .dialect-head h2 { font-size: clamp(2.25rem, 5vw, 4rem); margin: 1rem 0 1.5rem; }
.mempalace-landing .dialect-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 56px minmax(0, 1fr);
  gap: 0;
  align-items: stretch;
}
.mempalace-landing .slab {
  position: relative;
  border: var(--rule) solid var(--hair);
  padding: clamp(1.5rem, 2.5vw, 2rem);
  background: linear-gradient(180deg, rgba(17,21,28,0.65), rgba(10,13,18,0.35));
  min-height: 420px;
}
.mempalace-landing .slab .card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: var(--rule) solid var(--hair);
  padding-bottom: 0.9rem;
  margin-bottom: 1.4rem;
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--ice-ghost);
}
.mempalace-landing .slab .card-head .l { color: var(--prism); }
.mempalace-landing .slab .label {
  font-family: var(--f-display);
  font-style: italic;
  color: var(--ice);
  font-size: 1.4rem;
  margin-bottom: 1.25rem;
}
.mempalace-landing .slab p {
  font-family: var(--f-display);
  font-size: 1.05rem;
  line-height: 1.55;
  color: var(--ice-dim);
  margin: 0 0 1rem;
}
.mempalace-landing .slab p strong {
  color: var(--ice);
  font-weight: 500;
  font-style: italic;
}
.mempalace-landing .slab.mono pre {
  font-family: var(--f-mono);
  font-size: 13px;
  line-height: 1.75;
  color: var(--ice-dim);
  margin: 0;
  white-space: pre-wrap;
}
.mempalace-landing .slab.mono pre .k { color: var(--prism); }
.mempalace-landing .slab.mono pre .t { color: var(--refract); }
.mempalace-landing .slab.mono pre .v { color: var(--stellar); }
.mempalace-landing .slab.mono pre .c { color: var(--ice-ghost); opacity: 0.6; }
.mempalace-landing .dialect-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  border-top: var(--rule) solid var(--hair);
  border-bottom: var(--rule) solid var(--hair);
}
.mempalace-landing .dialect-arrow svg { width: 28px; height: 28px; color: var(--prism); }
.mempalace-landing .dialect-arrow span {
  writing-mode: vertical-rl;
  transform: rotate(180deg);
  font-family: var(--f-mono);
  font-size: 10px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--ice-ghost);
}
.mempalace-landing .dialect-caption {
  margin-top: 1.5rem;
  font-family: var(--f-display);
  font-style: italic;
  color: var(--ice-ghost);
  font-size: 1rem;
  max-width: 60ch;
}

/* Mechanics */
.mempalace-landing .mechanics-head { max-width: 780px; margin-bottom: clamp(3rem, 6vw, 5rem); }
.mempalace-landing .mechanics-head h2 { font-size: clamp(2.25rem, 5vw, 4rem); margin: 1rem 0 1.5rem; }
.mempalace-landing .mechanics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  border: var(--rule) solid var(--hair);
}
.mempalace-landing .mech {
  position: relative;
  padding: clamp(1.5rem, 2.5vw, 2rem);
  border-right: var(--rule) solid var(--hair);
  min-height: 320px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  transition: background 0.4s ease;
}
.mempalace-landing .mech:last-child { border-right: 0; }
.mempalace-landing .mech:hover { background: rgba(158,216,255,0.03); }
.mempalace-landing .mech .n { color: var(--prism); }
.mempalace-landing .mech h3 {
  font-family: var(--f-display);
  font-weight: 400;
  font-size: 1.75rem;
  margin: 0.5rem 0 0;
  letter-spacing: -0.005em;
}
.mempalace-landing .mech h3 em { font-style: italic; color: var(--prism); }
.mempalace-landing .mech p {
  color: var(--ice-dim);
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}
.mempalace-landing .mech .icon {
  width: 48px; height: 48px;
  color: var(--prism);
  opacity: 0.85;
}
.mempalace-landing .mech .icon svg { width: 100%; height: 100%; }
.mempalace-landing .mech .metric {
  margin-top: auto;
  padding-top: 1rem;
  border-top: var(--rule) solid var(--hair);
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.2em;
  color: var(--ice-ghost);
  text-transform: uppercase;
}
.mempalace-landing .mech .metric b { color: var(--prism); font-weight: 500; }

/* Install */
.mempalace-landing .install {
  text-align: center;
  padding: clamp(6rem, 12vw, 10rem) var(--gutter);
  background: radial-gradient(60% 80% at 50% 100%, rgba(74,163,255,0.18), transparent 70%);
}
.mempalace-landing .install h2 {
  font-size: clamp(2.75rem, 7vw, 5.5rem);
  margin: 1rem 0 1.5rem;
}
.mempalace-landing .install h2 em { font-style: italic; color: var(--prism); }
.mempalace-landing .install .lede { margin: 0 auto 3rem; }
.mempalace-landing .terminal {
  max-width: 720px;
  margin: 0 auto 2.5rem;
  border: var(--rule) solid var(--hair-strong);
  background: linear-gradient(180deg, rgba(17,21,28,0.9), rgba(10,13,18,0.7));
  text-align: left;
  box-shadow: inset 0 1px 0 rgba(234,244,255,0.04),
              0 30px 80px -30px rgba(74,163,255,0.3),
              0 0 0 1px rgba(158,216,255,0.06);
}
.mempalace-landing .terminal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.7rem 1rem;
  border-bottom: var(--rule) solid var(--hair);
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.2em;
  color: var(--ice-ghost);
  text-transform: uppercase;
}
.mempalace-landing .terminal-head .lights { display: flex; gap: 6px; }
.mempalace-landing .terminal-head .lights i {
  display: block; width: 8px; height: 8px; border-radius: 50%;
  border: 1px solid rgba(158,216,255,0.25);
  background: rgba(158,216,255,0.08);
}
.mempalace-landing .terminal pre {
  margin: 0;
  padding: 1.5rem 1.5rem 2rem;
  font-family: var(--f-mono);
  font-size: 14px;
  line-height: 1.9;
  color: var(--ice);
  white-space: pre-wrap;
}
.mempalace-landing .terminal .prompt { color: var(--prism); user-select: none; }
.mempalace-landing .terminal .c      { color: var(--ice-ghost); }
.mempalace-landing .terminal .ok     { color: var(--prism); }
.mempalace-landing .terminal .dim    { color: var(--ice-ghost); }
.mempalace-landing .install-cta {
  display: inline-flex;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
}

/* Footer */
.mempalace-landing footer.catalog {
  position: relative;
  padding: clamp(3rem, 6vw, 4.5rem) var(--gutter);
  border-top: var(--rule) solid var(--hair);
}
.mempalace-landing .catalog-card {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 2rem;
  padding: 2rem 0;
  border-top: var(--rule) solid var(--hair-strong);
  border-bottom: var(--rule) solid var(--hair-strong);
}
.mempalace-landing .catalog-card h4 {
  font-family: var(--f-mono);
  font-size: 10.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--ice-ghost);
  margin: 0 0 1rem;
  font-weight: 400;
}
.mempalace-landing .catalog-card ul { list-style: none; margin: 0; padding: 0; }
.mempalace-landing .catalog-card li {
  font-family: var(--f-display);
  font-size: 1.05rem;
  line-height: 1.5;
  color: var(--ice-dim);
}
.mempalace-landing .catalog-card li a {
  color: var(--ice-dim);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: color 0.25s, border-color 0.25s;
}
.mempalace-landing .catalog-card li a:hover { color: var(--prism); border-color: var(--prism); }
.mempalace-landing .catalog-title {
  font-family: var(--f-display);
  font-size: clamp(1.5rem, 3vw, 2.25rem);
  color: var(--ice);
  line-height: 1.2;
  margin: 0 0 0.75rem;
}
.mempalace-landing .catalog-title em { font-style: italic; color: var(--prism); }
.mempalace-landing .catalog-desc {
  font-family: var(--f-display);
  font-style: italic;
  color: var(--ice-dim);
  font-size: 1rem;
  margin: 0;
  max-width: 38ch;
}

/* Responsive */
@media (max-width: 1100px) {
  .mempalace-landing .mechanics { grid-template-columns: repeat(2, 1fr); }
  .mempalace-landing .mech:nth-child(2) { border-right: 0; }
  .mempalace-landing .mech:nth-child(1),
  .mempalace-landing .mech:nth-child(2) { border-bottom: var(--rule) solid var(--hair); }
}
@media (max-width: 900px) {
  .mempalace-landing .hero { grid-template-columns: 1fr; gap: 2rem; }
  .mempalace-landing .palace-stage { justify-self: center; max-width: 400px; order: -1; aspect-ratio: 1 / 0.85; }
  .mempalace-landing .anatomy-head { grid-template-columns: 1fr; }
  .mempalace-landing .anatomy-diagram { grid-template-columns: 1fr; }
  .mempalace-landing .forgetting-head { grid-template-columns: 1fr; }
  .mempalace-landing .forgetting-compare { grid-template-columns: 1fr; min-height: 0; }
  .mempalace-landing .forgetting-compare .divider { display: none; }
  .mempalace-landing .demo-pane { min-height: 0; }
  .mempalace-landing .demo-pane + .demo-pane { border-top: var(--rule) solid var(--hair-strong); }
  .mempalace-landing .dialect-grid { grid-template-columns: 1fr; }
  .mempalace-landing .dialect-arrow { padding: 1rem 0; border-left: 0; border-right: 0; }
  .mempalace-landing .dialect-arrow span { writing-mode: initial; transform: none; }
  .mempalace-landing .catalog-card { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 600px) {
  .mempalace-landing .folio { gap: 1rem; padding: 14px 1.25rem; }
  .mempalace-landing .folio .right { gap: 1rem; }
  .mempalace-landing .folio .right .hide-mobile { display: none; }
  .mempalace-landing .hero-stats { grid-template-columns: 1fr 1fr; }
  .mempalace-landing .catalog-card { grid-template-columns: 1fr; }
  .mempalace-landing .waitlist-row { grid-template-columns: 1fr; }
  .mempalace-landing .waitlist-meta { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .mempalace-landing *,
  .mempalace-landing *::before,
  .mempalace-landing *::after {
    animation-duration: 0.001s !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001s !important;
  }
}
</style>
