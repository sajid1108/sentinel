# Demo script: live walkthrough (4 min) and video (≈3 min)

## Before you start (5 minutes, every time)

1. **Laptop clock on IST.** Timestamps render in IST regardless of the laptop, but check it anyway.
2. Start the backend. In `backend/`:

   ```bash
   .venv\Scripts\python -m sentinel.cli serve
   ```

3. Start the frontend. In `frontend/`:

   ```bash
   npm run dev
   ```

4. Open the app in the browser at **1440 × 900**, full screen, zoom 100 %. Go to **Queue** and click **Reset demo**, then **Confirm**. It takes about 7 s.
5. Close every other tab. Turn on Do Not Disturb.
6. Keep the backup video open in another window (see "If something breaks").

---

## Live walkthrough (4 minutes)

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00 | Overview | Point at the notice line | "Sentinel is a return-abuse risk manager. Everything you'll see runs on a synthetic world with fixed seeds, and every page says so." |
| 0:15 | Overview → backtest table | Point at the Sentinel and Fixed threshold rows | "We'll show you where we lose. A tuned threshold is cheaper than us on cost. We chose to pay that premium so that we block 3.3 times fewer genuine customers. It's a trade, not a win." |
| 0:40 | Queue | Click **ORD-DEMO-001** in Simulate checkout | "A checkout comes in. The real models score it and the real policy decides it." |
| 0:50 | Demo 1 detail | Point at the two score cards | "Two numbers, never combined. This customer returns 61 % of the time, shown in blue, and that is not used for the decision. Abuse probability is under 0.1 %." |
| 1:05 | Demo 1 baselines | Point at Rule based: **Block** | "A typical merchant rule would block this loyal, 3½-year customer. Sentinel allows the order." |
| 1:15 | Queue → **ORD-DEMO-002** | Click | "Now a 5-day-old account buying a ₹24,000 phone." |
| 1:25 | Demo 2 abuse card | Point at 95.1 % and the ghost marker | "95 % abuse probability. Without the relationship evidence it would score 9.9 % and pass." |
| 1:40 | Demo 2 graph | Point at the red nodes | "Its device was used by three accounts later confirmed for abuse. Its card was shared with three others. Linked accounts placed four orders in the last day. No single account looks suspicious; the ring only shows up across accounts." |
| 2:00 | Demo 2 cost bars | Point at BLOCK Selected, ALLOW hatched G5 | "All four actions are priced in rupees. Block is cheapest, and it is allowed only because two independent signals agree and confidence is above the floor." |
| 2:15 | Queue → **ORD-DEMO-003** | Click | "The hard case." |
| 2:20 | Demo 3 cost bars | Point at BLOCK hatched G3, MANUAL_REVIEW Selected | "69 % abuse probability, just under the 70 % blocking floor. But review wins on cost anyway: ₹1,858 against ₹4,052 to block. Uncertainty gets proportionate friction, not a refusal." |
| 2:45 | Demo 3 | **Override** → Prepaid only, Customer verified, type a reason, **Apply override** | "A reviewer verifies the customer and switches the order to prepaid." |
| 3:05 | Audit timeline | Point at the two events and **Chain verified ✓** | "A new audit event, hash-chained to the last one. The system's original recommendation can never be edited, and any tampering is detectable." |
| 3:25 | Queue | Point at the counts row | "The queue now shows the current action, after review." |
| 3:35 | (close) | — | "Models predict, policy decides, humans can override, and everything is recorded. Real deployment needs a merchant's own data and a prospective trial; we've built the architecture that makes that trial safe." |

**Timing rule:** if you are past 2:30 when you reach Demo 3, skip the Queue counts line.

---

## Questions judges will ask

