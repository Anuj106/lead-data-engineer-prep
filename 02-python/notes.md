Week 1, Python Lecture 2: Functions, Decorators, Context Managers, Exceptions, Retries, Logging

Create the branch if you haven’t: git switch -c w03-python. This lecture covers the code patterns that make a pipeline script production-grade, and they come up in both coding rounds and design discussions. Every example below is traced step by step.

Part 1: Functions Are Objects

In Python, a function is a value: you can store it, pass it to another function, and return it. Two argument features matter in practice:

python
def load(path, *, batch_size=500, retries=3):  # the * forces batch_size and retries to be passed by name
    ...

def log_call(fn, *args, **kwargs):   # *args = extra positional args as a tuple, **kwargs = extra keyword args as a dict
    return fn(*args, **kwargs)

Keyword-only arguments (after the bare *) prevent bugs like load("f.csv", 500, 3), where nobody remembers which number is which.

Part 2: Closures

A closure is an inner function that remembers variables from the function that created it, even after that outer function has returned.

python
def make_counter():
    count = 0
    def inc():
        nonlocal count
        count += 1
        return count
    return inc

c = make_counter()
c()   # 1
c()   # 2
d = make_counter()
d()   # 1  <- a separate counter with its own count

Trace: each call to make_counter() creates a fresh count. inc holds a reference to its own count, so c and d don’t interfere. nonlocal is needed because you are reassigning count, and without it Python would treat count as a new local variable.

The late-binding trap.

python
funcs = [lambda: i for i in range(3)]
[f() for f in funcs]        # [2, 2, 2], not [0, 1, 2]

All three lambdas look up i when called, by which time the loop has finished and i is 2. Fix: bind the value at creation, lambda i=i: i.

Part 3: Decorators

A decorator is a function that takes a function and returns a new function, usually wrapping the original with extra behavior. The syntax @timed above def load() is shorthand for load = timed(load).

python
import time, functools

def timed(fn):
    @functools.wraps(fn)                 # keeps fn's name and docstring
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            print(f"{fn.__name__} took {time.perf_counter() - start:.3f}s")
    return wrapper

@timed
def load(): ...

Trace of load(): you actually call wrapper, which starts the clock, calls the original load, and prints the elapsed time in finally (so it prints even if load raises). Without functools.wraps, load.__name__ would be "wrapper", which makes logs and debugging confusing.

A decorator with arguments needs one more layer: a function that takes the settings and returns the decorator. This is the retry decorator, one of the most common interview asks:

python
import random, time, functools, logging
log = logging.getLogger(__name__)

def retry(max_attempts=3, base_delay=1.0, retry_on=(ConnectionError, TimeoutError)):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    if attempt == max_attempts:
                        raise                                  # out of attempts: surface the error
                    delay = random.uniform(0, base_delay * 2 ** (attempt - 1))   # exponential backoff with jitter
                    log.warning("attempt %d failed (%s); retrying in %.1fs", attempt, e, delay)
                    time.sleep(delay)
        return wrapper
    return decorator

@retry(max_attempts=4, base_delay=0.5)
def fetch_page(url): ...

Why each piece matters:

Exponential backoff (waits grow: up to 0.5s, 1s, 2s...) gives a struggling service time to recover instead of hammering it.
Jitter (a random wait inside that range) stops many clients from retrying at the same instant and causing a “thundering herd.”
retry_on lists only transient errors. A ValueError from bad data won’t fix itself, so retrying it wastes time.
Bare raise re-raises the original error with its traceback intact.
Part 4: Context Managers

A context manager guarantees setup and cleanup around a block, even if an error occurs. You’ve used one already: with open(path) as f.

Two ways to write one:

python
# Class-based
class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self
    def __exit__(self, exc_type, exc, tb):
        self.elapsed = time.perf_counter() - self.start
        return False            # False = don't swallow exceptions

# Generator-based: shorter, same idea
from contextlib import contextmanager

@contextmanager
def db_transaction(conn):
    try:
        yield conn              # the "with" body runs here
        conn.commit()
    except Exception:
        conn.rollback()
        raise

Trace of with db_transaction(conn) as c: c.execute(...):

Code before yield runs (setup).
The with body runs.
If the body succeeds, the code after yield runs and the transaction commits. If the body raises, control goes to except, rolls back, and re-raises.

The rule on __exit__: returning True suppresses the exception, which is almost never what you want. Return False (or nothing) so errors propagate.

Part 5: Exceptions Done Properly
python
try:
    row = parse(line)
except ValueError as e:                 # catch the specific error you can handle
    bad_rows.append((line, str(e)))
else:
    good_rows.append(row)               # runs only if no exception occurred
finally:
    stats["seen"] += 1                  # runs always

Rules to internalize:

