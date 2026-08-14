---
title: Module 11 — Public Dashboard
type: module
module: 11
status: done
updated: 2026-08-15
---

# Module 11 — Public Dashboard (visitors, not logged in)

## Scope
Spec **A**. Everything an anonymous visitor can reach. Built first because it is the simplest
complete vertical slice of the UI and it forces the visibility rules to be right.

## Pages / routes
| Route | Page | Contents |
|---|---|---|
| `/` | **Homepage feed** | Cards of public projects: latest image thumbnail, project name, intended use, location, **GPS coords**, **timestamp of the last image**, progress ring, macro stage, status badge, owner name. Filters: stage, status, near-me, sort by recent/progress. |
| `/projects/:code` | **Public Project Folder** | Hero image + progress ring, five stage bars, **timeline graph**, deadline, status, project handler (linked if their profile is public), public remarks, recent geotagged images, map + **"Open in Maps"** external link. |
| `/users/:username` | **Public Profile** | Name, professional role, company, bio, public projects with their roles — or the private-account state. |
| `/search` | **Search** | Tabs: Owners · Projects · Locations. Debounced, typed results. |
| `/contact` | **Contact Us** | Form + submission confirmation. |
| `/login`, `/register` | **Auth** | Login and the registration form (username, email, role, password, full name, optional company). |
| `*` | 404 | |

## Key components
- `ProjectCard`, `ProgressRing`, `StageBars` (five segments; the fifth visually distinct as
  the human-approval stage), `TimelineChart` (Recharts area/line over
  `project_progress_snapshots`), `ImageStrip` (thumb + GPS + timestamp overlay),
  `MiniMap` (MapLibre marker), `MapLink`, `StatusBadge`, `SearchBar`, `PrivateAccountNotice`,
  `EmptyState`, `SkeletonCard`.

## Critical implementation notes
- **The public API is the only source.** Public pages call `/public/*` exclusively; if a
  private field ever renders, that is a backend bug, and there should be a test proving the
  payload never contains it.
- The private-profile page renders **only** the username and "This account is private" —
  no project count, no avatar, no join date.
- A project owned by a private-profile user still appears in the feed, but the owner's name
  is plain text, not a link. Handle this case explicitly; it is easy to miss.
- Timeline chart must handle sparse data (gaps in captures) — plot actual points with gaps,
  don't interpolate a straight line through a two-week silence and imply data that isn't there.
- Show the **relative age** of the latest capture ("2 hours ago") next to the absolute
  timestamp — staleness is the most decision-relevant fact on the card.
- Coordinates displayed to 6 decimals with a copy button; the map link opens in a new tab.
- Fully **responsive** — a site engineer will open this on a phone at the site.
- Accessibility: progress conveyed by text and not by color alone; status badges have labels;
  all images have alt text derived from project + stage + date.
- SEO/social: `react-helmet-async` per-project OG tags (a public monitoring site should be
  shareable).

## Dependencies
Modules 04, 09 (for real progress data). `react`, `react-router-dom`, `@tanstack/react-query`,
`recharts`, `maplibre-gl`, `tailwindcss`, `date-fns`.

## How to run
```bash
cd dashboard && npm run dev      # http://localhost:5173, VITE_API_URL=http://localhost:8000
```

## Testing procedure
1. Feed loads with seeded public projects; private projects are **absent**.
2. Direct-URL a private project code → friendly not-found page (API returned 404).
3. Public profile renders; private profile shows only the notice.
4. Search returns owners, projects, and locations; empty query shows guidance, not an error.
5. Timeline renders with 30 days of snapshots; a 1-point project renders without crashing;
   a 0-point project shows an empty state.
6. Map link opens the correct coordinates.
7. Contact form validates and submits.
8. Component tests (Vitest + RTL) for `ProgressRing`, `StageBars`, `PrivateAccountNotice`.
9. Playwright: visitor journey — homepage → project → owner profile → search → login page.
10. Lighthouse: performance ≥ 85, accessibility ≥ 95.
11. Responsive check at 375 px, 768 px, 1440 px.

## Expected output
A visitor with no account can browse public construction projects, open one, see its
progress, timeline, and last geotagged capture, click through to the map, view the handler's
public profile, search, and register — matching spec section A exactly.

## Done criteria
- [x] All public routes implemented and responsive
- [x] Visibility rules provably respected in the UI
- [x] Timeline + stage bars + progress ring correct against seed data
- [x] Search and contact working
- [ ] E2E visitor journey passes — *Playwright deferred to [[Module-15-Testing-and-Evaluation]], which owns the browser suite*

## Delivered (2026-08-15)

| Route | Page |
|---|---|
| `/` | feed, with URL-backed filters (q, status, stage) |
| `/projects/:code` | progress ring, five stage bars, timeline, captures, remarks, handler, map links |
| `/users/:username` | public profile, or the private-account notice |
| `/search` | tabs over projects, owners, locations |
| `/contact` | form with success and failure states |
| `/login`, `/register` | honest placeholders — Module 12 owns auth |
| `*` | not-found |

**19 component tests**, TypeScript strict with `exactOptionalPropertyTypes`, ESLint clean.

The tests that matter are the ones about **what a visitor is told**: that the figure is
labelled "AI estimate" and only says "Verified" at 100 %; that the Approval bar explains it
requires an inspection; that a private profile renders exactly two lines and nothing else
(asserted on `textContent`, so a future field cannot slip in); and that a private project
reads as *"not available"* rather than as an error — a visitor must not be able to tell a
private project from one that never existed.

**Bundle, after code-splitting:** the landing page is **77 kB gzipped**; the project page's
chart chunk (110 kB gzipped, almost all Recharts) loads only when someone opens a project.
The chart lives in its own module for exactly this reason — importing it from the shared
component file pulled Recharts into the homepage, which was 186 kB before the split.

**Two backend gaps this module surfaced and one it fixed.** Fixed: image payloads carried
`thumb_key`, a storage key no browser can render, so nothing could display a photograph
anywhere — they now carry a signed `thumb_url`. Open (Q13): the feed omits `owner` and
`latest_image`, and search returns no locations index.

**`MiniMap` was not built.** MapLibre is ~200 kB for an embedded tile view of a single pin,
on a page that already links out to Google Maps and OpenStreetMap and shows copyable
coordinates. The dependency was removed rather than left unused; revisit in Module 12, where
an authenticated folder showing several cameras has more to put on a map.

## Related
[[Roles-and-Permissions]] · [[API-Contract]] · [[Module-12-Owner-Dashboard]] · [[Construction-Stages]]
