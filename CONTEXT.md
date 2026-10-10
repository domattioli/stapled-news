# stapled-news

Multi-outlet news coverage treated as a panel of noisy raters, from which a hidden consensus and per-outlet performance are estimated jointly.

## Language

### Estimation

**Event**:
A single real-world happening covered by one or more **Outlets**; the hidden object being rated.
_Avoid_: story, topic

**Outlet**:
A news publisher acting as one rater of an **Event**.
_Avoid_: source, publisher, annotator

**Atomic claim**:
A small, auditable proposition extracted from coverage that an **Outlet** includes or omits.
_Avoid_: fact, statement

**Consensus**:
The estimated latent status of an **Atomic claim** across **Outlets**; what the model identifies. Never equated with truth.
_Avoid_: truth, accuracy

**Sensitivity**:
An **Outlet**'s rate of covering consensus **Atomic claims**.
_Avoid_: reliability (ambiguous)

**Specificity**:
One minus an **Outlet**'s rate of propagating non-consensus **Atomic claims**.

### Validation

**Anchor**:
An externally labeled truth value for an **Event** or **Atomic claim**, drawn only from open fact-check datasets. A single **Outlet** is never an **Anchor**.
_Avoid_: ground truth, gold label

**Anchored posterior**:
The model's probability that an **Atomic claim** holds, after **Anchors** orient the classes; evaluated against held-out **Anchors**, never synonymous with truth.
_Avoid_: truth estimate, verified probability

**Eligible omission**:
An **Outlet** not carrying an **Atomic claim** for an **Event** it did cover; absence from an uncovered **Event** is not an omission.
_Avoid_: missing, silence

**Majority vote**:
The baseline that counts **Outlets** equally, against which **Consensus** is compared on **Anchors**.

**Syndication cluster**:
A group of near-duplicate headlines from one underlying account; it casts one vote.
_Avoid_: wire copy, duplicate

**Lean**:
An **Outlet**'s political position, taken from open academic ratings; not estimated by the model.
_Avoid_: bias (the model has no lean parameter)

## Flagged ambiguities

- "Bias" was used for both **Lean** and model error; use **Lean** for politics and **Sensitivity**/**Specificity** for performance.
- "Reuters as truth" (e6 anchoring) conflicts with **Anchor**; resolved: Reuters is an **Outlet**, kept only as an ablation.

## Example dialogue

> **Dev:** Fact-checkers rated this claim false; is that our **Consensus**?
> **Expert:** No. It is an **Anchor**. We check whether **Consensus** matches it more often than **Majority vote** does.
> **Dev:** And the AP story in forty papers?
> **Expert:** One **Syndication cluster**, one vote.
