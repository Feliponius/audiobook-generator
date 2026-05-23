# Audiobook Library Visual Audit and Redesign Direction

Date: 2026-05-18

## Goal

Document the current visual state of the book service, explain why it feels inconsistent today, and outline a concrete redesign direction for a **Spotify + Google Play Books hybrid** with **optional color schemes**.

---

## Executive summary

The app already has a strong functional foundation, but its visual identity is split across three different product personalities:

1. **Library screen** — dark green, soft, Spotify-adjacent, mobile-friendly.
2. **Book detail screen** — light blue/white, productivity-dashboard-like, much closer to a utility app than a media app.
3. **Reader shell** — dark, content-first, closer to Google Play Books, but isolated from the rest of the visual system.

The result is not that the UI is bad — it is that the app feels like **multiple prototypes stitched together**. The biggest source of inconsistency is not layout alone; it is the fact that each major screen appears to belong to a different brand.

The redesign should keep the current information architecture mostly intact, but unify it around:

- a single design token system,
- a single navigation model,
- a clearer distinction between **consume content** vs **manage pipeline**,
- a stronger cover-art-forward hero,
- and a theme system that supports multiple palettes without changing component structure.

---

## What I reviewed

### Live UI review
I inspected the running app in-browser at `http://127.0.0.1:8123` and reviewed:
- library screen
- settings screen
- book detail screen

### Code review
Primary implementation is in:
- `dashboard/index.html`

Notable structural sections:
- reader shell markup: `dashboard/index.html:819-845`
- library screen markup: `dashboard/index.html:847-865`
- book screen markup: `dashboard/index.html:867-928`
- settings screen markup: `dashboard/index.html:930-950`
- bottom nav: `dashboard/index.html:952-955`
- global tokens: `dashboard/index.html:12-28`
- book-screen visual overrides: `dashboard/index.html:593-650`
- library rendering logic: `dashboard/index.html:1144-1191`

Related product intent already exists in:
- `docs/audiobook-library-prd.md`

---

## Current state: what the app is doing well

## 1. The library screen already has a promising base identity
The library screen is the strongest visual foundation in the app.

What works:
- deep green / spruce / jade direction
- rounded cards and rounded controls
- reasonably good spacing
- strong mobile width discipline
- clear cover/title/author/status structure
- simple upload call to action

Relevant code:
- global palette tokens: `dashboard/index.html:12-28`
- library layout and cards: `dashboard/index.html:121-197`
- library markup: `dashboard/index.html:847-865`
- library render logic: `dashboard/index.html:1144-1191`

This screen already feels directionally aligned with the PRD goal of a calmer green-led mobile-first product.

## 2. The reader shell is conceptually on the right track
The reader shell is clearly trying to be content-first and low-chrome.

What works:
- fixed immersive shell
- minimal top bar
- day/night reading modes
- tap zones for previous/next page
- separate contents sheet

Relevant code:
- reader shell CSS: `dashboard/index.html:383-545`
- reader markup: `dashboard/index.html:819-845`

This is much closer to a Google Play Books style interaction model than the rest of the app.

## 3. Functionally, the book detail screen is rich
The book detail page includes most of the product features the app needs:
- read action
- listen action
- progress
- bookmarks
- notes
- playback
- chapters
- diagnostics

Relevant code:
- book screen markup: `dashboard/index.html:867-928`

So this is not a feature-gap problem. It is mostly a **visual hierarchy and product framing problem**.

---

## Current state: why it feels inconsistent

## 1. The app changes brands between screens
This is the biggest issue.

### Library screen
Uses the dark green global token set:
- `--bg0`, `--bg1`, `--surface`, `--accent`, `--accent2`, `--mint`
- `dashboard/index.html:12-28`

### Book screen
Overrides that identity with a different visual system:
- light blue/white page background
- blue primary buttons
- blue section headings
- white glassy cards

Relevant code:
- `dashboard/index.html:593-650`

Examples:
- `#bookScreen { background: linear-gradient(180deg, #f7f9fe 0%, #eef3fb 100%); }`
- `#bookScreen .btn-primary { background: linear-gradient(135deg, #3362e6, #5a7cff); }`
- `#bookScreen .detail-section h3 { color: #274ea6; }`

