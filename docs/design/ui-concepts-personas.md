---
kind: "doc"
name: "ui-concept-sketches-eight-more-audiences"
description: "Eight self-contained HTML persona mockups for willow-mcp, each rendering the same underlying facts through a different technical subculture's authentic visual language."
---

@markdownai v1.0

# UI concept sketches — eight more audiences

Companion to `ui-concepts.md` (dev-facing + general-audience tree mockups).
Same idea, pushed further: eight more self-contained HTML files, each
showing the *exact same underlying facts* — 369 tasks, 357 failed, 5
agents, 2 of 4 schema tables confirmed, the store-isolation gap, etc. —
through a different technical subculture's authentic visual language. No
build step, no dependencies; open any file directly in a browser. Design
sketches, not wired to a real `willow-mcp` instance.

The premise, per file, isn't "retro theme" — it's "what does this specific
audience need to see to trust the tool," authentically executed in that
audience's own real chrome conventions, not a modern reinterpretation of
them.

| File | Persona | What it's optimized for |
|---|---|---|
| `willow-sco-cde.html` | Classic enterprise Unix / SCO OpenServer, CDE | Motif-beveled windows, deep-blue titlebars, formal admin-console labels ("System Status," "Process Queue"). Legitimacy through institutional seriousness. |
| `willow-turbo-cpp-dos.html` | Turbo C++ / DOS text-mode IDE | EGA blue, double-line box-drawing art, real function-key hotbar, data rendered as literal C struct assignments (`sap.failed = 357;`). Closeness to the metal. |
| `willow-linux-ricer.html` | Tiling-WM / r/unixporn dotfiles | Catppuccin Mocha, Polybar-style top bar with workspace pips, a neofetch-style summary block, thin borders, sharp corners. Environment as identity. |
| `willow-mac-native.html` | Mac user, platform-as-promise | SF Pro/SF Mono, traffic-light chrome, sidebar vibrancy blur, full light **and** dark themes (this audience notices immediately if dark mode is naive or missing). Trust through polish. |
| `willow-windows-mmc.html` | Enterprise IT / Windows admin | Classic MMC three-pane console (tree / details / actions), Segoe UI, Fluent-light palette, ListView-style tables. Looks managed, not personal. |
| `willow-saas-dashboard.html` | Funded-startup SaaS | Vercel/Linear house style — near-black, one accent color, `rounded-lg` cards, tabular-nums stat tiles. The one file where that look is the deliberate target, not the cliché to avoid. Also the second file (after `willow-dev-tui.html`) with an **Egress** card for the stomata/gates layer — see `ui-concepts.md`. |
| `willow-vim-buffer.html` | Vim/Emacs power user | Gruvbox dark, near-zero chrome, a line-number gutter, all state packed into one inverted bottom statusline. Decoration reads as condescending to this audience. |
| `willow-bbs-ansi.html` | Dial-up BBS / ANSI art culture | Full 16-color ANSI palette on black, numbered SYSOP-voiced main menu, CRT scanline overlay, a skippable connect-handshake sequence. Warmth through obsolescence. |

All eight respect `prefers-reduced-motion` wherever they animate anything
(cursor blinks, CRT flicker, a status-dot pulse) and give every interactive
element a visible focus state. Single fixed palettes are correct and
expected for the period-specific personas (SCO, DOS, BBS, Vim, ricer,
SaaS) — only the Mac variant implements a full light/dark toggle, because
that's the one persona that would treat a missing dark mode as a defect.

Same use case as the first pair: not a spec, a palette/chrome/information-
density menu to pull ideas from when a real client UI direction gets
picked.

## Known gap: stomata / the gates layer

`willow-dev-tui.html` and `willow-saas-dashboard.html` are the only two of
the ten mockups with a slot for authorization state (consent, `task_net`,
egress leases, manifest permissions — collectively "stomata," see
`ui-concepts.md`). The other eight — SCO/CDE, Turbo C++/DOS, the ricer, Mac,
Windows MMC, Vim, BBS, and the general-audience file — predate `willow-mcp
gates` and don't represent it at all. That's a real hole, not a stylistic
choice: an operator using any of those eight personas today would have no
visual answer to "is this app allowed to do the thing it's trying to do, and
for how long." Worth closing the same way the first two were, when one of
these personas is picked for real.
