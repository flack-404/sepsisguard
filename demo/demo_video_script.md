# Demo Video Script — SepsisGuard (3 minutes)

**Hosting:** YouTube, unlisted. Link goes in the Devpost submission.

## Pre-recording checklist

- [ ] Railway deployment live (`/health` returns 200)
- [ ] SepsisGuard MCP server registered in Prompt Opinion workspace
- [ ] SepsisGuard ICU Co-Pilot agent published in Marketplace
- [ ] Three sepsis patients imported into workspace (`data/fhir_bundles/`)
- [ ] Toggle "Show Tool Calls" ON in Launchpad
- [ ] Browser zoomed to ~125% so text is video-legible
- [ ] OBS or Loom set to 1080p
- [ ] Audio levels checked

## Script

### Act 1 — The wound (0:00–0:30)

*[Open with a static title card: "SepsisGuard — Agents Assemble"]*

> Sepsis is the **number-one most expensive condition** in US hospitals — sixty billion dollars a year, three hundred fifty thousand deaths.
>
> The deployed industry leader, the Epic Sepsis Model, was published in JAMA Internal Medicine **missing two-thirds of cases**. Its alert burden is eighteen percent of all admitted patients.
>
> CMS just made SEP-1 a **pay-for-performance** measure under Hospital Value-Based Purchasing for fiscal year 2026. The market needs a new approach. We built SepsisGuard.

### Act 2 — The cure (0:30–2:10)

#### Scene 1: Setup (0:30–0:50)

*[Switch to Prompt Opinion Configuration screen → MCP Servers]*

> SepsisGuard is registered on Prompt Opinion as an MCP server — seven clinical tools exposed at slash-MCP. The FHIR Context Extension is on, all fifteen SMART scopes authorized. The A2A v1 agent card declares three skills.

#### Scene 2: The canonical case (0:50–1:25)

*[Switch to Launchpad → CAP patient → SepsisGuard ICU Co-Pilot agent]*

> Here's a sixty-seven-year-old with community-acquired pneumonia. Heart rate one-eighteen, lactate three-point-two, hypotensive. Watch the tool trace.

*[Send the prompt; let the tool calls play out on screen]*

> Tool one — **screen_sepsis_signals** — pulls vitals, labs, conditions, nursing notes. SIRS four-out-of-four. qSOFA two. Free-text trigger from the admit note.
>
> Tool two — **confirm_sepsis_diagnosis** — Claude reads the screening packet. Classification: severe sepsis, high confidence. Time Zero established.
>
> Tools three through five — **score**, **recommend**, **drive** — the bundle math runs, the antibiogram surfaces cefepime plus vancomycin, five FHIR Tasks are created in the EHR with three-hour deadlines.
>
> Tool six — **notify_care_team** — Communication resource sent to the bedside nurse and intensivist.
>
> Tool seven — **draft_sep1_documentation** — Claude produces a CMS-abstractor-grade progress note with every claim back-referenced to a FHIR resource. Predicted CMS score: zero-point-seven-eight.

#### Scene 3: The hard case (1:25–1:50)

*[Switch to UTI patient]*

> Same agent, harder case. Seventy-eight-year-old post-op-day-four, Foley still in. Vitals are borderline. Lactate two-point-four. There is **no infection-coded Condition** — the diagnostic information is in the nursing note: "patient confused, more lethargic, cloudy urine, sediment."
>
> The Epic Sepsis Model misses this case because it can't read text. SepsisGuard's screen catches the free-text triggers, the Adjudicator reads the nursing note and the urinalysis report and confirms severe sepsis from a urinary source.
>
> And — note this — the patient has a penicillin allergy. The Pharmacist substitutes cefepime for piperacillin-tazobactam and cites the under-two-percent cross-reactivity literature. That's not a rule. That's clinical reasoning the LLM brings.

#### Scene 4: The safety property (1:50–2:10)

*[Switch to a post-op patient with elevated temp but no infection]*

> One more: a post-op patient with a temperature of thirty-eight-point-six. Looks like sepsis. Isn't.
>
> The Adjudicator considers the alternatives — post-op fever, alcohol withdrawal, anaphylaxis — and returns `sepsis_likely_benign_alternative`. The bundle does NOT execute. No false alerts. No fabricated treatments.
>
> This is the safety property that lets a system like this ship.

### Act 3 — The math (2:10–2:50)

> **Per case:** Surviving Sepsis Campaign says every hour of antibiotic delay costs four to seven percent mortality. SepsisGuard closes that gap.
>
> **Per hospital:** A three-hundred-bed hospital recovers two-to-three million dollars a year in SEP-1 VBP compliance.
>
> **Per CMS rule:** SEP-1 is live in Hospital VBP fiscal year twenty-twenty-six. **Deployable today**.
>
> The Marketplace listing is published. The code is open source, Apache two-point-oh. The hammer is forged. The superhero is assembled.

*[Final card: SepsisGuard logo + GitHub URL + Apache 2.0]*

> **SepsisGuard.** Watch the ICU. Drive the bundle. Document the case.

---

## Total runtime target: 2:50 (max 3:00)

## Filming notes

- Record the platform integration with the agent visibly making tool calls — judges have repeatedly said the "Show Tool Calls" toggle is what they look for.
- Don't show the Claude system prompts on screen — keep the surface visual focused on platform UI and tool outputs.
- Use captions / lower-thirds for the key statistics in Act 1.
- The Act 3 voiceover can play over the agent_card.json + Marketplace listing UI.
- For the Devpost thumbnail: a screenshot of the agent's final summary panel with the predicted CMS score highlighted.
