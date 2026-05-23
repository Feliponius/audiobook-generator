# Audiobook Library Web App PRD

## Product name
Working name: **Audiobook Library**

## Product vision
Turn the current utilitarian audiobook monitor into a polished, mobile-first personal reading and listening app that feels like a real product instead of an ops dashboard.

The app should let Philip upload EPUBs, keep them in a visually appealing personal library, read them in-browser, convert them to audiobooks with the existing Kokoro-based pipeline, and then listen with strong resume behavior and low babysitting overhead.

## Background
The current application is a single-run operational monitor served by `monitor_server.py` with a static `dashboard/index.html`. It exposes run status well enough for development, but it is not organized around a library, persistent reading/listening state, or a consumer-grade mobile experience.

Current strengths to preserve:
- Existing EPUB-to-audiobook pipeline in `epub_to_audiobook.py`
- Existing dual Kokoro worker flow
- Existing HLS/live playback concept
- Existing tailnet-only deployment model
- Existing script-first cleanup preference and Kokoro-centric narration workflow

Current pain points to solve:
- UI feels like a monitor, not a product
- Color system is too blue/gray and not visually aligned with desired softer green aesthetic
- No library model for uploaded books
- No in-browser EPUB reading experience
- No user-friendly start/process controls
- Weak persistence for resume, bookmarks, notes, favorites
- HLS playback is currently broken due to playlist segment URL resolution
- Too much operator babysitting

## Product goals
1. **Beautiful mobile-first experience** with modern cards, softer green brand styling, and better visual hierarchy.
2. **Library-first workflow** where uploaded books persist and are browsable independently of conversion runs.
3. **Two core experiences in one app**:
   - Read EPUB in-browser
   - Listen to audiobook as it is generated or after completion
4. **Low-ops behavior** with simple start buttons, clear status, and minimal babysitting.
5. **Stateful personal usage** with resume position, bookmarks, notes, favorites, and clip/share support.
6. **Pipeline reuse, not rewrite** by building on the existing scripts and Kokoro flow.
7. **Single-user tailnet trust model** with no login screen.

## Non-goals
- Multi-user accounts or role-based auth
- Public internet exposure
- Marketplace/discovery/social network features
- Replacing Kokoro as the main TTS engine
- Cloud storage architecture for arbitrary external users
- Full digital-rights-management or commercial distribution workflows

## Target user
Primary and only supported user for this phase:
- Philip, using Android/mobile-first access over tailnet
- Wants practical but attractive UX
- Wants automation and low maintenance
- Wants reading + listening in the same product

## Design direction
### Visual style
- Replace blue-gray palette with a softer green-led palette.
- Preferred direction: **sage / jade / emerald-muted** rather than neon or saturated lime.
- UI should feel modern, calm, polished, and premium.

### Suggested palette direction
Not final design tokens, but intended direction:
- Background: deep forest/spruce near-black
- Primary surface: dark jade/sage panel
- Accent: soft emerald / jade green
- Secondary accent: muted mint
- Text: warm off-white
- Status colors: retain clear success/warn/error contrast without clashing with the green theme

### Layout style
- Card-based
- Mobile-first
- Large touch targets
- Sticky bottom/primary actions where useful
- Cover-art-forward if metadata/cover exists
- Minimal operator jargon on primary surfaces

## Core user stories
### Library and upload
- As Philip, I want to upload an EPUB from the web UI so I do not need to handle pipeline commands manually.
- As Philip, I want uploaded books to appear in a personal library with title, cover, status, and quick actions.
- As Philip, I want to favorite books so I can quickly return to them.

### Book detail page
- As Philip, when I open a book, I want a clean book detail card/page showing title, progress, actions, and latest activity.
- As Philip, I want a clear action like **Start audiobook** or **Begin conversion**.
- As Philip, I want a built-in **Read with e-reader** action.

### Reading
- As Philip, I want to read the EPUB directly in-browser in a mobile-friendly e-reader.
- As Philip, I want reading position to persist.
- As Philip, I want to bookmark locations and make notes.

### Audiobook generation and listening
- As Philip, when I start audiobook generation, I want the system to begin conversion using the existing script/pipeline.
- As Philip, if text preparation has not already been completed for the book, I want the system to do the needed prep automatically.
- As Philip, I want to start listening once enough audio has buffered/generated that playback is practical.
- As Philip, I want playback position to persist after refresh/restart.
- As Philip, I want to pause, resume, and bookmark listening position.
- As Philip, I want to clip and share audio from a selected span.

