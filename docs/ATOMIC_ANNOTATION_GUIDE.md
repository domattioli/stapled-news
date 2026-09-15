# Atomic Consensus Annotation Guide

Status: planned. This guide records protocol, not completed annotations or metrics.

## Split and isolation

Annotate 20 pilot events for rule development. Freeze parser, aliases, taxonomy,
matching rules, panel, and thresholds before annotating the 80 disjoint held-out
events. Held-out records must never be used to tune rules.

## Ownership and adjudication

Two independent annotators label each accepted atom, equivalence match, and
explicit conflict. Store annotator IDs, artifact versions, and a coded rationale.
A third adjudicator resolves disagreements without seeing system output. Record
planned, completed, and adjudicated counts separately. No precision, recall, or
coverage outcome is reported until this ledger exists.
