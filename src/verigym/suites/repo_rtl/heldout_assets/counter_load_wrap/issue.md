# Repair synchronous load and decade wrap

The visible counter must count from 0 through 9 and then wrap to 0. A synchronous `load`
operation has priority over `enable`, including when both inputs are asserted together. Reset has
highest priority and sets the count to zero. When neither load nor enable is asserted, the count
must hold. Valid load values are in the range 0 through 9.

Modify only the allowed RTL sources. Use the trusted public-test launcher for visible checks.