Catch specific exceptions. A bare except: or except Exception: pass silently swallows bugs, including typos, so the pipeline “succeeds” with missing data. This is among the worst habits in data code.
Chain errors to keep the cause: raise IngestError("bad batch 17") from e.
Define your own exception types (class TransientError(Exception), class BadRecordError(Exception)) so callers can handle the two cases differently: retry transient failures, quarantine bad records.
Decide the failure policy for bad records: skip and count, send to a dead-letter file, or fail fast. Whichever you pick, make it visible in logs and metrics.
Part 6: Logging

Use the logging module, never print, in pipeline code.

python
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s run=%(run_id)s %(message)s")
log = logging.getLogger("ingest")
log.info("loaded %d rows from %s", n, path)     # lazy formatting: pass args, not an f-string
log.exception("batch failed")                    # inside except: logs the message plus the traceback

Levels: DEBUG (detail), INFO (milestones), WARNING (recoverable oddities such as a retry), ERROR (a failure), CRITICAL (the system can’t continue). Put context in every message (run id, source, batch number), and never log secrets or personal data.

Part 7: The Lead-Level Layer
Retries are only safe on idempotent operations. If a POST that creates a record times out after the server processed it, retrying creates a duplicate. Fixes: idempotency keys, upserts (MERGE), or checking “did it already happen?” before retrying. This is the most important sentence in this lecture.
Always set timeouts. A call with no timeout can hang forever, and retry logic never gets the chance to run.
Bound the total retry time, not only the attempt count, and respect server hints (an HTTP 429 Retry-After header).
Know where retries belong. In Airflow, task-level retries and retry_delay handle whole-task failure, while in-code retries handle small transient calls. Don’t stack both blindly, since 3 × 3 = 9 attempts can surprise you.
Make failures observable: count retries, failures and quarantined records, and alert on rates, not on single events.
Atomic writes. Write output to a temporary file, then rename it into place (os.replace), so readers never see a half-written file. This links to idempotent partition overwrites in warehouses.
Check Your Understanding
Rewrite @timed def load() without the @ syntax. Why is functools.wraps there?
In the retry decorator, why does the wrapper raise on the last attempt instead of returning None?
What happens if __exit__ returns True?
Name a situation where retrying makes things worse.
Homework (about 2 hours; into 02-python/exercises.py and interview.md)

Debug and explain:

python
# a
funcs = [lambda: i for i in range(3)]

# b
try:
    process(batch)
except Exception:
    pass

# c
@retry(max_attempts=5)
def create_order(payload):          # POSTs a new order to an API
    ...

Coding:

A @timed decorator that logs the duration through logging, including when the function raises. [10 min]
Your own retry decorator from scratch (no copying): exponential backoff, jitter, configurable exceptions. Test it with a flaky function that fails twice and then succeeds. [20 min]
A context manager atomic_write(path) that writes to a temp file and renames it only if the block succeeds, leaving no partial file on error. [15 min]
upload_in_batches(records, size), using chunks from Lecture 1 and retry: failed batches go to a dead-letter list, and the function returns counts of succeeded and failed records. [20 min]
Configure logging so every message includes a run_id. [10 min]

Tier 2: an API returns HTTP 429 with a Retry-After header. How does your retry logic change?

Tier 3: design a restartable ingestion job: a checkpoint after every N batches, idempotent writes, and what gets logged and alerted on.

For 02-python/notes.md: Python syllabus checklist (commit-ready)
markdown
## Python syllabus
- [x] Data structures and complexity
- [x] Iterators, generators, memory-aware processing
- [x] Mutability traps, common idioms
- [x] Functions, closures, decorators, retry/backoff
- [x] Context managers, exceptions, logging
- [ ] Classes, dataclasses, typing, pytest
- [ ] pandas essentials, vectorization, performance
- [ ] Concurrency: threads, processes, asyncio, the GIL
- [ ] File formats and I/O: CSV, JSON, Parquet, compression
- [ ] datetime and timezones, regex
- [ ] API ingestion: pagination, rate limits, idempotent loads
- [ ] Mini end-to-end pipeline

Send answers as you finish them, partial is fine, and I’ll grade them for correctness, edge cases, idempotency awareness and production habits. Python Lecture 3 (classes, dataclasses, typing, pytest) is next whenever you’re ready.
----------------------------------------------------------------------------------------------------------------------------------------------------
extra notes - in deep
Fair point. That lecture compressed five topics into one reading, which is enough to recognize the ideas but not enough to own them. Decorators in particular sit on top of two other ideas, so if either one is shaky, the retry example looks like magic. I’ll fix that two ways: a deeper pass on the hardest part now, and a better note format going forward.

Deep Dive: Closures → Decorators → Decorators with Arguments
Step 1: A function is an object you can pass around
python
def greet(name): return f"hi {name}"
say = greet          # no parentheses: copies the reference, doesn't call anything
say("Asha")          # "hi Asha"

greet is just a name pointing at a function object. say is a second name for the same object. Keep this picture, because the rest depends on it.

