Week 1, Lecture 1: SQL Foundations, Thinking Like the Query Engine

Good. Let us begin. A professor's first rule: understand the machine before you memorize its syntax. Most SQL errors in interviews are not syntax errors. They are ordering errors and NULL errors. Today we fix both.

Part 1: Logical Query Processing Order

You write SQL in one order, but the engine conceptually evaluates it in another:

Step	Clause	What happens
1	FROM / JOIN	Build the working set of rows
2	WHERE	Filter individual rows
3	GROUP BY	Collapse rows into groups
4	HAVING	Filter groups
5	SELECT	Compute expressions, assign aliases
6	DISTINCT	Remove duplicate rows
7	ORDER BY	Sort the result
8	LIMIT	Truncate

Consequences you must internalize:

You cannot use a SELECT alias in WHERE, because WHERE runs before SELECT. (Some engines such as BigQuery and Snowflake relax this, and interviewers know the standard rule.)
WHERE filters rows and HAVING filters groups. Putting an aggregate in WHERE is always an error.
ORDER BY can use aliases, because it runs after SELECT.

This order also explains window functions (Lecture 2 of Week 2): they are evaluated after HAVING and before DISTINCT, which is why you cannot filter on a window function directly in WHERE.

Part 2: Our Working Schema

All examples today use this e-commerce schema:

users(user_id, signup_date, country)
orders(order_id, user_id, order_date, status, amount)
Part 3: Joins, Cardinality First

Do not memorize Venn diagrams. Think in terms of what rows survive and how many rows come out.

INNER JOIN: only rows with a match on both sides.
LEFT JOIN: every left row survives. Unmatched right columns become NULL.
FULL OUTER JOIN: every row from both sides survives.
CROSS JOIN: Cartesian product, m × n rows.

The central danger is row multiplication. If users has one row per user and orders has many rows per user, joining them yields one row per order. Aggregating a user-level attribute after that join silently inflates it. Before every join, ask: "What is the grain of each side, and what is the grain of the result?" Interviewers probe this relentlessly.

The classic LEFT JOIN trap. Suppose we want all users with their completed orders, keeping users who have none:

sql
-- WRONG: the WHERE filter kills the NULL rows, silently turning this into an INNER JOIN
SELECT u.user_id, o.order_id
FROM users u
LEFT JOIN orders o ON o.user_id = u.user_id
WHERE o.status = 'completed';

-- RIGHT: move the condition into the ON clause
SELECT u.user_id, o.order_id
FROM users u
LEFT JOIN orders o
  ON o.user_id = u.user_id
 AND o.status = 'completed';

Why does the first fail? For a user with no orders, o.status is NULL, and NULL = 'completed' is not true, so the row is removed in step 2. Which brings us to the next topic.

Part 4: NULL and Three-Valued Logic

SQL has three truth values: TRUE, FALSE, UNKNOWN. Any comparison with NULL yields UNKNOWN. WHERE keeps only rows evaluating to TRUE.

Key facts:

NULL = NULL is UNKNOWN, not TRUE. Use IS NULL.
NULL <> 5 is UNKNOWN. Rows with NULL are dropped by <> filters.
COUNT(*) counts rows, but COUNT(col) counts non-NULL values. COUNT(DISTINCT col) ignores NULLs too.
SUM, AVG, MIN, MAX ignore NULLs. AVG of (10, NULL, 20) is 15, not 10.
Use COALESCE(x, 0) to substitute defaults.

The NOT IN landmine. If the subquery returns even one NULL, NOT IN returns no rows at all:

sql
-- Dangerous if orders.user_id can be NULL
SELECT * FROM users
WHERE user_id NOT IN (SELECT user_id FROM orders);

Because user_id <> NULL is UNKNOWN for every row, the whole predicate collapses. The safe forms:

sql
SELECT * FROM users u
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.user_id);

-- or the anti-join pattern
SELECT u.*
FROM users u
LEFT JOIN orders o ON o.user_id = u.user_id
WHERE o.user_id IS NULL;

Default to NOT EXISTS in interviews. It signals maturity.

Part 5: Aggregation and HAVING
sql
SELECT country,
       COUNT(*)                 AS users,
       COUNT(DISTINCT u.user_id) AS distinct_users
FROM users u
GROUP BY country
HAVING COUNT(*) > 100;

Rule: every non-aggregated column in SELECT must appear in GROUP BY.

Conditional aggregation is one of the most useful patterns in data engineering. It lets you compute many metrics in one pass:

sql
SELECT user_id,
       COUNT(*)                                        AS total_orders,
       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
       SUM(CASE WHEN status = 'refunded'  THEN amount ELSE 0 END) AS refunded_amount