### Voice and settings
- As Philip, I want to sample Kokoro voices before running a book.
- As Philip, I want a settings page where I can choose pipeline options used during conversion.
- As Philip, I want enough in-app control to troubleshoot or re-run common tasks without needing Hermes every time.

## Experience architecture
### Primary navigation
Recommended nav:
- **Library**
- **Now Playing / Continue**
- **Settings**

Optional if needed later:
- Activity
- Favorites

### Main screens
1. **Library page**
2. **Book detail page**
3. **Reader page**
4. **Player page** (may be embedded in book detail for MVP)
5. **Settings page**
6. **Upload flow / modal**

## Functional requirements

### 1. Library
The system must:
- Accept EPUB uploads from the browser
- Extract/store book metadata where possible:
  - title
  - author
  - cover image
  - source filename
- Persist a library catalog independent of transient run folders
- Display each book as a card with:
  - cover
  - title
  - author
  - favorite state
  - read/listen/conversion status
  - primary action
- Support sorting/filtering at minimum by:
  - recently added
  - recently opened
  - favorites
  - in progress

### 2. Book detail page
The system must provide a detail page for each book showing:
- metadata
- cover
- current conversion status
- latest listening progress
- latest reading progress
- action buttons:
  - Read with e-reader
  - Start audiobook / Resume processing
  - Play audiobook when available
  - Favorite / unfavorite
  - Notes / bookmarks access

### 3. Upload and processing workflow
The system must:
- Store the uploaded EPUB as the canonical source artifact
- Create a per-book workspace for derived metadata and state
- Reuse the existing `epub_to_audiobook.py` pipeline rather than replacing it
- Support starting a conversion job from the UI
- Track whether a book is:
  - not started
  - queued
  - preparing
  - generating audio
  - ready to play
  - failed
- Surface errors in a human-readable way on the book page

### 4. Reading experience
The system must:
- Provide in-browser EPUB reading, likely via an EPUB rendering library such as `epub.js`
- Persist reading position per book
- Support bookmarks in reading mode
- Support notes/annotations tied to reading locations
- Provide comfortable mobile typography and spacing

### 5. Listening experience
The system must:
- Support progressive listening during generation once sufficient audio exists
- Fix HLS playback so playlists resolve segment URLs correctly
- Persist listening position per book
- Allow explicit bookmarking of listening position
- Restore progress after browser refresh/server restart
- Provide a player suitable for mobile use
- Show whether the book is buffering, generating, or ready

### 6. Notes and bookmarks
The system must:
- Allow notes attached to a book
- Support at least two bookmark types:
  - reading bookmarks
  - listening bookmarks
- Persist note and bookmark data server-side
- Make bookmarks visible and manageable from the book detail page

### 7. Favorites
The system must:
- Allow books to be marked favorite
- Persist favorite state
- Support favorite filtering in the library

### 8. Audio clip/share
The system should:
- Allow creation of short clips from generated audiobook audio
- Support a share/export path

MVP assumption:
- Clip export can be file-based rather than social-native
- Sharing may be via generated downloadable clip, local file handoff, or link-based access rather than large email attachments

### 9. Settings
The settings page must expose configurable options for the pipeline at least for:
- Kokoro voice selection
- voice preview/sample playback
- worker count (within safe bounds)
- rewrite policy selection
- whether to use HLS/live playback mode
- output retention preferences
- optional chapter selection behavior in future phases

### 10. No-login trust model
The app must:
- have no login page for this phase
- assume access is protected by tailnet/network placement
- be explicit in implementation comments/docs that this is trusted-network single-user software

## Data and storage requirements
### Canonical source storage
Preferred storage model:
- Keep original EPUB files
- Keep lightweight metadata/state files
- Keep generated artifacts needed for playback and product UX
- Avoid keeping large WAV files long-term

### Audio retention policy
Requirement:
- WAV files should not be retained as the default long-term storage format

Preferred approach:
- Use compressed listening formats for retained audio (for example M4A/AAC and HLS segments)
- Treat WAV as transient/intermediate only
- Add cleanup policy to remove WAV after successful compressed-output generation and verification

### Persistent app data
Per-book persistent state should include:
- library metadata
- favorite state
- reading progress
- listening progress
- notes
- bookmarks
- clip metadata
- conversion settings used for the book
- current/last run status

Implementation can use JSON or SQLite; SQLite is preferred if it simplifies relational state and future extensibility.