This means the user leaves a dark green audiobook app and enters a light blue productivity dashboard. That is the visual inconsistency you are feeling most strongly.

## 2. The bottom nav is structurally global but visually weak
The bottom nav is always present:
- `dashboard/index.html:952-955`

And styled as:
- `dashboard/index.html:547-559`

Problems:
- only two destinations, so it feels like a pair of buttons more than an app shell
- it does not strongly indicate active state
- it feels detached from the current screen
- it competes with top back buttons on subpages

On settings, this creates duplicate navigation.
On book detail, it weakens immersion.

## 3. The book detail page is over-indexed on operations, not consumption
Today the book page gives heavy visual weight to:
- audiobook generation status
- current chunk
- last event
- diagnostics

And comparatively less emotional or structural weight to:
- continue reading
- continue listening
- where I left off
- cover art
- chapter browsing as a media experience

Relevant markup:
- CTA stack: `dashboard/index.html:878-887`
- generation section: `dashboard/index.html:888-891`
- progress section: `dashboard/index.html:892-898`
- player panel: `dashboard/index.html:914-917`
- chapter list: `dashboard/index.html:918-920`
- diagnostics: `dashboard/index.html:922-927`

The page currently reads as **book + pipeline control panel**, not **book + reading/listening experience**.

## 4. Section hierarchy is too flat
Most information is expressed as repeated stacked cards/sections with similar weight.

This creates three problems:
- everything looks equally important
- the page becomes long and document-like
- the screen feels more like an admin panel than a polished media app

## 5. Settings copy is technically honest but product-visually rough
The settings screen includes implementation-specific language directly in the main UI:
- “script-only cleanup”
- “no LLM rewrite”
- “2 Kokoro workers”
- “not enforced yet”
- `epub_to_audiobook.py`

Relevant markup:
- `dashboard/index.html:936-948`

This is useful for development, but it makes the screen feel unfinished and tool-facing.

## 6. Themes exist only in isolated pockets
There is already a micro-theme concept in the reader:
- `data-reading-theme="night"`
- `data-reading-theme="day"`
- `dashboard/index.html:472-477`

But there is no app-wide theming model.

Right now theme decisions are screen-specific overrides rather than a shared system.

---

## Screen-by-screen assessment

## Library screen
### Current feel
- closest to Spotify-inspired
- dark, calm, card-based, mobile-appropriate

### Strengths
- coherent mood
- straightforward browsing
- simple top-level actions

### Weaknesses
- cover art is still too small for a book-driven experience
- favorite star is visually weak
- chips and status affordances are functional but not premium
- bottom nav is not strong enough to feel like a true shell

## Settings screen
### Current feel
- same dark shell as library, but more developer-facing

### Strengths
- consistent enough with library styling
- form controls are readable
- primary save action is clear

### Weaknesses
- redundant back button + bottom nav
- explanatory copy dominates the form
- “not enforced yet” messaging makes the app feel provisional
- advanced implementation detail is shown at the top layer

## Book detail screen
### Current feel
- closest to a utility dashboard or mobile productivity tool
- much less aligned with the library screen

### Strengths
- complete feature inventory
- readable sections
- chapter list is useful

### Weaknesses
- visually belongs to another product
- hero is too small and not immersive enough
- generation diagnostics dominate instead of consumption actions
- native media player feels generic
- too many stacked cards with equal weight

## Reader screen
### Current feel
- strongest Google Play Books influence
- content-first and restrained

### Strengths
- minimal chrome
- correct reading-mode priorities
- promising base for a polished reader

### Weaknesses
- visually disconnected from app shell
- not obviously tied into broader theme system
- likely needs stronger typography and spacing tuning for premium feel

---

## Root causes in the current code

## 1. One-file UI encourages local overrides over system design
Because `dashboard/index.html` contains tokens, screen markup, styling, and logic together, it is easy to add a local override for one screen instead of extending a shared system.

That is exactly what happened with `#bookScreen`.