FROM orders
GROUP BY user_id;

Part 6: CTEs and Subqueries

A CTE (WITH clause) names an intermediate result for readability:

sql
WITH completed AS (
  SELECT user_id, SUM(amount) AS revenue
  FROM orders
  WHERE status = 'completed'
  GROUP BY user_id
)
SELECT u.country, SUM(c.revenue) AS country_revenue
FROM completed c
JOIN users u USING (user_id)
GROUP BY u.country;

Subquery types to recognize:

Scalar: returns one value, e.g. WHERE amount > (SELECT AVG(amount) FROM orders)
Correlated: references the outer query and conceptually runs per outer row. EXISTS is the canonical use.
Derived table: a subquery in FROM.

Interview tip: structure complex answers as a chain of CTEs, each doing one thing. Interviewers read this as clear thinking.

-------------------------------------------------------
Week 1, Lecture 2: How the Engine Executes Your Query

Lecture 1 covered what a query means. Today covers how the engine runs it. Correct SQL that takes four hours is a failed pipeline, and at lead level you are the person who is expected to know why.

(Your coding problems from the Lecture 1 homework are still open. Do them alongside this lecture, since they are the part I can grade most concretely.)

Part 1: The Pipeline Behind a Query

Your SQL passes through several stages:

Parse: check syntax and build a tree.
Plan/optimize: the optimizer enumerates equivalent execution strategies and picks the one with the lowest estimated cost.
Execute: run the chosen plan.

The word that matters is estimated. The optimizer relies on table statistics (row counts, distinct values, value distributions). Stale or missing statistics lead to bad plans, so "the query was fast yesterday and slow today" is often a statistics or data-skew problem, not a code problem.

Part 2: Reading a Plan

Every major engine can show its plan:

Postgres/MySQL: EXPLAIN shows the estimated plan, EXPLAIN ANALYZE actually runs it and shows actual rows and timing.
Snowflake: the Query Profile. BigQuery: execution details. Spark: the SQL tab, or df.explain().

The single most valuable habit: compare estimated rows to actual rows. A large gap (estimated 100, actual 10 million) means the optimizer was misled, and that explains most surprising slowdowns.

Read plans bottom-up and inside-out: the innermost operations (scans) run first, and data flows upward.

Part 3: The Operators You Must Recognize

Scans

Sequential/full scan: read every row. Fine for small tables or when most rows match.
Index scan/seek: use an index to jump to matching rows. Wins when the filter is selective (matches a small fraction of rows).
Columnar scan with pruning (warehouses): read only the needed columns, and skip files or partitions whose min/max metadata rules them out.

Join algorithms

Algorithm	How it works	Best when
Nested loop	For each outer row, probe the inner side	One side is small, or the inner side has a useful index
Hash join	Build a hash table on the smaller side, stream the larger side through it	Large, unsorted inputs, equality joins (the workhorse of analytics)
Sort-merge join	Sort both sides on the key, then merge	Inputs already sorted, or both too large for memory; works for range conditions

In distributed engines these become broadcast join (copy the small table to every node, avoiding a shuffle) versus shuffle/sort-merge join (repartition both sides by the key, which is expensive). Week 6 (Spark) builds on exactly this.

Part 4: Indexes (Row-Store Intuition)
A B-tree index keeps keys sorted, giving fast equality and range lookups.
Composite indexes follow the leftmost-prefix rule. An index on (country, signup_date) helps WHERE country = 'IN' and WHERE country = 'IN' AND signup_date > ..., but not WHERE signup_date > ... alone.
Covering index: contains every column the query needs, so the engine never touches the table.
Indexes are not free: they slow writes and consume storage. Index for your actual query patterns.
Selectivity decides everything. An index on status where 96% of rows are 'completed' is nearly useless for that filter, since reading most of the table through an index is slower than a sequential scan.
Part 5: Warehouse-Specific Thinking

Snowflake, BigQuery and lakehouse engines are columnar, with no classic indexes. Your levers are different:

Select only the columns you need. SELECT * forces reading every column and defeats columnar storage.
Filter on the partition or clustering key so pruning works (this is where sargability from last time pays off).
Filter early, aggregate before joining. Reduce row counts before the expensive shuffle.
Avoid skew. If one key (say user_id = NULL or a viral account) holds 40% of the rows, one worker does 40% of the work while the others idle.
Choose the right set operation. UNION deduplicates, which means a sort or hash over the whole result. Use UNION ALL unless you truly need dedupe. Likewise, avoid DISTINCT as a band-aid for a join fan-out bug (you saw the real fix last time).
Part 6: A Diagnostic Checklist for "This Query Is Slow"

