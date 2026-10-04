----------------------
SARGABLITY
----------------------
Sargability: Why WHERE amount * 2 > 100 Is Worse Than WHERE amount > 50
The idea

SARGable means Search ARGument-able. A predicate is sargable when the engine can use an index (or partition metadata) to jump directly to the matching rows instead of testing every row.

Why the function breaks it

An index on amount is a sorted structure of the raw stored values, like a phone book sorted by last name.

WHERE amount > 50: the engine binary-searches the sorted index to the first value above 50 and reads from there. Cost: roughly O(log n) plus the matching rows.
WHERE amount * 2 > 100: the index is sorted by amount, not by amount * 2. The engine cannot navigate it with your expression, so it must read every row, compute amount * 2, and then compare. Cost: O(n), a full scan.

The rule of thumb: keep the column bare on one side of the comparison, and move all computation to the other side.
The rule of thumb: keep the column bare on one side of the comparison, and move all computation to the other side.

Common non-sargable patterns and their rewrites
Non-sargable	Sargable rewrite	Why
WHERE YEAR(order_date) = 2025	WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'	Range on the raw column
WHERE DATE(created_at) = '2026-10-03'	WHERE created_at >= '2026-10-03' AND created_at < '2026-10-04'	Half-open range
WHERE LOWER(email) = 'a@b.com'	Store emails normalized, or use a functional index	Function on column
WHERE amount + 10 > 100	WHERE amount > 90	Algebra moved to the constant side
WHERE name LIKE '%son'	Avoid leading wildcard; use full-text/trigram search	Sorted order can't help a suffix match
WHERE varchar_col = 123	WHERE varchar_col = '123'	Implicit cast applied to the column

Note the half-open range (>= start AND < next_start) in the date rewrites. It avoids the classic bug where BETWEEN with end-of-day timestamps drops or double-counts boundary rows.


-------------------------------------
Left JOIN with 1 x M relationship
----------------------------------------
A LEFT JOIN from users to orders returns more rows than users has. Why, and is that a bug?

"It's not a bug by itself. The left join preserves every user, and users with several orders produce several rows, so the grain shifts from user to order. It becomes a bug if I then aggregate a user-level column and double-count, or if the right side was meant to be unique and isn't. I'd check the grain on both sides before joining, and if I need user-level output I'd pre-aggregate orders in a CTE first. In a pipeline I'd also add a uniqueness test on the join key, for example a dbt unique test, so fan-out can't appear silently."



-----------------------------------
Here is a simplified Postgres-style plan. orders has about 50M rows, users about 1M.

Hash Join  (actual time=4200..9800 rows=48000000)
  Hash Cond: (o.user_id = u.user_id)
  ->  Seq Scan on orders o  (actual time=0.02..3900 rows=48000000)
        Filter: (status = 'completed')
        Rows Removed by Filter: 2000000
  ->  Hash  (actual time=310..310 rows=1000000)
        ->  Seq Scan on users u  (actual time=0.01..140 rows=1000000)
Which join algorithm is used, and which table is the hash table built on? Why is that a sensible choice?

The complete answer
Size and memory. Building on the smaller input keeps the hash table small enough to stay in memory. If it didn't fit, the engine would split the join into batches and spill to disk, which is much slower.
Cost shape. The cost is roughly one pass over the build side plus one pass over the probe side, each row doing an O(1) hash lookup. That is linear in the input sizes.
Uniqueness helps, with the right framing. user_id is unique in users (a primary key), so each order probes at most one match. That keeps bucket chains short and probing cheap. You can also confirm it from the plan: the join emits 48,000,000 rows, equal to the filtered orders rows, so there was no fan-out.
Why not the alternatives?
Nested loop would do 48M probes into users. That is only reasonable with an index and a small outer side.
Sort-merge would need to sort 48M rows first, which is expensive, unless the inputs were already sorted.

