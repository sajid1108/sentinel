# Brief: "Try an order" on the live landing page (recorded grid)

**Goal.** The live site (https://sajid1108.github.io/aegisshift/, public repo `sajid1108/aegisshift`, copy in `landing/`) is static and has no server. Add a "Try an order" section to it that answers from a **grid of real API responses recorded ahead of time**. No backend change and no app change.

Progress line: `PROGRESS  landing try  [####------]  <step> — N of 4 steps done  |  elapsed XhYYm`

## 1. Define the grid (from the data, not hand-typed)
- Axes come from `GET /internal/demo/order-builder`: 6 accounts × 3 devices × 3 tokens.
- Cart: take the inputs the Phase 10 form offers (`frontend/src/lib/tryOrder.ts`) and reduce each free input to a small fixed set, for example category (6) × a few order-value bands × payment method. Aim for about 2,000 combinations or fewer. State the exact grid in the report.
- The site may offer **only** combinations that are in the grid. There's no interpolation and no "nearest" answer.

## 2. Record
- Write `scripts/record_try_grid.py`. It runs against a **copy** of a freshly seeded `sentinel.db` with the local API. For each combination it calls the public checkout once and then reads the decision (no second scoring call), as the Phase 10 panel does.
- Save a compact file, `landing/try-grid.json`, keyed by combination. Each entry holds: the shopper outcome text, action, p_abuse, the counted signals, the expected cost per action, and the top reason codes with the text the reviewer sees. Include `recorded_at` and the git SHA. The file must stay under 3 MB; drop fields before you drop combinations.
- **Order independence check:** score 20 random combinations again at the end. Every value must match the first pass exactly. If any differs, stop and report; don't paper over it.
- Leave the real `sentinel.db` untouched.

## 3. Landing section
- Add a section to `landing/index.html` that fits the existing look (read the page first). Use plain JS with no new libraries: form selects filled from `try-grid.json`, and a result showing "what the shopper sees" next to "what the reviewer sees".
- Put this notice above the form, word for word: **"Answers are recorded from the real model and policy, not computed live. Every combination here was scored ahead of time."** Keep the exact synthetic-data notice from `ARCHITECTURE.md` §1 on the section.
- Labels: use the Phase 11 wording now. The device option is "Another account's device (strongest evidence)" and the token option is "Another account's token (strongest evidence)". Never say "ring" in an option label.
- **Honesty rules:** show the Demo 1 case with another account's device and token as it recorded. It stays ALLOW, and the site says why in one sentence: "The evidence registers, but one shared device or token doesn't outweigh years of clean history." Don't pick or reorder combinations to make BLOCK look common. The default selection is Demo 1's own order.
- Check it at 375, 1280 and 1440 widths: no horizontal scroll, and the tree videos still sync. Save screenshots to `docs/reports/landing-try/`.

## 4. Ship
- Commit `landing/` and the script to this repo (`main`). Copy `landing/` to a clone of `sajid1108/aegisshift` and push it there. Confirm the live URL serves the new section; GitHub Pages may take a minute.
- Write `docs/reports/landing-try.md` covering: the grid, the file size, the order-independence result, how many combinations came out ALLOW, MANUAL_REVIEW and BLOCK, the screenshots, and anything you changed on the page beyond the new section.
- No co-author trailer on any commit. Stop at the gate.