When an interviewer asks this, give a structured answer in this order:

1. Measure: get the actual plan, not guesses.
2. Find the dominant cost: the operator with the largest time or rows.
3. Check estimates vs. actuals: stale statistics?
4. Check data volume: are we scanning or shuffling more than necessary? (columns, partitions, filters)
5. Check join strategy and fan-out: grain, skew, broadcast opportunities.
6. Fix at the right level: query rewrite, then physical design (partitioning, clustering, indexes), then pre-aggregation or materialization, then scale compute last, because it's the most expensive fix and often hides the real problem.

The Lead-Level Layer
Cost is a first-class metric. In a per-byte or per-credit warehouse, a careless query is a budget problem. You'd set up query cost monitoring, partition filter requirements on large tables, and review heavy queries in code review.
Optimize the pipeline, not just the query. Often the best fix is not running the query on raw data at all: incremental models and pre-aggregated tables.
Don't optimize without evidence. Saying "I'd look at the plan first" is a stronger answer than reciting tricks.
Homework (about 60 minutes)

Here is a simplified Postgres-style plan. orders has about 50M rows, users about 1M.

Hash Join  (actual time=4200..9800 rows=48000000)
  Hash Cond: (o.user_id = u.user_id)
  ->  Seq Scan on orders o  (actual time=0.02..3900 rows=48000000)
        Filter: (status = 'completed')
        Rows Removed by Filter: 2000000
  ->  Hash  (actual time=310..310 rows=1000000)
        ->  Seq Scan on users u  (actual time=0.01..140 rows=1000000)


----------------------------------------------------------------------------------------------------------------------------------------------------
----------------------------------------------------------------------------------------------------------------------------------------------------
Week 2, Lecture 1: Window Functions

Window functions are the single most tested SQL topic in data engineering loops. The Week 1 coding problems stay open on your list, so come back to them when you have time. Create a branch for the week: git switch -c w02-sql-windows.

Part 1: The Core Idea

GROUP BY collapses rows: 48M rows in, one row per group out. A window function keeps every row and attaches a computed value derived from a related set of rows (the "window").

sql
function(...) OVER (
  PARTITION BY ...   -- which rows are related (like GROUP BY, but no collapsing)
  ORDER BY ...       -- ordering within the partition
  frame clause       -- which rows around the current row to include
)

Think of it as: for each row, look at its neighbors within its partition, and compute something.

Where it sits in the processing order (extending Lecture 1): windows are evaluated after GROUP BY and HAVING, and just before SELECT's final projection and DISTINCT. Consequence: you cannot filter on a window function in WHERE. Wrap it in a CTE or subquery, or use QUALIFY in Snowflake and BigQuery:

sql
-- Standard SQL
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date DESC) AS rn
  FROM orders
)
SELECT * FROM ranked WHERE rn = 1;

-- Snowflake / BigQuery shortcut
SELECT * FROM orders
QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY order_date DESC) = 1;
Part 2: Ranking Functions
Function	Ties	Example over values 100, 100, 90
ROW_NUMBER()	Arbitrary but unique	1, 2, 3
RANK()	Same rank, then gaps	1, 1, 3
DENSE_RANK()	Same rank, no gaps	1, 1, 2

Choosing is a requirements question. "Top 3 products per category" with ties: do you want exactly 3 rows (ROW_NUMBER), or everyone tied for the top 3 (DENSE_RANK)? Ask the interviewer. That clarifying question is a lead-level signal.

Determinism warning. If ORDER BY has ties, ROW_NUMBER picks arbitrarily, and the result can change between runs. In pipelines, always add a tie-breaker: ORDER BY updated_at DESC, ingest_id DESC.

Part 3: Navigation Functions
LAG(col, n, default) looks at the previous row, LEAD at the next.
FIRST_VALUE, LAST_VALUE, NTH_VALUE.
sql
SELECT order_date, revenue,
       revenue - LAG(revenue) OVER (ORDER BY order_date) AS dod_change
FROM daily_revenue;

The first row has no predecessor, so LAG returns NULL. Decide how you handle it (default value or leave NULL), and guard divisions for percentage change with NULLIF(prev, 0).

Part 4: Frames, Where Most Bugs Live

The frame says which rows around the current one feed an aggregate:

sql
SUM(amount) OVER (
  PARTITION BY user_id
  ORDER BY order_date
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW   -- running total
)

Two traps, both frequently asked:

