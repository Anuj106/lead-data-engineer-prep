
----------------------------------------------------------------
PARTITION PRUNING & FILE PRUNING & ROW-GROUP PRUNING & PREDICATE PUSHDOWN 
----------------------------------------------------------------
Partition pruning is a database optimization where the query engine skips partitions that cannot contain the rows you're looking for.

Think of a partitioned table as a cupboard with separate drawers. Instead of opening every drawer, the database opens only the relevant ones

Partition pruning decides which partitions to read. Predicate pushdown decides which rows/records to filter as early as possible.

Partition pruning decides which partitions to read. Predicate pushdown decides which rows/records to filter as early as possible.

For a Lead Data Engineer interview, a very good one-line answer is:

Partition pruning eliminates entire partitions based on partition predicates, while predicate pushdown pushes filters closer to the data source so fewer rows need to be read or processed.

S3
│
├── date=2026-08/        ← Partition pruning ❌
├── date=2026-09/        ← Keep
│   │
│   ├── file-001.parquet ← File pruning ❌
│   ├── file-002.parquet ← File pruning ❌
│   └── file-003.parquet ← Keep
│       │
│       ├── Row Group 1  ← Row-group pruning ❌
│       ├── Row Group 2  ← Row-group pruning ❌
│       ├── Row Group 3  ← Keep
│       └── Row Group 4  ← Row-group pruning ❌
│
└── date=2026-10/        ← Partition pruning ❌

Interview answer

If they ask:

"What is row-group pruning?"

Say:

Parquet files are divided into row groups with statistics such as min/max values. If the query predicate cannot possibly match a row group based on those statistics, the engine skips reading that row group. This reduces I/O without scanning the entire file.

And the key distinction:

Partition pruning skips partitions; file pruning skips files; row-group pruning skips portions of files; predicate pushdown applies filters as close to the data source as possible.