## 2. Global tokens exist, but the app is not fully token-driven
The library uses the root token system.
The book screen partially bypasses it with hardcoded blue/white values.

This means the app has a token layer, but not a fully enforced design system.

## 3. Consumption and pipeline-management concerns share the same visual layer
The UI tries to serve both:
- a personal reading/listening app
- an operator monitor for audiobook generation

Both are valid, but they should not have equal emphasis on the same surface.

---

## Recommended redesign direction

## North star
Make the app feel like:
- **Spotify** for audio confidence, strong CTAs, mood, and cover-art presence
- **Google Play Books** for reading ergonomics, restrained chrome, progress continuity, and contents access

The hybrid should be:
- cover-art-forward
- mobile-first
- calm rather than flashy
- product-feeling rather than dashboard-feeling
- able to support multiple visual themes without reworking layout

---

## Proposed experience model

## 1. Use one app shell everywhere
Recommended primary nav:
- Library
- Continue / Now Playing
- Settings

This matches the PRD direction in `docs/audiobook-library-prd.md:109-125`.

Rules:
- top back buttons only where necessary
- bottom nav should feel like a real tab bar, not two independent buttons
- active tab must be obvious
- sub-screens should still feel inside the same product family

## 2. Reframe the book detail page around “continue”
The top of the page should answer:
- What book is this?
- What was I doing last?
- What should I do now?

Recommended order:
1. immersive hero
2. continue card
3. read/listen mode switch or paired CTAs
4. progress summary
5. chapters / contents
6. notes and bookmarks
7. technical details
8. diagnostics

## 3. Demote technical pipeline information
When the audiobook is complete, generation details should shrink to a compact status summary.

Examples:
- “Audiobook ready”
- “51 chapters available”
- “Last generated 2h ago”

Then put chunk/event/raw details under:
- Technical details
- Advanced
- Diagnostics

If a run is failing or actively generating, that card can temporarily rise in prominence.

## 4. Make chapters behave like both an album track list and a table of contents
Each chapter row should visually support:
- title
- current/completed/locked state
- duration if known
- quick play/read jump
- obvious selected state

Goal:
- Spotify track-list scanability
- Google Play Books jump-to-section usefulness

## 5. Strengthen the hero
The current hero should become the anchor of the book page.

Recommended changes:
- larger cover
- subtle blurred/gradient backdrop based on cover palette
- clearer author and metadata line
- visible read/listen progress
- one dominant continue action

---

## Proposed visual system

## Design principles
1. **One component language, many themes**
2. **Content first, diagnostics second**
3. **Strong hierarchy at the top, quieter utilities below**
4. **Large touch targets always**
5. **No screen-specific brand swaps**

## Component families
### Primary surfaces
- hero sections
- continue cards
- active playback cards

### Secondary surfaces
- notes
- bookmarks
- chapter list containers
- form fields

### Utility surfaces
- advanced settings
- diagnostics
- raw event details

## Token groups to define
Instead of hardcoding screen-level colors, define app tokens like:
- `--color-bg`
- `--color-bg-elevated`
- `--color-surface-1`
- `--color-surface-2`
- `--color-text`
- `--color-text-muted`
- `--color-accent`
- `--color-accent-contrast`
- `--color-success`
- `--color-warning`
- `--color-danger`
- `--color-border`
- `--color-shadow`

And semantic component tokens like:
- `--hero-bg`
- `--card-bg`
- `--nav-bg`
- `--cta-primary-bg`
- `--cta-secondary-bg`
- `--status-ready-bg`
- `--status-running-bg`

This is what will make multiple optional color schemes practical.

---

## Optional color schemes

The app should support a small set of curated app-wide themes. These should change tokens, not layouts.

## Theme 1: Forest Audio
Best default for your current direction.

Mood:
- Spotify-adjacent
- dark, calm, premium
- spruce / sage / emerald-muted

Suggested direction:
- background: deep spruce-black
- surface: muted jade / forest glass
- accent: soft emerald
- highlight: mint-sage
- text: warm off-white

Best for:
- default app shell
- library
- player surfaces