--------------------------------------
Grain of WORK v/s Grain of Answer
--------------------------------------
Q The query is SELECT u.country, SUM(o.amount) FROM orders o JOIN users u USING (user_id) WHERE o.status = 'completed' GROUP BY u.country. Propose two changes that would reduce the work, one at query level and one at physical design level.
When the work is finer than the answer, the standard move is: aggregate earlier, at the finest grain the join actually needs. The join key is user_id, so we can aggregate orders to one row per user before joining.

The lead-level answer to "how do we really fix this"

The strongest fix is to stop recomputing from raw rows every night: maintain an incremental summary table, for example user_daily_revenue(user_id, order_date, revenue), updated only with the new day's completed orders. The nightly report then reads a table that is orders of magnitude smaller. This is the bridge to question 4.

-------------------------------
The nightly report now takes 3 hours as orders grows. How do you bring it down?
---------------------------------
The depth behind each claim (what you say if probed)

1. Handling mutable data. The sharp follow-up is: "Orders change status. What about refunds or late-arriving data?" Your design must cover it:

Reprocess a trailing window (for example, the last 7 to 30 days) every night, instead of only yesterday, to catch late updates.
Or consume change data capture (CDC), or an updated_at watermark, and apply changes with a MERGE.
Periodically run a full reconciliation against the source (weekly, say) to catch drift, and alert on any difference.

2. Idempotent load. The job must be safe to re-run without double-counting. Use a partition overwrite or a MERGE keyed on (user_id, order_date), never a blind INSERT:

sql
MERGE INTO user_daily_revenue t
USING (
  SELECT user_id, order_date, SUM(amount) AS revenue
  FROM orders
  WHERE status = 'completed'
    AND order_date >= CURRENT_DATE - INTERVAL '7 days'
  GROUP BY user_id, order_date
) s
ON t.user_id = s.user_id AND t.order_date = s.order_date
WHEN MATCHED THEN UPDATE SET revenue = s.revenue
WHEN NOT MATCHED THEN INSERT (user_id, order_date, revenue) VALUES (s.user_id, s.order_date, s.revenue);

One gap in this version: if all of a user's orders on a day are refunded, no source row exists for that key and the stale target row stays. A production version also needs to zero out or delete keys that disappear from the recomputed window. Mention this if asked, as it is the kind of edge case that signals real experience.

3. Backfill. Parameterize the job by date range so you can rebuild any period. Partitioning the summary table by order_date makes partition-level overwrite cheap.

4. Data quality. Add checks that run before consumers read the data: row count and revenue reconciliation against the source for the recomputed window, uniqueness on (user_id, order_date), and a NULL-rate check on amount. Fail the job rather than publish a wrong number.

5. Observability and cost. Track runtime, bytes scanned and cost per run, with an alert on a trend (for example, 30% over the 7-day average) instead of waiting for an SLA breach. Add a partition filter requirement on the large table so no one can accidentally scan it fully.

6. Trade-offs to state out loud.

Incremental vs. full recompute: faster and cheaper, but more complex, with a risk of drift. Mitigated by the trailing window and reconciliation.
Summary table vs. raw queries: the summary fixes one report's pattern. If analysts need new dimensions, they need the raw table or a more general aggregate. A well-chosen grain (user and day) serves many future questions.
Freshness: if the business later wants intraday numbers, this evolves toward streaming or micro-batch ingestion, and I'd raise that as the next step.

7. Organizational angle (this is what makes it lead-level). Say who you would involve and how you'd roll it out: validate the new table against the old report in parallel for a week, communicate the change to the report's consumers, document the metric definition once, and write a short design doc so the team owns it after you.

How to use this
Do not paste it into your repo verbatim. Rewrite it in your own words in 01-sql/interview.md, including the MERGE gap I flagged. Your own phrasing is what you'll be able to say under pressure.
Add one line to mistakes.md if anything surprised you, tagged [sql].
Practice saying the spoken version out loud with a timer. Aim for under 2 minutes without notes.


------------------------------------

---------------------------------------
