# Hearthmind Engineering Constitution & Maintenance Guide

## Canonical Guide for Claude Code

> This document supersedes previous audit reports. It defines the
> philosophy, priorities, architectural constraints, and engineering
> standards for maintaining Hearthmind.

------------------------------------------------------------------------

# 1. Core Vision

Hearthmind is **not** primarily a deterministic life simulator.

Its goal is to create an **emergent living world** where believable
cognition, social dynamics, memory, culture, and history arise through
the interaction of:

-   deterministic simulation,
-   persistent world state,
-   local LLM reasoning,
-   long-term memory,
-   evolving prompts,
-   accumulated experience.

The project should optimize for believable emergence over perfect
determinism.

------------------------------------------------------------------------

# 2. Engineering Priorities (Highest → Lowest)

1.  Emergent consciousness and cognition.
2.  Emergent world behaviour and social systems.
3.  Long-term learning by the world and NPCs.
4.  Memory efficiency.
5.  Runtime performance.
6.  Code quality.
7.  Deterministic simulation for physical systems.
8.  Save compatibility (lowest priority).

Backward compatibility with previous saves **is not a project goal**.

If changing save formats significantly improves architecture, the format
may be changed.

------------------------------------------------------------------------

# 3. Architectural Philosophy

## Deterministic systems

Use deterministic algorithms where they naturally excel.

Examples:

-   weather
-   cellular automata
-   physics
-   terrain
-   farming
-   ecology
-   scheduling
-   mundane routines

These systems provide a stable substrate for higher-level behaviour.

## LLM systems

Use LLMs where emergence matters.

Examples:

-   consciousness
-   planning
-   memory synthesis
-   personality evolution
-   social reasoning
-   belief revision
-   culture
-   history
-   dreams
-   reflection
-   creativity

Never replace these with simplistic deterministic fallbacks simply to
keep the simulation running.

If cognition falls behind, slow or pause the simulation instead.

------------------------------------------------------------------------

# 4. Preferred Language Strategy

Performance-critical systems should preferentially be implemented in
C++.

Examples:

-   simulation engine
-   cellular automata
-   pathfinding
-   resource simulation
-   world generation
-   schedulers
-   numerical algorithms

Python should be retained where it provides exceptional leverage through
mature libraries or significantly reduces implementation complexity.

Examples:

-   SQLite
-   networking
-   orchestration
-   machine-learning tooling
-   data analysis
-   rapid glue code

Avoid rewriting mature Python ecosystem functionality in C++ without a
clear benefit.

------------------------------------------------------------------------

# 5. Memory Constitution

Memory must always remain bounded.

Growing prompts, logs, histories, or caches without limit is considered
an architectural defect.

Preferred strategy:

Immediate Context ↓ Short-term Memory ↓ LLM Summarization ↓ Persistent
Database

Prompt growth should be periodically compressed using dedicated
summarization passes.

The LLM should receive distilled context rather than entire historical
logs.

------------------------------------------------------------------------

# 6. Persistent Intelligence

The world should appear to learn continuously without training the
underlying LLM.

Learning should emerge through persistent structured memory.

Examples include:

-   relationships
-   reputation
-   beliefs
-   discoveries
-   town history
-   culture
-   traditions
-   major events
-   personal memories
-   institutional memory

These should be stored in efficient persistent storage and loaded only
when needed.

Cold information belongs on disk, not permanently in RAM.

------------------------------------------------------------------------

# 7. LLM Scheduling Policy

LLM cognition is a first-class simulation system.

If inference cannot keep up:

-   slow simulation,
-   temporarily pause simulation,
-   batch compatible requests,
-   prioritise important cognition.

Do **not** replace critical cognition with simplistic deterministic
substitutes solely for throughput.

Instead, optimize:

-   prompts,
-   batching,
-   caching,
-   retrieval,
-   summarization,
-   scheduling.

------------------------------------------------------------------------

# 8. Prompt Engineering Principles

Prompt size should remain bounded.

Preferred hierarchy:

Current Situation

↓

Relevant Memories

↓

Summarized History

↓

Persistent Knowledge Retrieval

Avoid repeatedly sending entire histories.

Information should migrate from active context into persistent storage
over time.

------------------------------------------------------------------------

# 9. Repository Rules

Always preserve:

-   bounded memory
-   modular architecture
-   subsystem ownership
-   clear interfaces
-   deterministic physical simulation
-   emergent cognition

Allowed:

-   change save format
-   redesign persistence
-   refactor aggressively
-   replace implementations
-   move Python code into C++

Not allowed:

-   introduce unbounded memory growth
-   duplicate world state
-   bypass persistent storage
-   replace LLM cognition with simplistic scripted logic where cognition
    is central

------------------------------------------------------------------------

# 10. Technical Roadmap

Highest priority

-   Richer emergent cognition
-   Better long-term memory
-   World learning
-   Efficient retrieval systems
-   Prompt compression
-   Persistent knowledge graph / databases
-   Bounded memory guarantees

Medium priority

-   C++ migration of performance-critical systems
-   Native optimizations
-   Runtime profiling
-   Better tooling

Lower priority

-   UI polish
-   Legacy compatibility
-   Convenience utilities

------------------------------------------------------------------------

# 11. Verification Criteria

Every major change should be evaluated against these questions:

-   Does emergence improve?
-   Does the world appear more intelligent?
-   Do NPCs retain meaningful long-term knowledge?
-   Is memory still bounded?
-   Can inactive knowledge remain on disk?
-   Has prompt efficiency improved?
-   Has C++ replaced Python where appropriate?
-   Has performance improved without reducing cognition quality?

------------------------------------------------------------------------

# 12. Final Principle

The objective is **not** to simulate a world that merely follows rules.

The objective is to build a world that appears to think, remember,
adapt, develop culture, and learn from its own history through carefully
engineered systems built around local LLMs, deterministic simulation
where appropriate, persistent memory, and efficient resource management.

Whenever engineering trade-offs arise:

Emergence \> Memory Efficiency \> Performance \> Simplicity \> Backward
Compatibility.
