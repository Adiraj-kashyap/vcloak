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

## Future work: scaling behaviour end to end

Declared scope (ADR-028, decision of the owner on ISSUE-51): the end-to-end evaluation (E6, M15) is valid at 10 and
50 concurrent users in two-party conversations. That is what the results chapter claims: correct and within budget
at those two populations. Two populations are not a scaling curve. How latency, throughput or GPU load change as
the number of users grows is untested; no trend is drawn and nothing is extrapolated.

The 200-user cells that were run are not evidence either way: the single-process load generator exceeded one core
while the service was at 25 to 32 % of a core, so the limit was the measuring harness, not the system. Those rows
are kept in the run record as UNSTABLE and appear in no table or figure.

What a scaling result needs, and does not exist yet:
- a load harness that runs several generator processes, so that the generator stays below one core per process
  and its own queueing stays out of the latencies;
- the CAND_K sizing rule (buckets and CAND_K from the expected rows per bucket-window, ISSUE-43) applied to the
  layouts of larger populations, so that a larger cell is measured on a layout sized for it rather than on the
  default one.

Nothing in the repository measures the system end to end above 50 users: no number here or elsewhere may be
quoted for a larger population.
