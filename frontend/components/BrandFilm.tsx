'use client'

import { useEffect, useRef, type CSSProperties } from 'react'
import { Phone, Globe, UserPlus } from 'lucide-react'

// ── Axon brand film ──
// A 72-second, scene-based "video" drawn entirely in CSS/JS — no media file.
// Ported from the standalone axon-brand-film.html deliverable; it replaces the
// old /hero-demo.mp4 <video> in the landing hero. Styles live in
// app/brand-film.css (scoped under .bfilm). A master rAF clock drives scene
// switching, the seek rail, and the score counter; per-element timing inside a
// scene is plain CSS animation-delay (the --d custom property).

// Scene timeline: [id, duration in seconds, chapter label]
const SC: Array<[string, number, string]> = [
  ['s1', 6.5, 'cold open'],
  ['s2', 9.0, 'the problem'],
  ['s3', 7.0, 'meet axon'],
  ['s4', 9.0, '01 · capture'],
  ['s5', 13.0, '02 · score'],
  ['s6', 10.0, '03 · prioritize'],
  ['s7', 7.5, 'payoff'],
  ['s8', 10.0, 'get started'],
]

const d = (delay: string) => ({ '--d': delay } as CSSProperties)

// Survey-plat texture drifting behind every scene (inherits currentColor).
const Plat = () => (
  <svg className="plat" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <g fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M-40 640 C 260 560, 520 700, 860 620 S 1420 520, 1680 590" />
      <rect x="120" y="120" width="300" height="220" />
      <rect x="470" y="150" width="240" height="190" />
      <rect x="1080" y="90" width="330" height="260" />
      <rect x="220" y="700" width="280" height="170" />
      <rect x="980" y="660" width="260" height="200" />
      <path d="M760 60 L760 380 M760 220 L1080 220" />
      <path d="M1460 380 L1600 380 M1520 380 L1520 700" />
      <path d="M120 470 L420 470 M270 340 L270 470" />
    </g>
    <g fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="3 9" className="accentline">
      <path d="M60 90 L60 850" />
      <path d="M1540 60 L1540 320" />
      <path d="M470 250 L1080 250" />
      <path d="M300 560 L1300 560" />
    </g>
    <g stroke="currentColor" strokeWidth="1.4">
      <path d="M860 140 l14 0 M867 133 l0 14" />
      <path d="M420 620 l14 0 M427 613 l0 14" />
      <path d="M1240 470 l14 0 M1247 463 l0 14" />
    </g>
  </svg>
)

const PlaySvg = () => <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
const ReplaySvg = () => <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 2.8-6.5" /><path d="M3 4v5h5" /></svg>

