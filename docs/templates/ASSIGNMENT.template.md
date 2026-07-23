---
kind: assignment
title: "{title}"
from: "{orchestrator}"
to: "{agent}"
role: "{role}"
priority: normal
dispatch_id: "{id}"
reply_to: "{reply_to}"
---

@markdownai v1.0

# Assignment: {title}

**From:** {orchestrator}
**To:** {agent}
**Persona / role:** {role}
**Priority:** {high | normal | low}
**Dispatch ID:** {id}
**Reply to:** {reply_to}

## Bite

One sentence — the single outcome.

## Checklist

- [ ] {item}
- [ ] {item}

## Context

- {link or reference}

## Success criteria

- {what done looks like}

@constraint severity=error
Out of scope:

- {what you must not do}
