# Demo Recording Notes

Pre-flight checklist before hitting record.

## Environment

- [ ] Browser: Chrome / Edge, zoom 125%, full-screen mode
- [ ] Window size: 1920×1080 (record at this resolution)
- [ ] Hide bookmarks bar, cookie banners, notification dots
- [ ] Test audio: input level peaks at -6 dB, no clipping
- [ ] OBS scene preset: 1080p, 30fps, hardware H.264

## Platform state

- [ ] Railway deploy live at `https://<your-domain>/health` → 200
- [ ] SepsisGuard MCP server registered, FHIR Context Extension ON
- [ ] All 15 SMART scopes "Select All" authorized
- [ ] SepsisGuard ICU Co-Pilot agent saved + published
- [ ] 3 patients imported (CAP, UTI, intra-abdominal)
- [ ] **Toggle "Show Tool Calls" ON** in Launchpad — the entire video hinges on this

## Take order

1. **Act 1** (0:00–0:30) — voice-over with static title cards. Easiest take.
2. **Act 2 Scene 1** (0:30–0:50) — Configuration → MCP Servers screen.
3. **Act 2 Scene 2** (0:50–1:25) — CAP patient live workflow. **Re-take until all 7 tools fire visibly.** The agent loop takes ~90 seconds — record once, edit to fit the time budget.
4. **Act 2 Scene 3** (1:25–1:50) — UTI patient. Focus the camera on the tool calls that demonstrate free-text reading. Same edit strategy.
5. **Act 2 Scene 4** (1:50–2:10) — Negative case. **You may need to manually create a post-op patient** with elevated temp but no infection (not in `data/examples/`). Alternative: voice-over the safety property without showing a third demo.
6. **Act 3** (2:10–2:50) — voice-over over the published Marketplace listing.

## Editing notes

- Speed up the tool-trace playback 1.5× during Act 2 so the 90-second agent loop fits in the time budget.
- Add lower-thirds for stats in Act 1: "$60B / yr — AHRQ HCUP", "Recall 0.33 — JAMA 2021", "FY2026 — Hospital VBP".
- Insert a brief title card between Scenes 2 and 3 ("Now the hard case →") so viewers know we're switching patients.
- Audio: light intro music at -28 dB, voice at -12 dB.

## Things to avoid

- **No PHI on screen.** Synthetic patient data only. Triple-check before publishing.
- **Don't show your Anthropic API key** in any terminal or env panel.
- **Don't show personal info** in the Prompt Opinion account profile.
- **Don't deep-link to internal Configuration pages** that might expose other workspaces.

## Final-cut checklist

- [ ] Length ≤ 3:00
- [ ] Resolution 1080p
- [ ] Captions verified for accuracy on technical terms (SEP-1, lactate, MAP, etc.)
- [ ] CTA at end with GitHub URL on screen for ≥ 3 seconds
- [ ] Upload **unlisted** to YouTube
- [ ] Copy URL into `SUBMISSION.md`