Step 2: A function can create and return another function
python
def make_multiplier(n):
    def multiply(x):
        return x * n
    return multiply

double = make_multiplier(2)
triple = make_multiplier(3)
double(10)   # 20
triple(10)   # 30

When make_multiplier(2) returns, the call is over and its local n would normally be gone. But multiply still uses n, so Python keeps n alive, attached to multiply. That attached variable is the closure. You can see it:

python
double.__code__.co_freevars   # ('n',)   <- "free variables" the function carries with it

double carries n = 2 and triple carries n = 3. They are separate function objects with separate captured values.

Mental model: a closure is a function plus a backpack of the outer variables it uses.

Step 3: A decorator is “a function that takes a function and returns a function”

Put steps 1 and 2 together. Instead of capturing a number, capture a function:

python
def shout(fn):                      # takes a function
    def wrapper(*args, **kwargs):   # builds a new function...
        result = fn(*args, **kwargs)    # ...that calls the original (fn is in the backpack)
        return result.upper()
    return wrapper                  # returns the new function

def greet(name): return f"hi {name}"

greet = shout(greet)    # replace the name with the wrapped version
greet("Asha")           # "HI ASHA"

The @ syntax is only shorthand for that reassignment line:

python
@shout
def greet(name): return f"hi {name}"
# means exactly: greet = shout(greet)

Trace of greet("Asha") after decoration:

The name greet now points to wrapper, so you are calling wrapper("Asha").
wrapper calls the original greet (held in its backpack as fn), which returns "hi Asha".
wrapper uppercases it and returns "HI ASHA".

Why *args, **kwargs: the wrapper doesn’t know what arguments the original takes, so it accepts anything and forwards it all unchanged.

Why functools.wraps(fn): after decoration, greet.__name__ would say "wrapper". @functools.wraps(fn) copies the original name and docstring onto the wrapper, so logs, stack traces and help text stay readable.

Step 4: Decorators with arguments, three layers

@retry(max_attempts=4) has parentheses, and that changes what Python does. Expand it:

python
@retry(max_attempts=4)
def fetch(url): ...
# means: fetch = retry(max_attempts=4)(fetch)

Read it inside out:

retry(max_attempts=4) runs first and returns a decorator.
That decorator is called with fetch and returns a wrapper.
fetch now points to the wrapper, which does the real work on every call.

So the structure always has three levels:

python
def retry(max_attempts):          # level 1: receives the settings
    def decorator(fn):            # level 2: receives the function
        def wrapper(*a, **kw):    # level 3: runs on every call
            ...
        return wrapper
    return decorator

max_attempts (level 1) and fn (level 2) are both in the wrapper’s backpack. This is why decorators with arguments feel confusing: three nested defs, each with one job.

Step 5: Stacking decorators
python
@tag("A")
@tag("B")
def f(): print("body")
# means: f = tag("A")(tag("B")(f))

The decorator closest to the function wraps it first. Calling f() prints:

enter A
enter B
body
exit B
exit A

Like layers of an onion: outer wrapper runs first on the way in, last on the way out. This matters for real cases, such as putting @timed outside @retry (timing all attempts) versus inside (timing one attempt).

Common bugs
Bug	Symptom	Fix
Wrapper forgets return fn(...)	Decorated function returns None	Return the result
No functools.wraps	Wrong __name__ in logs	Add it
@retry used without parentheses when it takes arguments	TypeError	Write @retry() or support both forms
Decorating a method	Works, because self arrives inside *args	Nothing to fix, but know why

To support both @retry and @retry(max_attempts=4):

python
def retry(_fn=None, *, max_attempts=3):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            ...
        return wrapper
    return decorator(_fn) if _fn else decorator
Interview questions on this topic
What does @decorator desugar to?
What is a closure, and how would you prove a function has one? (__code__.co_freevars)
Why do decorators with arguments need three nested functions?
In what order do stacked decorators run?
Write a @timed decorator on a whiteboard, from memory.
Where would you not use @retry? (Non-idempotent operations.)
Exercise (20 minutes, before the homework)

On paper, trace @tag("A") @tag("B") def f() and write the printed output without running it. Then run it and compare. If your trace disagrees, find which step in the onion you misread.

A better note format for every topic from now on

Each concept in notes.md will get this seven-part structure, so notes aren’t just a summary:

markdown
### <Concept>
1. Why it exists (the problem it solves)
2. Mental model (one picture or analogy)
3. Step-by-step trace (a small example, by hand)
4. Variations
5. Pitfalls and bugs
6. Interview questions
7. Lead-level layer (scale, tradeoffs, failure)

The material above follows that structure, so you can copy it into 02-python/notes.md and rewrite it in your own words.

I’ll teach the rest the same way, and I can redo context managers, exceptions and logging at this depth too. Do you want that next, or would you rather move on to Lecture 3 and see whether the new format works for you?
----------------------------------------------------------------------------------------------------------------------------------------------------