---
title: Module 12 — Owner Dashboard
type: module
module: 12
status: planned
updated: 2026-08-12
---

# Module 12 — Authenticated Dashboard (project owners & collaborators)

## Scope
Spec **B**, **B.2**, **B.4**, **B.5**, **B.6**. Everything behind login.

## Pages / routes
| Route | Page | Contents |
|---|---|---|
| `/register`, `/login` | Auth | Registration sets username, email, **role**, password (+ full name, optional company). On success → redirect to the user's profile, per the spec. |
| `/me` | **My Profile** | Name, role, company (editable), bio, avatar, public/private toggle (**B.5**), and the **Projects section** with status badges (active / inactive / delayed / completed) + **Create Project** button. |
| `/projects/new` | **Create Project** | The form: name, location (+ map picker), code initials + number → live `project_code` preview and availability check, deadline, worker count (skippable), public/private. |
| `/projects/:id` | **Project Folder** | The main workspace — see below. |
| `/projects/:id/devices` | **Devices** | Paired cameras, status, battery, last seen, face, weight, schedule, unpair. |
| `/projects/:id/members` | **Collaborators** | Invite by username/email with a role, change roles, remove (**B.6**). |
| `/invitations` | **Invitations** | Pending invites to accept/decline. |
| `/notifications` | **Notifications** | Inspection required, delays, offline devices, reports ready. |

## Project Folder page — exactly what the spec lists
1. **Estimated progress** — big ring + number, with "AI estimate" labelling.
2. **Timeline graph** — displayed vs expected curve.
3. **Deadline** + days remaining.
4. **Status** badge with the reason ("no captures in 16 days").
5. **Stage percentages** — the five bars; the fifth (Approval) shows a
   **"Mark as Inspected & Complete"** button when `awaiting_inspection`, and is otherwise
   visibly locked with the explanation that the last 20 % requires physical inspection.
6. **Recent images** — grid of the last weeks' uploads, each with GPS + timestamp, predicted
   stage + confidence, low-confidence/rejected badges, and a lightbox with detection overlays.
7. **Remarks** — feed of system + manual remarks; compose box (delay/weather/manual).
8. **Upload** button — blueprints / 3D renders / references (**for the AI to follow**; see the
   scope note below).
9. **Pair a Camera** button → the pairing modal (**B.2**).
10. **Report** button → modal for kind/format, then async generation (**B.4**).
11. **Devices** section — what cameras are connected to this folder.
12. **Members** section.

## Pairing modal (B.2) — the flow
```
[Pair an ESP32 Device]
  → choose face: Front | Front Diagonal (recommended) | Back | Back Diagonal
  → POST /projects/{id}/pairing-tokens
  → modal shows: QR code · 8-char code in large type · 15:00 countdown
                 · step-by-step: power the camera → join "GeoVision-Setup-XXXX"
                   → enter Wi-Fi + this code
  → modal listens on the WebSocket for device.paired
  → on event: ✅ "ESP_NG_00_FD paired" → schedule editor (capture times) → done
  → on expiry: "Code expired" + [Generate new code]
```
After pairing, the Devices section lists the camera with live status. This is the single
most demo-critical screen in the defense — make it feel finished.

## Critical implementation notes
- **Render permissions from the server.** `GET /projects/{id}` returns a `permissions` block;
  buttons are shown/hidden from it. Never re-derive permissions in the client, and never treat
  hiding a button as security — the API enforces it too.
- The `project_code` preview updates live and calls the availability check (debounced); on
  collision, show the server's suggestions as clickable chips.
- Optimistic updates for remarks and settings; roll back on failure.
- Approval is a **deliberate, confirmed action**: a confirmation dialog stating that this
  finalizes the project at 100 %, requires inspection notes, and is recorded against the
  user's name. It should feel weightier than a normal button.
- Distinguish **AI estimate** from **owner-confirmed** everywhere in the UI — the credibility
  of the whole system rests on the user never mistaking one for the other.
- Show the device secret/pairing code **once**, with a copy button and an explicit "you won't
  see this again" warning.
- Handle the sad paths visibly: no devices yet, no images yet, all captures rejected, device
  offline, model unavailable. Empty states are most of the perceived quality of a dashboard.

### Scope note — "upload references for the AI to follow"
In v1 the uploaded blueprint / 3D render is **stored, displayed, and included in reports**;
it is **not** consumed by the model. Making the AI compare captures against a blueprint is a
substantially harder research problem (plan registration, viewpoint alignment) and is
recorded as future work in [[Open-Questions]]. State this scope boundary plainly in the
thesis rather than implying the model uses the render.

## Dependencies
Modules 11, 05, 10, 14. `react-hook-form`, `zod`, `qrcode.react` (display only), `sonner`.

## How to run
```bash
cd dashboard && npm run dev
# log in with a seeded account from scripts/seed_db.py
```

## Testing procedure
1. Register → redirected to `/me` showing the chosen name and role (spec behavior).
2. Create a project → appears in the profile's Projects section with a status badge.
3. Duplicate code → inline error + clickable suggestions.
4. Pair flow: issue token → run `simulate_device.py --code <code>` → the modal closes on the
   WebSocket event and the device appears.
5. Upload a blueprint → listed in assets, visible in the report.
6. Write a remark → appears immediately.
7. Report → 202 → toast on `report.ready` → download.
8. Force a project to 80 % → approval CTA appears; approve → 100 % + `completed`.
9. Viewer-role account → read-only UI, no action buttons; direct API call still 403.
10. Toggle profile private → log out → profile shows the private notice.
11. Playwright: full owner journey — register → create → pair → simulate uploads → watch
    progress rise → generate report → approve.

## Expected output
A complete owner experience matching spec section B, demoable end to end in under five
minutes with the device simulator.

## Done criteria
- [ ] Register → profile redirect; profile editing and public/private toggle
- [ ] Create Project with live code validation
- [ ] Full Project Folder page with all 12 elements above
- [ ] Pairing modal with QR, code, countdown, and live pairing confirmation
- [ ] Devices, members/collaboration, remarks, assets, reports, approval
- [ ] Permission-driven UI; empty and error states designed

## Related
[[Module-11-Public-Dashboard]] · [[Device-Pairing-Protocol]] · [[Roles-and-Permissions]] · [[Module-14-Realtime]]