Default frame. When ORDER BY is present and you don't specify a frame, the default is RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW. RANGE treats rows with equal ORDER BY values as peers and includes all of them. So a running total with duplicate dates jumps by the whole group at once. Write ROWS explicitly when you mean "row by row."
LAST_VALUE. With the default frame, LAST_VALUE(x) returns the current row's value (the frame ends at the current row), not the partition's last value. Fix: ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING, or use FIRST_VALUE with a reversed order.

Moving average caveat. ROWS BETWEEN 6 PRECEDING AND CURRENT ROW means the last 7 rows, which equals 7 days only if every day has a row. With missing days, you need a calendar table (join to a date spine first) or a RANGE frame with an interval, where your engine supports it.

Part 5: The Patterns You Must Know Cold

1. Deduplicate / latest record per key (every pipeline uses this):

sql
SELECT * FROM customers
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at DESC, ingest_id DESC) = 1;

2. Top-N per group: ranking function plus filter, as above.

3. Running totals and moving averages: frames, as above.

4. Sessionization. Group a user's events into sessions, where a gap of more than 30 minutes starts a new session. The technique is flag, then cumulative sum:

sql
WITH flagged AS (
  SELECT user_id, event_ts,
         CASE WHEN LAG(event_ts) OVER (PARTITION BY user_id ORDER BY event_ts) IS NULL
                OR event_ts - LAG(event_ts) OVER (PARTITION BY user_id ORDER BY event_ts)
                   > INTERVAL '30 minutes'
              THEN 1 ELSE 0 END AS new_session
  FROM events
)
SELECT user_id, event_ts,
       SUM(new_session) OVER (PARTITION BY user_id ORDER BY event_ts
                              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_id
FROM flagged;

Each "new session" flag adds 1, so the running sum becomes a session counter. Learn this shape; it reappears in many problems.

5. Gaps and islands (consecutive streaks): subtracting a row number from a sequential value gives a constant for each unbroken run.

sql
WITH d AS (SELECT DISTINCT user_id, login_date FROM logins),
g AS (
  SELECT user_id, login_date,
         login_date - (ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date))::int AS grp
  FROM d
)
SELECT user_id, MIN(login_date) AS streak_start, MAX(login_date) AS streak_end, COUNT(*) AS streak_len
FROM g GROUP BY user_id, grp;

Why it works: consecutive dates increase by 1, and the row number also increases by 1, so their difference stays constant within a streak and jumps at each gap. Note the DISTINCT first, because duplicate dates would break the arithmetic. (Postgres syntax; adjust date arithmetic for your engine.)

Part 6: The Lead-Level Layer
Cost. Each distinct PARTITION BY ... ORDER BY needs data sorted by partition. In a distributed engine that means a shuffle on the partition key. Reusing the same window spec across several functions lets the engine share one sort, and you can name it with a WINDOW w AS (...) clause.
Skew. If PARTITION BY user_id has one key (a bot, or NULL) with 30% of the rows, one worker handles 30% of the data. Filter out junk keys first, and watch for NULL partitions.
Reduce data first. Filter and project before the window, because the sort cost scales with row count.
Dedupe in pipelines. The ROW_NUMBER dedupe is the heart of idempotent incremental loads, and the tie-breaker keeps reruns deterministic. This links to the MERGE discussion from Week 1 and to Week 7 (dbt incremental models).
Window vs. self-join. A window function usually replaces a self-join (e.g. comparing each row to the previous) with a single pass, which is both simpler and faster.
Homework (about 2 hours total)

Use orders(order_id, user_id, order_date, status, amount), users(user_id, signup_date, country), events(user_id, event_ts, event_type), logins(user_id, login_date), and customers(customer_id, name, email, updated_at, ingest_id) with multiple versions per customer. Target times in brackets.

Conceptual (2 to 3 sentences each, into 02 notes in 01-sql/interview.md):

Why can't you write WHERE ROW_NUMBER() OVER (...) = 1, and what are two ways around it?
A running total over a RANGE frame jumps unexpectedly on days with multiple orders. Why?

Coding (01-sql/exercises.sql, add a -- time: N min comment to each):

Top 3 orders by amount per country. State whether you chose ROW_NUMBER or DENSE_RANK and why. [12 min]
Day-over-day revenue change as a percentage, handling the first day and zero-revenue days. [12 min]
7-day moving average of daily revenue. Describe what breaks if some days have no orders. [15 min]
Latest version of each customer, deterministic on ties. [8 min]
Sessionize events with a 30-minute gap and output, per session, start, end and event count. [20 min]
Longest consecutive login streak per user. [20 min]

Tier 2: events has 20 billion rows and a few bot user_ids with billions of events each. What happens to your sessionization query, and how would you fix it?

Tier 3: Turn problem 4 into an idempotent incremental pipeline step. How do late-arriving versions, reruns and backfills behave?


