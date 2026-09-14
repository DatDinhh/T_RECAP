# Reference runtime contract

Ordinary runs are read-only with respect to the source vector directory and coefficient directory. The C++ runner and Python wrappers write only to a separate, new or empty output directory.

The CLI requires a complete trecap_phase2_vector_config_v1 configuration. It checks baseline geometry, protection flags, widths, FFT/rounding/tail/threshold modes, row counts, canonical input hash, and hashes of the coefficient files it actually reads. Unknown metadata remains in the copied source configuration. Required numeric and string fields retain their JSON types; duplicate keys and malformed JSON are rejected.

The sole permitted arithmetic override is an explicit --thr2 in the legal magnitude-squared domain. It affects the result configuration without rewriting the input configuration. Other baseline changes require a deliberate contract change; changing a JSON label cannot change the compiled model.

One run has one threshold. A source configuration does not describe cycle-level scheduling or commit events. Public library calls require matching run, window, twiddle, and OLA configurations; coefficient tables with independently defaulted baseline configuration cannot silently override caller settings.

The runtime output contains two distinct configurations:

- source_config.json: exact bytes of the source input configuration, retaining generator provenance;
- config.json: generated effective configuration and output hashes for this run.

The run.json metadata records the source configuration hash, coefficient directory, input location, threshold-override status, and reference_output lifecycle. Suite metadata lives in output run_manifest.json. These runtime files are not a frozen release manifest and do not update imported provenance.

The explicit write_vector_artifacts library API remains available for legacy artifact-authoring callers. It can write an input bundle, and must not be used for a read-only runtime invocation. The executable uses write_reference_outputs.

The default coefficient directory for the direct executable is artifacts/coefficients relative to its working directory; Python wrappers default to the package's coefficient directory. Pass --coeff-dir when using a different checked-in snapshot.

This contract describes implemented software behavior. It does not assert that a verification campaign or hardware validation has been completed.
