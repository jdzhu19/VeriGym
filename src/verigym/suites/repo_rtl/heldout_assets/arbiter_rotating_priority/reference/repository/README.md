# Three-client rotating arbiter

This repository contains a synchronous three-client arbiter. At most one requester is granted
per cycle. After a grant, the next arbitration must begin with the client immediately following
the winner, wrapping from client 2 to client 0.

The active-low synchronous reset establishes client 0 as the initial priority. The combinational
grant reflects the current request vector and registered rotation pointer.
