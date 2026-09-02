# Advanced integration release audit

The branch adds a dedicated fail-closed release audit for the newer advanced-discovery production bridge.

Release-critical invariants now checked offline:

- package initialization actually installs `IntegratedScientificDiscoveryEngine` on the production `advanced_discovery` export;
- #40 tasks come from machine-normalized verification checks before public label simplification;
- three computational paths must all succeed and pairwise agree; R is invoked with generated allow-listed code, `shell=False`, timeout, minimal environment and strict numeric stdout protocol;
- three-way agreement is still not enough when the computed value disagrees with the claim's expected RHS;
- #103 debate arguments are reconstructed only from accepted independent retrieved evidence, instruction-like source text is excluded, missing author metadata never fabricates a person, and retracted sources cannot become reliable current evidence;
- repository implementation/test presence cannot be promoted into live/scientific/100% maturity proof.

The audit is static and zero-network. It complements, rather than replaces, behavioural pytest, the strict foundation gate and the separate live ₹0 release gate.
