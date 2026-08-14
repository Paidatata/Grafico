# Live Chart Centering & Sidebar Grouping — Design

**Date**: 2026-08-14
**Status**: Approved for implementation

## Problem

The chart currently loads scrolled to its leftmost edge (04:00) and never
moves on its own — the dispatcher has to manually scroll to find "now" every
time they open the page. The sidebar is a single flat list ordered by
insertion (roughly departure time), mixing both directions together, so
finding a specific train means scanning the whole list. Hovering a train's
line shows one tooltip near the cursor, not a label at each stop. There is no
way to see, at a glance, which trains are currently mid-journey.

## Goals (this phase)

- The chart auto-centers on the current time and keeps recentering as time
  passes, without the dispatcher having to touch anything.
- The dispatcher can still freely drag nodes or scroll to any other part of
  the chart; auto-centering steps out of the way while they do, and comes
  back on its own once they stop.
- The sidebar list is split by the real field naming convention (the P/R/M
  `train_code` scheme added in the previous phase — see `parser.py`'s
  `compute_train_codes`) so odd-numbered (destino BFU) and even-numbered
  (destino RGS/Mauá) trains are visually separated, one on each side of the
  chart.
- Both side lists only show trains currently in transit at whatever time is
  centered in the chart — a live, at-a-glance "who's running right now" view
  that follows the chart if the dispatcher scrolls it elsewhere.
- Hovering any train's line shows its code and time directly at every stop
  node, not just in a single cursor-following tooltip.

## Non-goals (out of scope this phase)

- Any backend/API change — every field this needs (`train_code`, `start_time`,
  `end_time`, `stops[].time`) is already returned by `GET /api/schedule`.
- Automated frontend tests — this repo has none (see CLAUDE.md); verified via
  `node --check`, standalone Node numeric-verification scripts, and updated
  `frontend/tests/manual_test.md` scenarios, matching how prior frontend
  fixes in this repo were verified.
- A user-facing "jump to now" button — not asked for; the 30s idle auto-resume
  covers returning to live tracking.
- Configurable tick/idle intervals — the 15s tick and 30s resume threshold are
  hardcoded per the explicit numbers given.

## The "reference time" model

The vertical line's on-screen position is always fixed at the horizontal
center of the chart viewport — it never moves. What moves is the chart
content underneath it. The "reference time" is *derived*, not stored: it's
whatever time is under the viewport's horizontal center right now
(`xToTime(scrollLeft + clientWidth / 2)`).

- Every 15s, if the dispatcher hasn't interacted recently, the chart smoothly
  scrolls so the *real current clock time* lands back at center — this is
  what makes the line track "now" and the chart appear to crawl left under it.
- If the dispatcher scrolls the chart manually (scrollbar, wheel, trackpad,
  keyboard) or starts dragging a node, auto-centering pauses. It resumes 30s
  after the last such interaction.
- While auto-centering is paused and the dispatcher has scrolled elsewhere,
  the reference time is simply whatever time is now centered — the line's
  label reflects that, and the two sidebar lists filter to trains in transit
  *at that time*, not at the real current time. Scroll to 9:45, see who's
  running at 9:45.

## Sidebar split

Trains are split by `train_code` parity into two independent panels flanking
the chart:

- **Left** — codes starting with `P` (destino Barra Funda), sorted by number
  ascending (equivalent to departure order, since `parser.py` already assigns
  P-numbers in departure order).
- **Right** — codes starting with `R` or `M` (destino RGS / Mauá), same sort.

Each panel keeps its own search box (filters only its own list) and trip
count badge. Both panels are, in addition to the existing per-line tab filter
(Linha 10 / 7 / 710), filtered live to only the trains in transit at the
current reference time (see above) — recomputed on every chart scroll and
every 15s auto-tick.

"Mostrar Realizado" and "Resetar" move to the header, since they act on the
whole chart / the globally selected trip, not on either specific list —
having them live inside one of the two side panels would be misleading.

## Hover node labels

Hovering any train's polyline (selected or not) draws a small label —
`{train_code} {HH:MM}` — next to every one of that stop's nodes for the
duration of the hover, in addition to the existing cursor-tooltip. Cleared on
mouseout. This is separate from the selected trip's permanent draggable
circles, which are unaffected.

## Explicitly out of scope for "interaction pauses auto-scroll"

Selecting a trip from the sidebar list also scrolls the chart (existing
behavior, unchanged) but does **not** count as an interaction that pauses the
auto-scroll clock — only an active node drag or a genuine (non-programmatic)
chart scroll do. This was a deliberate scoping decision: the user's answer
named exactly those two triggers.
