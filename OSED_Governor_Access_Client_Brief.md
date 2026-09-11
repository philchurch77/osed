# Governor access to the OSED — what has been built, and two decisions we need

**Date:** 10 September 2026
**For:** Ele
**Status:** Built and tested. Not yet released to any school. Two decisions below are needed before we switch it on.

---

## What was agreed

At the meeting on 9 September, governors were given the go-ahead to have their own OSED
logins, starting with a limited view: **the School Dashboard, the Trust Dashboard and the
Evaluation page**, with the in-depth review left closed until schools have said whether
they are comfortable opening it.

That is what has been built. Nothing else was opened.

---

## What a governor will see

A governor signs in with Microsoft, exactly as staff do, and lands on a menu with four
items:

| Page | What it shows them |
|---|---|
| **Home** | A list of the school or schools they govern. |
| **School Dashboard** | The termly ratings for their school, across the eight evaluation areas. |
| **Evaluation** | The judgement areas, with the evidence and next-steps commentary school leaders have written. |
| **Trust Dashboard** | The term's grid, with arrows showing movement against the previous term. |

**Governors cannot change anything.** Every page is read-only for them. There is no Save
button, the rating controls are inert, and the commentary appears as text rather than as
boxes they could type into. Even if a governor account were set up incorrectly and given
editing rights by mistake, it still could not save — the restriction is applied first and
overrides everything else.

**Governors only ever see their own school.** Everything is filtered to the school or
schools on their user record. If a governor edits the address in their browser to try
another school's number, they are quietly returned to their own. We have tested this
directly, including with deliberately malformed values.

## What a governor will not see

The following are **not** available to governor accounts. If one follows an old link or a
bookmark to any of them, they get a plain page explaining that their account covers three
pages and offering links back to them — not an error, and not a silent redirect that would
look like a broken link.

- In-depth review (the decision you flagged as most sensitive to schools)
- Reflection
- School Progress
- Risk register
- Operations & Resources
- Anything administrative

Two things sit on the Trust Dashboard that we have **deliberately hidden from governors**,
because they come from tabs governors are not being given: the **red-risk exception
report**, which names each risk and its owner, and the **Operations & Resources summary**.
Governors see the judgement grid and a line explaining that the rest is managed by school
and trust staff.

---

## Two decisions we need from you

### 1. The Trust Dashboard shows a governor only their own school

The Trust Dashboard is filtered by school for everyone except system administrators. That
means a governor of one school opens a page called "Trust Dashboard" and sees **a single
row — their own school**.

That is consistent with how the rest of the system works, and it is what we have built.
The concern is the name: a governor may reasonably expect a trust-wide picture and wonder
where the rest of it went.

**Options:**

- **Leave it as it is** and expect the page name to be self-explanatory in context.
- **Leave the scoping but rename or re-label the page** for governors, so no one is
  looking for data that was never going to appear.
- **Give governors the whole trust's grid.** Possible, but it would be the first time any
  non-administrator sees other schools' judgements, so it needs a deliberate decision from
  the Trust rather than a technical one from us.

We would not recommend the third without a conversation about who else it affects.

### 2. Do any governors sit on more than one governing body?

This matters more than it sounds. Where a governor is linked to two schools, moving
between the menu items can quietly return them to their default school rather than keeping
them on the one they were reading — the page changes school without anything on screen
signalling it clearly.

The realistic risk is not that someone gets stuck. It is that a governor reads one school's
judgements believing they are looking at another, and repeats them in a meeting.

If multi-school governors are a real case at the Trust, we would fix this before release —
it is a contained change. **If every governor sits on a single governing body, it cannot
happen at all** and we would leave it alone. We need to know which it is.

---

## What we would need from you to set governors up

- **A list of governors, with the exact school name and email address** for each. The
  school name has to match the Trust's record exactly ("Copleston High School", not
  "Copleston") or the row is skipped.
- The email address must be the one attached to their Microsoft account.
- **Which schools are in the first group**, if you would rather start with one or two
  rather than all of them.

Accounts are created and marked as governors in one step, and there is a safeguard: if a
governor list is uploaded without the role column filled in, the system reports how many
accounts were created with full access rather than letting it pass silently.

**Removing a governor** when they leave is one change — marking the account inactive. That
is the complete action and revokes access immediately.

---

## What has not changed

Committee members and Trust Board members still have **no OSED logins**, and none are
planned. Those audiences continue to receive exported screenshots in board packs. Governors
are the single exception agreed at the meeting, and were treated as such.

---

## One thing for the Trust's data protection record

Governors are a new group of people being given access to the system for the first time,
and they will be reading evaluative commentary written by staff about their own school.

No new personal information is being collected, and this change narrows access rather than
widening it — so in our view it does not trigger a new data protection impact assessment.
But if the Trust's record of processing lists who has access to the OSED, **it will need
updating to name governors and what they can see.** That is a judgement for the Trust's
data protection officer, and we have flagged it rather than assumed it.
