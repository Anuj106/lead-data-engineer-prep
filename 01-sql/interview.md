Part 7: Homework (about 90 minutes, no running code, write on paper or in a doc)

Conceptual (answer in 2 to 3 sentences each):
-----------------------------------------------------------
Why does SELECT amount * 2 AS dbl FROM orders WHERE dbl > 100 fail in standard SQL?
-----------------------------------------------------
Grade: correct. That is the core reason, and it is stated concisely.

To make it interview-complete, add three sentences:

Name the fix. Either repeat the expression, WHERE amount * 2 > 100, or wrap it so the alias exists before the filter runs:
sql
   WITH t AS (SELECT amount * 2 AS dbl FROM orders)
   SELECT dbl FROM t WHERE dbl > 100;
Distinguish logical from physical order. The processing order is a semantic model, not the literal execution plan. The optimizer may reorder operations, such as pushing filters down, as long as the result is equivalent. The alias rule comes from the logical model.
Show the lead-level instinct. Even the repeated-expression version, WHERE amount * 2 > 100, applies a function to the column, which can prevent index or partition-pruning use (it is non-sargable). The better rewrite is WHERE amount > 50. An interviewer who sees you volunteer this will mark you as someone who thinks about performance by default.


----------------------------------------------------
Q2. A LEFT JOIN from users to orders returns more rows than users has. Why, and is that a bug?
--------------------------------------------------------
Grade: correct on both parts. It is not a bug, and the cause is a one-to-many relationship, with multiple orders per user. At lead level, the interviewer expects you to go further on three points.

1. State the rule precisely

A LEFT JOIN guarantees the result has at least as many rows as the left table, never fewer. Each left row appears once per matching right row, or once with NULLs if there is no match. So the output grain changes from one row per user to one row per order (or per user with no orders).

2. Say when it is a bug

Fan-out is only intentional if you wanted order-level rows. It becomes a bug in two situations:

Aggregating a left-side attribute after the join. If users has a lifetime_budget column and you run SUM(u.lifetime_budget) after joining to orders, each user's budget is counted once per order. The numbers inflate silently, with no error and plausible-looking output.
The right side was supposed to be unique but isn't. Joining to a dimension table that should have one row per key, but has duplicates (a bad SCD load, a missed dedupe), multiplies rows unexpectedly. Here the join is exposing an upstream data quality problem.

-- Is the right side unique on the join key?
SELECT user_id, COUNT(*) FROM orders GROUP BY user_id HAVING COUNT(*) > 1;

-- Did the join change the grain?
SELECT COUNT(*) AS rows_out, COUNT(DISTINCT u.user_id) AS users_out FROM users u LEFT JOIN orders o USING (user_id);

--------------------------------------------------------------
Q3. AVG(amount) returns a different value than SUM(amount) / COUNT(*). Under what condition?
----------------------------------------------------------------
"They differ when amount contains NULLs. AVG divides by the count of non-NULL values, while COUNT(*) counts all rows, so the second expression is lower. I'd also watch for integer division on int columns and divide-by-zero on empty groups. Then I'd clarify what NULL means in the business: unknown versus zero, because that decides whether to exclude it or COALESCE it. And I'd define the metric once so all dashboards agree."

-----------------------------
Week1 - L2 : How the Engine Executes Your Query
Homework (about 60 minutes)

Here is a simplified Postgres-style plan. orders has about 50M rows, users about 1M.

Hash Join  (actual time=4200..9800 rows=48000000)
  Hash Cond: (o.user_id = u.user_id)
  ->  Seq Scan on orders o  (actual time=0.02..3900 rows=48000000)
        Filter: (status = 'completed')
        Rows Removed by Filter: 2000000
  ->  Hash  (actual time=310..310 rows=1000000)
        ->  Seq Scan on users u  (actual time=0.01..140 rows=1000000)

Answer in 01-sql/interview.md:

Q1. Which join algorithm is used, and which table is the hash table built on? Why is that a sensible choice?

"Hash join, with the hash table built on users. It's the smaller side at about 1M rows versus 48M, so it fits in memory, and orders is streamed through it with O(1) lookups. The join key is unique on users, so there's no fan-out, which the 48M output rows confirm."


Q2. Would an index on orders.status help here? Justify with the numbers.
The query is SELECT u.country, SUM(o.amount) FROM orders o JOIN users u USING (user_id) WHERE o.status = 'completed' GROUP BY u.country. Propose two changes that would reduce the work, one at query level and one at physical design level.
Tier 3: this runs nightly and now takes 3 hours as orders grows. Describe your plan to bring it down, in order, using the checklist above.