export default function BrandFilm() {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const cleanups: Array<() => void> = []

    const starts: number[] = []
    let TOTAL = 0
    for (const [, dur] of SC) { starts.push(TOTAL); TOTAL += dur }

    const $ = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!
    const stage = $('.stage')
    const scenes = SC.map(([id]) => $(`#${id}`))
    const scoreN = $('.scoren')
    const fill = $('.rail .fill')
    const tcCur = $('[data-tc-cur]')
    const tcTot = $('[data-tc-tot]')
    const chap = $('.chap')
    const ticksEl = $('[data-ticks]')
    const rail = $('.rail')
    const bigplay = $('[data-bigplay]')

    let t = 0, playing = false, ended = false, cur = -1, lastTs: number | null = null

    const fmt = (sec: number) => {
      sec = Math.max(0, Math.round(sec))
      const m = Math.floor(sec / 60), s = sec % 60
      return `${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`
    }
    const sceneAt = (time: number) => {
      for (let i = SC.length - 1; i >= 0; i--) { if (time >= starts[i]) return i }
      return 0
    }
    const easeOutCubic = (p: number) => 1 - Math.pow(1 - p, 3)

    const apply = (idx: number, force?: boolean) => {
      if (idx === cur && !force) return
      const old = cur
      scenes.forEach((s, i) => {
        s.classList.remove('active', 'prev')
        if (i === old && i !== idx) s.classList.add('prev')
      })
      const el = scenes[idx]
      void el.offsetWidth // restart css animations
      el.classList.add('active')
      cur = idx
      chap.textContent = SC[idx][2]
    }

    // Score counter is driven by the master clock, not CSS, so it stays
    // correct across seeks and pauses.
    const driveScore = () => {
      let val: number
      if (cur < 4) val = 0
      else if (cur > 4) val = 82
      else {
        const local = t - starts[4]
        const p = Math.min(1, Math.max(0, (local - 2.0) / 2.8))
        val = Math.round(easeOutCubic(p) * 82)
      }
      const str = String(val)
      if (scoreN.textContent !== str) scoreN.textContent = str
    }

    const ui = () => {
      stage.classList.toggle('paused', !playing)
      root.classList.toggle('playing', playing)
      root.classList.toggle('ended', ended)
      bigplay.setAttribute('aria-label', ended ? 'Replay' : playing ? 'Pause' : 'Play')
    }

    const restart = () => {
      t = 0; ended = false; playing = true
      apply(0, true); ui()
    }
    const playPause = () => {
      if (ended) { restart(); return }
      playing = !playing
      ui()
    }
    const seekScene = (idx: number) => {
      idx = Math.max(0, Math.min(SC.length - 1, idx))
      t = starts[idx] + 0.001
      ended = false
      apply(idx, true)
      ui()
    }

    let rafId = 0
    const loop = (ts: number) => {
      if (lastTs === null) lastTs = ts
      let dt = (ts - lastTs) / 1000
      lastTs = ts
      if (dt > 0.25) dt = 0.25 // tab-switch guard

      if (playing) {
        t += dt
        if (t >= TOTAL) { t = TOTAL; playing = false; ended = true; ui() }
      }
      const idx = sceneAt(Math.min(t, TOTAL - 0.001))
      if (idx !== cur) apply(idx)

      fill.style.width = `${(t / TOTAL) * 100}%`
      tcCur.textContent = fmt(t)
      driveScore()

      rafId = requestAnimationFrame(loop)
    }

    // Chapter ticks + rail seeking.
    for (let k = 1; k < SC.length; k++) {
      const tick = document.createElement('div')
      tick.className = 'tick'
      tick.style.left = `${(starts[k] / TOTAL) * 100}%`
      ticksEl.appendChild(tick)
    }
    cleanups.push(() => { ticksEl.innerHTML = '' })

    const on = (el: HTMLElement, ev: string, fn: (e: Event) => void) => {
      el.addEventListener(ev, fn)
      cleanups.push(() => el.removeEventListener(ev, fn))
    }

    on(rail, 'click', (e) => {
      const me = e as MouseEvent
      const r = rail.getBoundingClientRect()
      const pct = Math.min(1, Math.max(0, (me.clientX - r.left) / r.width))
      seekScene(sceneAt(pct * (TOTAL - 0.001)))
      if (!playing) { playing = true; ui() }
      e.stopPropagation()
    })
    on($('[data-play]'), 'click', (e) => { e.stopPropagation(); playPause() })
    on($('[data-restart]'), 'click', (e) => { e.stopPropagation(); restart() })
    on(bigplay, 'click', (e) => { e.stopPropagation(); playPause() })
    on($('[data-replay]'), 'click', (e) => { e.stopPropagation(); restart() })
    on(stage, 'click', (e) => {
      if ((e.target as HTMLElement).closest('button, a')) return
      playPause()
    })

    // Keyboard transport — scoped to the player (not document) so the film
    // never hijacks page-level scrolling or shortcuts.
    on(root, 'keydown', (e) => {
      const ke = e as KeyboardEvent
      if ((ke.target as HTMLElement).closest('button, a, input, textarea')) return
      if (ke.code === 'Space' || ke.key === 'k') { ke.preventDefault(); playPause() }
      else if (ke.key === 'ArrowRight') seekScene(cur + 1)
      else if (ke.key === 'ArrowLeft') { if (t - starts[cur] > 1.5) seekScene(cur); else seekScene(cur - 1) }
      else if (ke.key === 'r') restart()
    })

    // Responsive type scale: 1em = 1% of stage width.
    const setScale = () => { stage.style.fontSize = `${stage.clientWidth / 100}px` }
    const ro = new ResizeObserver(setScale)
    ro.observe(stage)
    cleanups.push(() => ro.disconnect())

    // Autoplay (like the mp4 it replaced) — but only once the player is
    // actually in view, so the film doesn't run out before anyone scrolls to it.
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        io.disconnect()
        if (!playing && !ended && t === 0) { playing = true; ui() }
      })
    }, { threshold: 0.35 })
    io.observe(stage)
    cleanups.push(() => io.disconnect())

    // Init.
    tcTot.textContent = fmt(TOTAL)
    setScale()
    apply(0, true)
    ui()
    rafId = requestAnimationFrame(loop)
    cleanups.push(() => cancelAnimationFrame(rafId))

    return () => cleanups.forEach((fn) => fn())
  }, [])

  return (
    <div className="bfilm" ref={rootRef}>
      <div className="kicker"><span>axon — brand film</span><span>72s · no audio</span></div>

      <div className="stage" tabIndex={0} aria-label="Axon brand film">

        {/* scene 1 · cold open */}
        <section className="scene on-ink" id="s1">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div className="mask" style={d('.6s')}><span className="mi display" style={{ fontSize: '5.5em' }}>Every lead looks the same.</span></div>
            <div className="mask" style={d('2.5s')}><span className="mi display l2" style={{ fontSize: '5.5em' }}>Until you know <span className="ul" style={d('4.5s')}>what&apos;s behind it.</span></span></div>
          </div>
        </section>

        {/* scene 2 · the problem */}
        <section className="scene on-paper" id="s2">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div className="cutstack">
              <div className="cut" style={d('.4s')}>Who&apos;s serious?</div>
              <div className="cut" style={d('2.4s')}>Who&apos;s price-shopping?</div>
              <div className="cut" style={d('4.4s')}>Who&apos;s worth rolling a truck for?</div>
            </div>
            <div className="mask" style={d('6.7s')}><span className="mi display settle">You&apos;ve been answering by gut.</span></div>
            <p className="body sub fup" style={d('7.5s')}>Service contractors lose hours every week chasing leads that were never going to close.</p>
          </div>
        </section>

        {/* scene 3 · meet axon */}
        <section className="scene on-ink" id="s3">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div className="overline fup" style={d('.5s')}>business intelligence for service contractors</div>
            <div className="mask" style={d('1s')}><span className="mi wordmark">axon</span></div>
            <div className="rule"><div className="hairdraw" style={d('1.9s')} /></div>
            <p className="sub fup" style={d('2.6s')}>Lead scoring that reads the property — not just the phone number.</p>
          </div>
        </section>

        {/* scene 4 · 01 capture */}
        <section className="scene on-paper step" id="s4">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div>
              <div className="overline fup" style={d('.4s')}>how it works — 01</div>
              <h2 className="display"><span className="mask" style={d('.7s')}><span className="mi">Every lead,</span></span><span className="mask" style={d('.85s')}><span className="mi">one queue</span></span></h2>
              <p className="body fup" style={d('1.3s')}>Calls, web forms, and referrals land in a single inbox the moment they come in. Nothing slips, nothing gets copy-pasted.</p>
            </div>
            <div className="card fup" style={d('1.1s')} id="s4-rows">
              <div className="cardhead">
                <span className="cardtitle">incoming leads</span>
                <span className="livedot"><i />live</span>
              </div>
              <div className="row" style={d('1.8s')}>
                <div className="who"><div className="name">Dana Whitfield</div><div className="job">water heater replacement</div></div>
                <span className="srcchip"><Phone />call</span>
                <span className="when">2m</span>
              </div>
              <div className="row" style={d('2.5s')}>
                <div className="who"><div className="name">M. Okafor</div><div className="job">panel upgrade</div></div>
                <span className="srcchip"><Globe />website</span>
                <span className="when">9m</span>
              </div>
              <div className="row" style={d('3.2s')}>
                <div className="who"><div className="name">R. Salas</div><div className="job">fence + gate</div></div>
                <span className="srcchip"><UserPlus />referral</span>
                <span className="when">14m</span>
              </div>
            </div>
          </div>
        </section>

        {/* scene 5 · 02 score — signature */}
        <section className="scene on-ink step" id="s5">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div>
              <div className="overline fup" style={d('.4s')}>how it works — 02</div>
              <h2 className="display"><span className="mask" style={d('.7s')}><span className="mi">Axon reads</span></span><span className="mask" style={d('.85s')}><span className="mi">the property</span></span></h2>
              <p className="body fup" style={d('1.3s')}>Six public-record signals — pulled, weighted, and scored the moment a lead arrives.</p>
              <div className="monosm caption fup" style={d('6.2s')}>six signals · weighted · explainable</div>
            </div>
            <div className="instrument">
              <div className="signals">
                <div className="sig fup" style={d('2s')}><span className="k">home age</span><span className="v">24 yrs</span></div>
                <div className="sig fup" style={d('2.45s')}><span className="k">last sale</span><span className="v">9 yrs ago</span></div>
                <div className="sig fup" style={d('2.9s')}><span className="k">est. equity</span><span className="v">high</span></div>
                <div className="sig fup" style={d('3.35s')}><span className="k">garage</span><span className="v">2 spaces</span></div>
                <div className="sig fup" style={d('3.8s')}><span className="k">area income</span><span className="v">top 20%</span></div>
                <div className="sig fup" style={d('4.25s')}><span className="k">permits</span><span className="v">3 in 5 yrs</span></div>
              </div>
              <div className="ringwrap fup" style={d('1.6s')}>
                <svg viewBox="0 0 100 100" aria-hidden="true">
                  <circle className="ringtrack" cx="50" cy="50" r="46" />
                  <circle className="ringp" cx="50" cy="50" r="46" />
                </svg>
                <div className="scorebox">
                  <div className="scoren">0</div>
                  <div className="scoreof">/ 100</div>
                </div>
                <div className="gradechipbig"><span className="gl">grade</span><span className="gv">A</span></div>
              </div>
            </div>
          </div>
        </section>

        {/* scene 6 · 03 prioritize */}
        <section className="scene on-paper step" id="s6">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div>
              <div className="overline fup" style={d('.4s')}>how it works — 03</div>
              <h2 className="display"><span className="mask" style={d('.7s')}><span className="mi">Work the</span></span><span className="mask" style={d('.85s')}><span className="mi">A-list first</span></span></h2>
              <p className="body fup" style={d('1.3s')}>The queue sorts itself before the first truck rolls. High-value jobs rise to the top — the rest can wait.</p>
            </div>
            <div className="card fup" style={d('1.1s')}>
              <div className="cardhead">
                <span className="cardtitle">today&apos;s queue</span>
                <span className="livedot"><i />sorted by score</span>
              </div>
              <div className="qrow top slidein" style={d('1.7s')}>
                <span className="g gA">A</span>
                <div className="lead"><div className="lname">Dana Whitfield</div><div className="ljob">water heater replacement</div></div>
                <span className="callnext">call next</span>
                <span className="lscore">86</span>
              </div>
              <div className="qrow slidein" style={d('2.3s')}>
                <span className="g gA">A</span>
                <div className="lead"><div className="lname">4212 Larkspur Ln</div><div className="ljob">whole-home repipe</div></div>
                <span className="lscore">82</span>
              </div>
              <div className="qrow slidein" style={d('2.9s')}>
                <span className="g gB">B</span>
                <div className="lead"><div className="lname">M. Okafor</div><div className="ljob">panel upgrade</div></div>
                <span className="lscore">61</span>
              </div>
              <div className="qrow slidein" style={d('3.5s')}>
                <span className="g gC">C</span>
                <div className="lead"><div className="lname">R. Salas</div><div className="ljob">fence + gate</div></div>
                <span className="lscore">38</span>
              </div>
              <div className="legend fup" style={d('4.4s')}>A ≥ 75&nbsp;&nbsp;·&nbsp;&nbsp;B ≥ 55&nbsp;&nbsp;·&nbsp;&nbsp;C ≥ 35</div>
            </div>
          </div>
        </section>

        {/* scene 7 · payoff */}
        <section className="scene on-ink" id="s7">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div className="mask" style={d('.5s')}><span className="mi display">Your best jobs were always in the list.</span></div>
            <div className="mask" style={d('2.3s')}><span className="mi display">Now they&apos;re <span className="ul" style={d('4s')}>at the top.</span></span></div>
            <div className="pills">
              <span className="pill fup" style={d('4.4s')}>6 signals</span>
              <span className="pill fup" style={d('4.6s')}>3 grades</span>
              <span className="pill fup" style={d('4.8s')}>1 queue</span>
            </div>
          </div>
        </section>

        {/* scene 8 · end card */}
        <section className="scene on-paper" id="s8">
          <div className="bglayer"><Plat /></div>
          <div className="safe">
            <div className="mask" style={d('.5s')}><span className="mi wordmark" style={{ color: 'var(--ink)' }}>axon</span></div>
            <p className="tagline fup" style={d('1.2s')}>Know which leads are worth the drive.</p>
            <div className="ctas fup" style={d('2s')}>
              <a className="fbtn primary" href="/signup">Get started</a>
              <button className="fbtn ghost" type="button" data-replay>Replay</button>
            </div>
            <div className="foot fup" style={d('2.7s')}>axon — business intelligence for service contractors</div>
          </div>
        </section>

        {/* film overlays */}
        <div className="grain" />
        <div className="vignette" />

        {/* big play / replay */}
        <button className="bigplay" type="button" data-bigplay aria-label="Play">
          <span className="disc">
            <span className="g-play"><PlaySvg /></span>
            <span className="g-replay"><ReplaySvg /></span>
          </span>
        </button>
      </div>

      {/* chrome */}
      <div className="chrome">
        <button className="cbtn" type="button" data-play aria-label="Play or pause">
          <span className="i-play"><PlaySvg /></span>
          <span className="i-pause"><svg viewBox="0 0 24 24"><line x1="9" y1="5" x2="9" y2="19" /><line x1="15" y1="5" x2="15" y2="19" /></svg></span>
        </button>
        <div className="tc"><span data-tc-cur>00:00</span> <span>/ <span data-tc-tot>01:12</span></span></div>
        <div className="rail" aria-label="Seek by chapter">
          <div className="track">
            <div className="fill" />
            <div data-ticks />
          </div>
        </div>
        <div className="chap">cold open</div>
        <button className="cbtn" type="button" data-restart aria-label="Restart film">
          <ReplaySvg />
        </button>
      </div>
    </div>
  )
}
