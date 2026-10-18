Interview version of CLOSURES
If an interviewer asks:
"Why does [lambda: i for i in range(3)] produce [2,2,2]?"

A strong answer is:
"Because Python closures use late binding. The lambdas close over the variable i, not a snapshot of its value. When the functions are eventually called, the loop has finished and i is 2, so all three return 2. Using lambda i=i: i captures the current value as a default argument."

That's a very good Python interview concept for us to keep in your notes.

2. Now look at your loop
funcs = [lambda: i for i in range(3)]


The loop goes:
i = 0 → create lambda
i = 1 → create lambda
i = 2 → create lambda

So you might imagine:
lambda 1 → remembers 0
lambda 2 → remembers 1
lambda 3 → remembers 2

But that's not what happens.
Instead, conceptually:
lambda 1 ─┐
lambda 2 ─┼──→ i
lambda 3 ─┘

All three functions refer to the same i.

3. What happens after the loop?
The loop finishes with:
i = 2


Now you call:
[f() for f in funcs]


Each function asks:
"What is i right now?"

And i is:
2

So:
f1() → 2
f2() → 2
f3() → 2

Therefore:
[2, 2, 2]


4. This is called a closure
A closure occurs when a function remembers/uses a variable from its surrounding scope.