Q2. Would an index on orders.status help here? Justify with the numbers.
"No. The scan read 50M rows and kept 48M, so the filter matches 96% of the table. An index would force millions of random lookups instead of one sequential pass, and the planner rightly chose a sequential scan. Indexes pay off on selective filters, and this one isn't. If we cared about the 4% non-completed rows, a partial index would make sense."


Q3. The query is SELECT u.country, SUM(o.amount) FROM orders o JOIN users u USING (user_id) WHERE o.status = 'completed' GROUP BY u.country. Propose two changes that would reduce the work, one at query level and one at physical design level.

The strongest fix is to stop recomputing from raw rows every night: maintain an incremental summary table, for example user_daily_revenue(user_id, order_date, revenue), updated only with the new day's completed orders. The nightly report then reads a table that is orders of magnitude smaller. This is the bridge to question 4.
Step 1: Ask what the query produces versus what it processes
How many rows does the join produce? 48,000,000.
How many rows does the final result have? One per country, so a couple of hundred at most.
So where is the waste? We push 48M rows through the join and into the aggregation, only to collapse them into a few hundred rows. The grain of the work (one row per order) is far finer than the grain of the answer (one row per country).

When the work is finer than the answer, the standard move is: aggregate earlier, at the finest grain the join actually needs. The join key is user_id, so we can aggregate orders to one row per user before joining.

Step 2: Query-level change (pre-aggregate before the join)
sql
WITH user_revenue AS (
  SELECT user_id, SUM(amount) AS revenue
  FROM orders
  WHERE status = 'completed'
  GROUP BY user_id            -- 48M rows -> at most ~1M rows
)
SELECT u.country, SUM(r.revenue) AS revenue
FROM user_revenue r
JOIN users u USING (user_id)
GROUP BY u.country;

Now the join is about 1M rows against 1M rows instead of 48M against 1M. The result is identical because SUM is decomposable: the sum of partial sums equals the total. The same holds for COUNT, MIN and MAX. AVG is not decomposable on its own, so you'd carry SUM and COUNT separately. Optimizers can sometimes push aggregation below a join automatically, but you shouldn't rely on it.

Step 3: Physical-design change

For this Postgres-style setup, a partial covering index:

sql
CREATE INDEX idx_orders_completed_user
  ON orders (user_id) INCLUDE (amount)
  WHERE status = 'completed';
It holds only the two columns the query needs, so an index-only scan reads far fewer bytes than scanning wide table rows.
It is sorted by user_id, which lets the engine stream the aggregation without a large hash table.

An honest caveat, connecting to your last answer: the benefit comes from reading narrower data, not from skipping rows, because the filter still matches 96%. It also depends on the table being vacuumed recently, so index-only scans work. The real trade-off is write cost and storage on a 50M-row table.

In a warehouse such as Snowflake or BigQuery, the columnar format already gives you the narrow read. There the physical-design lever would be clustering on user_id or building a summary table.

The lead-level answer to "how do we really fix this"

The strongest fix is to stop recomputing from raw rows every night: maintain an incremental summary table, for example user_daily_revenue(user_id, order_date, revenue), updated only with the new day's completed orders. The nightly report then reads a table that is orders of magnitude smaller. This is the bridge to question 4.


Q4. Tier 3: this runs nightly and now takes 3 hours as orders grows. Describe your plan to bring it down, in order, using the checklist above.
The spoken answer (about 2 minutes)

"I'd start by clarifying the requirements: what the SLA is, who consumes the report, and how fresh it needs to be. Then I'd follow a fixed sequence rather than jump to a fix.

First, measure. I'd pull the actual plan or query profile for the current run and the history of run times. If runtime grew linearly with table size, it's a scaling problem. If it jumped suddenly, I'd suspect a plan regression, stale statistics, or data skew.

Second, find the dominant cost and compare estimates to actuals. In the plan we saw, the scan and the 48M-row join dominate, and the final aggregation collapses all that to a few hundred rows. That tells me the work is at the wrong grain.

Third, cut the data volume. Select only the needed columns, filter on the partition key so pruning works, and keep predicates sargable.

Fourth, fix the grain. Pre-aggregate orders to one row per user before joining. SUM is decomposable, so the result is identical, and the join drops from 48M rows to about 1M.

Fifth, and this is the real fix, stop recomputing history. Completed orders from last year don't change, so I'd maintain an incremental summary table, such as user_daily_revenue, and have the nightly job process only new and changed data. The report then reads a table that's orders of magnitude smaller, and runtime stays flat as the raw table grows.

Last, scale compute only if still needed, because a bigger warehouse hides the problem and the cost keeps growing with the data.

I'd make sure the incremental load is idempotent and backfillable, add data quality checks, and monitor runtime and cost so we'd see this trend before it breaches the SLA."