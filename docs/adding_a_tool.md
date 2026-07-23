# Adding a tool

Implement `ToolPlugin` from `verigym.plugin_api` and register it in `verigym.tools`. Define a
strict request model, health check, argument-array command, bounded result parser, and descriptor
visibility.

Commands must use validated tokens and `shell=False`. Reject absolute/traversing paths, links,
special files, unchecked hard links, unsafe identifiers, and unbounded output. Write artifacts
only through the supplied tool context. Classify candidate failures separately from missing
dependencies and infrastructure failures.

Declaring a plugin does not make it agent-visible: the task’s frozen tool policy must allow it.
Tests should cover hostile filenames/fields, parser bounds, timeout/resource errors, hidden-path
denial, deterministic artifacts, and safe diagnostics.