## Technical constraints and assumptions
- Existing backend is a lightweight Python HTTP server with embedded static frontend
- Existing conversion pipeline must remain the execution engine for audiobook generation
- Existing dual Kokoro run should be preserved
- Tailnet/private-network deployment means auth can be skipped for this phase
- Android/mobile-first usage matters more than desktop-first optimization
- The app should remain operable without constant Hermes intervention

## UX requirements
### Library card UX
Each library card should aim to show:
- cover image
- title
- author
- progress chip(s)
- favorite icon
- one primary CTA

### Book detail CTA logic
Examples:
- If not started: **Start audiobook**
- If running: **View progress** / **Continue listening** if available
- If enough audio exists: **Play now**
- Always available: **Read with e-reader**

### Playback UX
- Mobile-usable seek bar
- Big play/pause controls
- Resume from last position automatically
- Manual bookmark action
- Optional sleep-timer is nice-to-have, not MVP

### Reading UX
- Clean typography
- Chapter navigation
- Resume where left off
- Bookmark and note actions

## Reliability requirements
- Refreshing the page must not lose progress state
- Restarting the web server must not lose saved reading/listening state
- Conversion jobs should be recoverable/inspectable after interruption
- UI should clearly separate transient generation state from permanent library state

## Observability/admin requirements
Because the app should reduce babysitting, it should still expose enough diagnostic info in a calmer way:
- recent processing events for a book
- current stage
- last error
- basic system state only when helpful

This should move behind secondary detail sections rather than dominating the primary experience.

## Suggested MVP scope
### MVP must include
- Polished green-themed mobile-first redesign
- Library page with upload
- Book detail page
- EPUB reader in-browser
- Start audiobook from UI
- Reuse existing pipeline
- Working HLS/live playback or equivalent progressive playback
- Persistent listening progress
- Persistent reading progress
- Favorites
- Bookmarks
- Settings page with Kokoro voice selection and sampling
- Reduced artifact retention with no long-term WAV default

### Post-MVP / Phase 2
- Notes UI refinement
- Audio clip/share flow
- Email/send workflow if practical
- Continue queue / background processing queue management
- More advanced troubleshooting/admin surfaces in-app
- Per-book voice overrides and batch operations

## Open implementation decisions
These do not block the PRD, but should be resolved during implementation planning:
1. **Persistence layer**: JSON files vs SQLite
   - Recommendation: SQLite for library/state, files for EPUB/covers/audio
2. **Reader engine**: `epub.js` or equivalent
   - Recommendation: `epub.js`
3. **Job execution model**: subprocess management inside Python app vs lightweight queue
   - Recommendation: start with subprocess orchestration compatible with current scripts
4. **Audio share transport**: downloadable clip, local share sheet, tailnet URL, or email handoff
   - Recommendation: downloadable clip first, delivery integrations later
5. **Player architecture**: HLS-first vs direct M4A fallback
   - Recommendation: HLS/live when available, M4A fallback when complete

## Recommended delivery phases
### Phase 1: Foundations
- Library data model
- EPUB upload and cataloging
- New visual design system
- Library + book detail pages
- HLS bug fix

### Phase 2: Read/listen core
- EPUB reader integration
- Conversion start flow
- Listening/player state persistence
- Reading position persistence
- Favorites/bookmarks

### Phase 3: Personal knowledge and control
- Notes
- Kokoro voice sampling
- Settings page
- Retention cleanup workflow

### Phase 4: Sharing and polish
- Audio clip/share
- richer continue flows
- stronger error recovery UX
- quality polish and performance improvements

## Acceptance criteria
The redesign is successful when:
- Philip can upload an EPUB from the browser
- The uploaded book appears in a polished library card grid/list
- Opening a book shows a modern detail card/page with clear actions
- Philip can read the EPUB in-browser
- Philip can start audiobook conversion from the UI
- Philip can begin playback before the full book is finished, assuming enough audio is available
- Playback position survives refresh/restart
- Reading position survives refresh/restart
- Favorites, bookmarks, and notes persist
- Kokoro voice choice can be previewed and configured in settings
- The app stores EPUB as the source of truth and does not retain WAV long-term by default
- The UI feels materially more polished and pleasant than the current monitor

## Implementation guidance for Cursor
Constraints for implementation work:
- Cursor must use **Composer 2 only**
- Preserve and build on existing scripts instead of replacing them wholesale
- Keep the app mobile-first
- Prefer incremental, reviewable changes
- Hermes may review and make direct corrective edits only if Composer 2 gets stuck or repeatedly misses the requirement
