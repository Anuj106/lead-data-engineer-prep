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