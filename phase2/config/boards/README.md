# Board configuration and checkpoint scope

This directory contains board contracts and physical design ledgers. Each file's
schema and contract stage define its purpose; checkpoint evidence fields are not
a live inventory of the build directory or hardware state.

`de1soc_clock_reset_architecture.json` is the frozen Step-10 source checkpoint.
Its status, deferred-constraint, and generated-HDL/SDC-presence fields record that
original checkpoint. The v1 schema and checkpoint checker retain those values for
historical consistency. RTL and HPS runtime code do not consume these fields;
source/package tools retain the contract as provenance. A copied checkpoint in a
build manifest does not mean the current build lacks generated products.

Current physical policy comes from [physical_timing.json](physical_timing.json)
and the executable [clocks.sdc](../../constraints/de1soc/clocks.sdc) and
[de1soc.sdc](../../constraints/de1soc/de1soc.sdc). Current implementation results
are in the run manifests and
[architecture_implementation.md](../../docs/architecture/architecture_implementation.md);
[build_order.md](../../docs/architecture/build_order.md) defines acceptance gates.
The historical Step-10 deferrals neither disable these constraints nor waive
current timing, CDC, pin, or deployment requirements. Source and fitted evidence
do not establish functional verification or physical board operation.
