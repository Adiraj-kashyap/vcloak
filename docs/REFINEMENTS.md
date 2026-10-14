# Refinements and future scope

The refinements carried out (C1-C*, each with its before and after numbers) are written in M20 S3. Until then this
file holds only what has been decided as scope.

## Future work: group conversations

Declared scope (ADR-027): V-cloak supports two-party conversations only. Every conversation in the implementation
and in every measurement is a pair, and every reported population says so (conversations = users / 2).

Group conversations are future work. What would have to change: the sizing of the candidate set (CAND_K) and the
window layout (WINDOW_S, BUCKETS), because the anonymity set of a message is bounded by its conversation group. A
group puts more rows of one conversation into one bucket-window than a pair does, so a layout sized for pairs
overflows CAND_K sooner, and the set a message hides in has to be re-derived for groups rather than read off the
two-party results.

Nothing in the repository measures a group: no number here or elsewhere may be quoted for one.