| Question | Answer |
|---|---|
| "Why not just use a threshold? It's cheaper." | "It is, by ₹35k per 1,000 orders. It also blocks 3.3× more genuine customers, and it can't explain a block with evidence. Our guardrails cost about ₹9,211 per wrongful block avoided. That's a policy choice a merchant can see and change." |
| "The evidence panel and the attribution panel disagree on Demo 2." | "On purpose. Evidence lists facts: the device is linked to confirmed abusers. Attribution shows what moved the model, which is mostly the new account, because correlated graph features overlap. We show both and never hide a true fact because the model routed around it." |
| "Isn't this just an unfairly harsh policy on new accounts?" | "New accounts do carry much more friction: 36 % against about 5 %. It's in the model card. Newness alone can never block, and most of that friction is prepaid or review, not refusal." |
| "How do you know it's not overfitted?" | "Chronological splits with gaps, calibration on its own slice, and a ring that exists only in the test period. We catch 73 % of it with the graph and 14 % without." |
| "Is the data real?" | "No, it's synthetic, and every page says so. It includes deliberately hard cases like households, hostels and second-hand phones, and none of those were ever blocked." |
| "What stops someone probing the checkout?" | "The customer only ever sees an outcome. Allow and review return byte-identical responses." |
| "Where does the money come from?" | "One versioned policy file. The UI never formats or computes money; it renders the server's figures, and the assumptions panel shows every value." |

---

## If something breaks

| Problem | Fix |
|---|---|
| A demo shows the wrong state (already overridden) | Queue → **Reset demo** → Confirm (about 7 s) |
| Backend won't start ("Database not found") | `.venv\Scripts\python -m sentinel.cli seed-db`, then `serve` again |
| Fresh machine | `scripts/setup_env.sh` (idempotent: venv, dependencies, data, database) |
| Anything else, or more than 20 s lost | Switch to the backup video and narrate over it |

---

## Video script (≈ 3 minutes, screen recording with voice-over)

**Record at 1440 × 900.** Reset the demo first, and use slow, deliberate mouse movements.

| # | Shot | Voice-over |
|---|---|---|
| 1 | Landing page hero, "A prediction is not a decision." (0:00–0:10) | "E-commerce merchants lose money to return abuse, and most of them fight it by punishing customers who simply return a lot. Sentinel separates the two." |
| 2 | Landing page, Demo 1 mock-up (0:10–0:20) | "Two models: the chance of a return, and the chance of abuse. They're never combined, and return probability can't choose the action." |
| 3 | App → Queue → click ORD-DEMO-001 (0:20–0:40) | "A loyal customer who returns 61 % of orders. Abuse risk is under 0.1 %. Sentinel allows the order; a typical rule would have blocked it." |
| 4 | ORD-DEMO-002, graph, slow zoom on the red nodes (0:40–1:10) | "A new account buying a phone. Its device was used by three confirmed abusers, and its card by three other accounts. Without that relationship evidence it would score 9.9 % and pass. With it: 95 %." |
| 5 | Demo 2 cost bars (1:10–1:25) | "Every action is priced in rupees. Block is cheapest, and it is allowed only because independent signals agree." |
| 6 | ORD-DEMO-003 cost bars, BLOCK hatched G3 (1:25–1:45) | "The uncertain case: 69 %. Review is the cheapest action, so the order goes to a person instead of being refused." |
| 7 | Override dialog → apply → audit timeline (1:45–2:10) | "The reviewer switches it to prepaid. A new event is hash-chained, the original recommendation is preserved, and the chain verifies." |
| 8 | Overview backtest table (2:10–2:35) | "On synthetic data, realized cost is 69 % below doing nothing. A tuned threshold is cheaper still. We pay that premium to block 3.3 times fewer genuine customers, and we say so." |
| 9 | Landing page "What we disclose" → footer notice (2:35–2:55) | "New accounts carry more friction; that's in our model card. All data is synthetic. Real deployment needs a merchant's own data and a prospective trial." |
| 10 | Landing hero again (2:55–3:00) | "Sentinel. Models predict, policy decides, and every decision is explained and recorded." |