## Theme 2: Play Books Light
Best if you want a cleaner reading-first daytime mode.

Mood:
- editorial
- airy
- soft paper + ink

Suggested direction:
- background: warm off-white / mist
- surface: white / pearl
- accent: desaturated blue-green or Google-like soft blue
- text: charcoal
- muted text: warm gray-blue

Best for:
- day reading
- settings
- users who prefer less moody chrome

## Theme 3: Midnight Theater
Best for listening-heavy use.

Mood:
- cinematic
- high contrast
- album-like

Suggested direction:
- background: charcoal / midnight
- surface: graphite
- accent: emerald or violet-cyan accent line
- text: bright cool white
- secondary text: slate gray

Best for:
- now playing
- immersive nighttime usage

## Theme 4: Sepia Reader
Best as an optional reading-biased theme.

Mood:
- paper-first
- cozy
- low eye strain

Suggested direction:
- background: warm parchment
- surface: ivory / sand
- accent: muted olive or russet
- text: dark cocoa / near-black

Best for:
- ebook reading mode
- day sessions with long reading time

### Recommendation
Ship 2 first:
1. **Forest Audio** as app default
2. **Sepia / Play Books Light** as alternate reading-friendly theme

That gives strong contrast without overcomplicating the implementation.

---

## Concrete improvement plan

## Phase 1: Unify the visual system
1. Remove the hardcoded blue/white `#bookScreen` identity.
2. Convert book detail to the same token family as the library.
3. Add semantic color tokens instead of screen-local overrides.
4. Make bottom navigation a real tab bar with active state.

Highest-value code target:
- `dashboard/index.html:593-650`

## Phase 2: Rework the book detail hierarchy
1. Expand the hero.
2. Replace stacked CTAs with a continue-first action cluster.
3. Collapse or demote generation diagnostics.
4. Turn progress into richer visual summaries.
5. Improve chapter list row hierarchy and status treatment.

Primary targets:
- `dashboard/index.html:871-927`

## Phase 3: Clean settings UX
1. Move advanced technical copy into a collapsible “Advanced” section.
2. Remove redundant navigation.
3. Reword “not enforced yet” features as disabled or coming soon.
4. Add a simple theme selector here once app theming exists.

Primary targets:
- `dashboard/index.html:930-950`

## Phase 4: Add app-wide theme support
1. Put a `data-theme` attribute on `body` or `.app-root`.
2. Define token sets per theme.
3. Persist chosen theme in app settings.
4. Keep reader-specific day/night reading appearance as a sub-setting, not the only theme mechanism.

## Phase 5: Improve playback and “continue” feel
1. Replace generic native-player framing with a stronger now-playing card.
2. Surface last position and current chapter more prominently.
3. Add chapter-level context to listen/read actions.

---

## Suggested IA for the redesigned book page

## Hero
- large cover
- title
- author
- completion summary
- favorite / overflow action

## Continue card
- Continue listening
- Continue reading
- last location summary
- maybe “current chapter / page”

## Quick actions
- Read
- Listen
- Bookmark
- Note

## Contents / chapters
- current chapter highlighted
- durations if available
- play/read affordances

## Notes and bookmarks
- merged or adjacent utility block

## Technical details
- generation state
- events
- chunk info

## Diagnostics
- collapsed by default

---

## Final recommendation

Do **not** redesign by inventing a completely new UI from scratch.

Instead:
- keep the current structure,
- unify it under one design system,
- stop the book screen from being visually separate,
- and re-prioritize the page around **reading and listening continuation** rather than **pipeline status**.

If you want the simplest guiding sentence for implementation, it is:

> Make the library feel like Spotify, make the reader feel like Google Play Books, and make the book page the bridge between them.

---

## Short version of the problem

Today the app feels inconsistent because:
- the **library** is dark green and media-like,
- the **book page** is light blue and dashboard-like,
- the **reader** is dark and content-first,
- and **technical pipeline details are too visually prominent** in the main user journey.

## Short version of the fix

Unify the app around:
- one token system,
- one app shell,
- one brand identity,
- a stronger continue-first book page,
- and optional app-wide themes layered on top.
