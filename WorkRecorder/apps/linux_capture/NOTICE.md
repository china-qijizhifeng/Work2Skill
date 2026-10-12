# Source attribution

This component contains selected AT-SPI collectors adapted from the following local source trees:

- `collectors/a11y_daemon.py`: `MyPCBench/scripts/persist-introspection/a11y_daemon.py`. The MyPCBench tree includes an MIT license and a NOTICE; copies are in `licenses/MyPCBench-MIT.txt` and `licenses/MyPCBench-NOTICE.txt`.
- `collectors/event_watch.py`: `OSWorld/recording_files/guest/event_watch.py`. The OSWorld tree includes Apache License 2.0, retained in `licenses/OSWorld-Apache-2.0.txt`.

These local collector additions were not tracked by the source repositories at extraction time. The source-tree notices document provenance; they do not establish authorship of every local addition or relicense unrelated files. Preserve applicable upstream notices when distributing derivatives.

Changes made for WorkRecorder: desktop-user environment discovery replaces fixed UID 1000 assumptions; the internal tree port is configurable; tree request bounds are capped. The collectors are supervised by a new single-desktop service. The Mac launcher and service adapter do not include benchmark tasks, DOM collectors, real recordings, credentials, VM images, or multi-user deployment code.

The retained MyPCBench NOTICE describes third-party components in that upstream project; those unrelated components were not copied here.
