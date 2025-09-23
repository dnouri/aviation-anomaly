Remind yourself of our principles and methodology in CLAUDE.md and discuss them. Then read through TODO.md and consider where we are in the process. Have a virtual discussion with Kent and Tim about how to best apply our methodology to the next task in TODO.md, using ultrathink. Remember to follow Core Principles in CLAUDE.md and in the TODO.md:

- Don't mask errors in tests. Always fix at the right place.
- When you encounter failing tests, do proper root cause analysis. This will usually involve creating a minimal test case to reproduce the problem and disect it.
- Prefer testing against real or realistic data. Create spikes in tmp/ to inspect relevant data available in data/ to help you figure out data structure and distribution.
- When writing tests, look at existing test structure, including existing pytest fixtures in conftest.py. Also consider using pytest's monkeypath and tmp_path over other ways of patching.
- Prefer testing against real objects and data over creating mocks where possible.
- Don't write overly defensive code: fail fast.
- Use a pair programming approach with Kent and Tim to find the cleanest and most elegant solution in the refactor phase.

Don't forget to check off items in TODO.md as you progress.
