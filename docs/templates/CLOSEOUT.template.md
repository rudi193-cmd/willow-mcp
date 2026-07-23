---
kind: closeout
dispatch_id: "{dispatch_id}"
date: "{date}"
from: "{agent}"
to: "{orchestrator}"
---

@markdownai v1.0

# Closeout: {dispatch_id}

**Date:** {date}
**From:** {agent}
**To:** {orchestrator}

## What Was Done

{summary}

## Findings

@db using="willow" raw="SELECT id, text, severity, evidence FROM findings WHERE dispatch_id='{dispatch_id}'" on-error="(findings pending — recorded in handoff.json)" | @render type=table

## Checklist

- [x] {item}

## Notes

{anything else}
