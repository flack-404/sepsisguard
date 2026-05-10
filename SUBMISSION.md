# SepsisGuard — Devpost submission

> Skeleton. Final copy will be filled in before submission per `SEPSISGUARD_BUILD_SPEC.md` §19.

## Tagline

Multi-agent SEP-1 bundle co-pilot — watches the ICU, drives the bundle, documents the case.

## Inspiration

Sepsis is the **#1 most expensive condition** in US hospitals — $60B/year, 350,000 deaths annually (AHRQ HCUP, CDC). Yet the deployed industry leader, the Epic Sepsis Model, was published in *JAMA Internal Medicine* missing two-thirds of cases while alerting on 18% of all admitted patients. CMS just made SEP-1 a pay-for-performance measure under Hospital Value-Based Purchasing (FY2026). The market needs a new approach.

## What it does

_TODO: 3 paragraphs walking through the 5 agents + 7 tools._

## How we built it

_TODO: Both Superpower (MCP server, 7 tools) and Superhero (A2A v1 agent) in one Python service. Anthropic `claude-opus-4-7` with prompt caching. FHIR R4. SHARP-on-MCP._

## Why this wins on judging criteria

_TODO: bullet each criterion (impact, AI factor, feasibility, alignment with SHARP/A2A/Prompt Opinion)._

## Standards we actually implement

_TODO: CMS SEP-1, Surviving Sepsis Campaign 2021, FHIR R4, US Core 6.1, SMART App Launch v2, MCP, A2A v1._

## Built with

Python 3.12 · FastAPI · Anthropic Claude API · FHIR R4 · MCP · A2A v1 · SHARP-on-MCP · Railway

## Try it yourself

```bash
git clone <repo>
cd sepsisguard
pip install -r requirements.txt
python -m sepsisguard.demo --scenario all
```

## What's next

_TODO: production deployment, multi-hospital rollout, post-acute extension._
