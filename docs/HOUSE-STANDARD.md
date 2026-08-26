# House Standard

Every agent on this team reads this file before writing anything. It is the contract that makes seven independent opinions add up to one defensible deliverable.

---

## 1. Evidence discipline — the tagging rule

**No bare numbers.** Every quantified claim, every competitor assertion, every statement about regulation or timing carries a tag showing where it came from. A number without a tag is a defect, and the round's Engagement Manager sends the report back.

| Tag | Means | Example |
|---|---|---|
| `[F-012]` | Verified fact. Lives in `01-fact-base.md` with source, URL, and verbatim quote. | `EU installs fell 4% in 2025 [F-012]` |
| `[R-p14]` | The input report asserts this on page 14. **Not independently verified.** | `Management targets 12% share by 2028 [R-p14]` |
| `[C-finance/unit-econ.md]` | From our internal context pack. | `Our gross margin floor is 34% [C-finance/unit-econ.md]` |
| `[EST: method]` | Your own estimate. The method goes in the tag. | `~€900M addressable [EST: F-012 volume × F-018 price, EU-27 only]` |
| `[ASSUMPTION]` | A premise you are adopting without evidence, knowingly. | `Tariff regime holds through 2027 [ASSUMPTION]` |

The distinction between `[F-]` and `[R-]` is the one that matters most. `[F-]` means someone checked. `[R-]` means the report said so. Collapsing the two is how a strategy team ends up defending a client's own marketing deck back to them.

**You may not promote `[R-]` to `[F-]` yourself.** Only the Research Desk grades facts. If a report claim is load-bearing for your argument and it is still `[R-]`, say so explicitly — that is a finding about the report's foundations, and the Partner needs it.

## 2. What "no hallucination" means operationally

It is not a request to be cautious. It is three concrete behaviors:

- **Cite or estimate — never assert.** If you cannot tag it, you do not know it. Write `[EST: ...]` and show your method, or leave the claim out.
- **An estimate must be reproducible.** Anyone reading `[EST: F-012 × F-018]` can redo your arithmetic and get your number. "Industry experience suggests roughly 15%" is not an estimate; it is a hallucination with a hedge in front of it.
- **Say what you could not establish.** Every report ends with an open-questions section. A lens report with no open questions has not been honest about its limits.

When you search the web, the same rule applies to what you bring back: record the URL and the sentence that supports the claim, not your recollection of the page.

## 3. Answer-first structure

Lead with the conclusion. Your first sentence answers "so what" — the thing the reader would ask for if they said "just give me the headline." Supporting logic comes after, for readers who want it.

This inverts how analysis is usually written and it is the single hardest habit to hold. A section that opens with "In order to assess the market dynamics, we first examined..." has buried its answer. Rewrite it to open with what you found.

## 4. Be readable, then be brief

Readable and brief are different things, and readable matters more. If the reader has to reread your paragraph or ask what you meant, any words you saved are gone.

Keep output short by being **selective** — drop findings that don't change what the reader would do next — not by compressing prose into fragments, arrow chains (`demand ↓ → margin ↓ → exit`), or shorthand you invented three sections ago. What you do include, write in complete sentences with the terms spelled out.

Use tables for enumerable facts. Use prose for reasoning. A table is a bad place to put an argument.

## 5. Scope discipline

Answer the question you were given, from the lens you were given. Do not:

- write the other lenses' sections for them — they are running in parallel and will cover their own ground
- expand the engagement scope because an adjacent question looks interesting
- deliver a recommendation the client did not ask for, unless you flag it plainly as out of scope

If you conclude the framing itself is wrong, say so in a sentence and then do the work as scoped. Deciding to change the question is the Partner's call, not yours.

## 6. Confidence, stated plainly

Every finding carries a confidence level, and the levels mean something specific:

- **High** — grounded in `[F-]` facts graded A or B, and the logic connecting them is short.
- **Medium** — grounded in facts, but the inferential chain is long, or one input is grade C.
- **Low** — resting on `[R-]` claims, `[ASSUMPTION]`s, or a single uncorroborated source.

Do not round Low up to Medium because the finding feels important. Importance and confidence are independent, and the Partner needs both to weigh a recommendation.

## 7. Falsifiers

Every substantive finding names what would change your mind. "This holds unless Chinese import prices fall below €2,800/unit, which F-031 puts at €3,400 today" is a falsifier. "Further research is recommended" is not.

Falsifiers are what let the Red Team do its job, and what makes the deliverable useful six months later when conditions have moved.

## 8. The lens report format

Seven sections. Do not add sections; do not skip them. If a section is genuinely empty, write one line saying why.

1. **Bottom line** — three sentences maximum. The so-what from this lens alone.
2. **Where the report holds up, and where it doesn't** — from your lens specifically. Cite pages.
3. **Findings** — three to five, each answer-first, each tagged, each with a confidence level.
4. **The number that matters** — one figure this lens contributes to the decision, with its full derivation.
5. **Risks and falsifiers** — what would change your view, quantified where possible.
6. **Open questions** — what you could not establish, and what it would take to establish it.
7. **Recommended action from this lens** — with confidence, and with an explicit note where it may conflict with another lens.

Section 7's conflict note matters: you cannot see the other lenses' reports, but you can usually predict where you are stepping on them. Naming it makes the Partner's conflict map real instead of guessed.
