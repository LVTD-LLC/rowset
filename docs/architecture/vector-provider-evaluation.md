# Vector Provider Evaluation

## Recommendation

Keep Qdrant as Rowset's V1 provider. Revisit turbopuffer when Rowset has
production evidence that vector index volume, namespace count, or cold-storage
economics dominate operational cost.

Do not add turbopuffer to the MVP path now. The existing Qdrant deployment is
already provisioned for Rowset, the current code is Qdrant-backed, and the V1
product risk is search correctness rather than petabyte-scale index economics.

## Current Rowset Needs

- Authenticated dataset-level row search.
- Server-derived profile and dataset filters.
- Immediate enough row create/update/delete behavior for agent workflows.
- A self-hostable path that fits existing CapRover operations.
- A rebuildable retrieval index sourced from Rowset/Postgres.
- Simple operational debugging while the product surface is still changing.

## Qdrant Fit

Qdrant remains the best default for V1 because:

- It is already deployed for Rowset on CapRover.
- It is self-hostable and does not force a paid hosted dependency for early
  dogfooding.
- Its core data model maps directly to Rowset's design: collections contain
  points, and points combine vectors with JSON payload used for hydration and
  filtering.
- It supports payload filtering and payload indexes, which Rowset needs for
  profile, dataset, status, archived, and row metadata filters.
- Its collections require consistent vector dimensionality, matching Rowset's
  one-collection-per-model-and-dimension strategy.

Primary risks:

- Rowset owns Qdrant operations, backup posture, monitoring, and capacity.
- Cost is resource-based for hosted Qdrant Cloud and infrastructure-based for
  self-hosting, so idle or small workloads can still consume a fixed server.
- Very large cold datasets may become expensive or operationally heavy compared
  with object-storage-native systems.

## Turbopuffer Fit

turbopuffer is worth tracking because it is object-storage-native and designed
for very large search workloads. Current official docs emphasize large scale,
many namespaces, cost-effectiveness, hybrid search, object-storage durability,
and namespace-oriented tenancy.

Strengths that may matter later:

- Object-storage-native architecture for large cold or semi-cold indexes.
- Built-in vector, full-text, and hybrid search support.
- Namespace model that can fit isolated tenant or dataset partitions.
- Current pricing has a low Launch minimum compared with typical managed
  database commitments, while Scale and Enterprise tiers add higher minimums and
  support/security features.
- Recent roadmap updates show active work on namespace branching, sparse vector
  search, int8 vector storage, full-text improvements, and large-namespace query
  pricing reductions.

Primary risks for Rowset now:

- It is not open source and is commercial-only for normal use.
- It would add a second provider before V1 Qdrant behavior is proven.
- Rowset would need a new provider implementation, new lifecycle tests, new
  operational docs, and migration/backfill tooling.
- The current workload is likely too small for turbopuffer's scale economics to
  outweigh provider complexity.
- Write latency and cold-query behavior need validation against Rowset's agent
  workflow expectations.

## Decision Triggers

Reopen the provider decision when at least one of these is true:

- Rowset stores tens of millions of indexed rows or enough vector bytes that
  self-hosted Qdrant capacity planning becomes a recurring constraint.
- Cold or long-tail datasets dominate storage cost while query frequency remains
  low.
- Customers require many naturally isolated namespaces and only occasionally
  query each namespace.
- Qdrant operations become a material maintenance burden relative to product
  usage.
- A customer requires managed private networking, BYOC, or commercial support
  that is a better fit for turbopuffer.

## Evaluation Plan For Later

When a trigger is met:

1. Export a representative Rowset dataset corpus: taskboards, CRM-like datasets,
   and one large synthetic long-tail dataset.
2. Index the same chunk payloads in Qdrant and turbopuffer.
3. Compare exact-ID, semantic, filtered, and hybrid queries using the existing
   search quality fixture as a seed.
4. Measure write latency, backfill throughput, delete/reindex behavior, hot and
   cold query latency, filter behavior, and operational recovery.
5. Estimate monthly cost from storage, writes, queries, minimum commitments, and
   support requirements.
6. Decide whether to add a second provider abstraction implementation, migrate,
   or stay Qdrant-only.

## Source Links

- Qdrant overview: https://qdrant.tech/documentation/overview/
- Qdrant collections: https://qdrant.tech/documentation/manage-data/collections/
- Qdrant filtering: https://qdrant.tech/documentation/search/filtering/
- Qdrant indexing: https://qdrant.tech/documentation/manage-data/indexing/
- Qdrant pricing: https://qdrant.tech/pricing/
- turbopuffer introduction: https://turbopuffer.com/docs/index
- turbopuffer architecture: https://turbopuffer.com/docs/architecture
- turbopuffer tradeoffs: https://turbopuffer.com/docs/tradeoffs
- turbopuffer pricing: https://turbopuffer.com/pricing
- turbopuffer roadmap: https://turbopuffer.com/docs/roadmap
