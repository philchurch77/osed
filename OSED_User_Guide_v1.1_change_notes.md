# User Guide v1 → v1.1: what changed, and what needs a decision

Checked against the live OSED code on 6 September 2026. Two lists: corrections I have
already applied to v1.1, and mismatches I have **not** resolved because they are a
decision for you rather than a wording fix.

---

## A. New content

**Section 6, "Using the Risk Register"** is new (6.1 scoring, 6.2 logging, 6.3 the termly
review, 6.4 what happens after you save, 6.5 how a risk comes off the register, 6.6 what
good looks like). Sign-off, What happens next, and the two writing sections have moved
down to 7, 8, 9 and 10, and the cross-reference in section 3 now points at "steps 9 and 10".

---

## B. Corrections applied

| # | Where | v1 said | The system does |
| --- | --- | --- | --- |
| 1 | §1 | "Select Microsoft Single Sign-In" | The button reads **Sign in with Microsoft**. |
| 2 | §2 | "choose the overall judgement from the dropdown" | The judgement cell opens a panel of five rating buttons, not a dropdown list. |
| 3 | §2 | Only school and year mentioned | The dashboard shows **all three terms side by side** for the year; there is no term selector on that page. Added a line so leaders know which column to complete. |
| 4 | §3 | "the 300-word evidence summary and the 300-word priorities and next steps sections" | The on-screen columns are labelled **Commentary** and **Next steps**. Both are 300 words. Wording aligned to the labels. |
| 5 | §5 | The rounds table implied the system works in rounds | In-depth reviews are held against the **academic year**, not a term, and every area is selectable at any time. Added an NB, and noted that Early Years and Post-16 are **two separate areas** in the in-depth review (the dashboard still has one combined "Early Years / P16" row). |
| 6 | §5 | "additional in-depth review outside of this cycle… is possible" | True, but there is **one in-depth review per area per academic year** — revisiting an area updates that record rather than creating a second one. Added to the NB. |
| 7 | §5, Step 1 | "prompt you to complete this same process… e.g. Strong Standard, Urgent Improvement, Needs Attention, Exceptional" | Only **expected standard, strong standard and exceptional** statements are ever RAG-rated. A red at expected standard concludes **Needs Attention** immediately and shows nothing further; **Urgent Improvement is not an outcome the ladder concludes at all**. Replaced with the actual rules. |
| 8 | §5, Step 1 | The "grades differ" NB read as though the alert appears on the in-depth page | The alert appears on the **Evaluation** tab, headed "In-depth review grades differ". Corrected. |
| 9 | §5 | Safeguarding not distinguished | Safeguarding has a single set of statements and concludes **Met / Not Met**. Added. |
| 10 | §5, Step 2 | Implied every rated bullet needs a write-up, at the guide's 300-word limits | The commentary page shows the statements for **the band the grade landed on**, and both boxes are capped at **150 words**, not 300. Corrected, plus the Needs Attention prompt ("in addition, does one or more of the following apply?"). |
| 11 | §7 (was §7) | "Trust Dashboard… based on school averages" | The Trust Dashboard is a **grid of every school against every area** for one term, with trend arrows — no averaging. (Averages do exist, but on **School Progress** when "all schools" is selected.) Rewritten. |
| 12 | §8 | School Progress tab not mentioned | Added to Outputs and Reporting. |
| 13 | §8 | "respond to them by updating directly onto the OSED online system" | Named the **Reflection** tab (*Reflection on QA & Feedback*), one box per area per year, which is where those responses go. |
| 14 | §9 | "text will be cut off at the word limit" | Correct — kept, and added that a live word counter sits under each box. |
| 15 | Throughout | Encoding damage (`â` in place of em-dashes, e.g. "Summer 2 â Autumn 1", "Amber â Partial evidence") | Repaired. |

---

## C. Not resolved — your call

**1. "The OSED will automatically close at the end of day on the deadline."**
The system has no automatic close. There is no lock, no submit step and no read-only
switch that comes on at a date: every tab stays editable for any year and term, for
anyone with edit rights, indefinitely. I have softened the line to "The OSED closes at the
end of day on the deadline communicated in the SI calendar", which is true as a process
statement, but if you intend it to read as a system behaviour then either the guide needs
to say the deadline is managed by the SI calendar and enforced by the Central Team, or the
lock needs building. Worth deciding before the guide goes out, because Principals will
read the current sentence as "the system will stop me".

**2. "SEF-Ready Summaries… can be exported and inserted directly into the SEF."**
There is no export anywhere in the OSED — no download, no CSV, no print view, no copy
button. The text can be selected and copied from the screen, and that is all. I have
reworded to "are written to be used directly in the SEF" rather than claim an export, but
if an export button was expected for this year it is not built.

**3. Risk register entries cannot be edited by the school.**
Once a risk is added, only the term rating and the term note can be changed on the Risk
tab. Title, category, mitigation, owner and review point are fixed. The Central Team can
amend them in the admin. I have written §6.2 to warn Principals to check before saving and
to contact the Central Team for corrections — but if you would rather they could edit
their own entries, that is a build change, not a guide change. The same applies to
reopening a closed risk, which is currently impossible.

**4. Who can see the Risk tab.**
The Risk tab is visible to **every** account that can log in, including read-only accounts
such as trustees, and it shows the full register for the schools that account is
provisioned for. Only the Risk QA screen is restricted. Section 6 is written for the
Principal and does not spell this out; if trustees are being told they see only the Red
exception report, that is worth a sentence somewhere.

**5. Mitigation and close-reason word limits.**
Both are 150 words. I have stated them in §6, but they were never in a client document, so
flag them if they feel wrong — they are easy to change.

**6. The escalation rule is Red only.**
Stated in §6.4. It is a setting rather than code, so if the Trust later decides that an
Amber persisting across terms should also escalate, that sentence in the guide needs
changing at the same time.

**7. Terminology.**
The system labels terms **Autumn / Spring / Summer** everywhere and never says "Round 1".
The §5 rounds table still uses OSED Round numbering, which is right for the SI cycle — I
have added an NB so the two do not read as contradicting each other.
