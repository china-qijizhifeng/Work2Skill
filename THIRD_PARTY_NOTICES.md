# Third-party notices

The root MIT license covers original Work2Skill contributions. It does not replace third-party licenses, copyright notices, or terms for externally hosted datasets.

## MyPCBench

The downstream task variants in `DownstreamTasks/tasks-jitter.json` derive from [MyPCBench](https://github.com/ljang0/MyPCBench). The Linux accessibility collector also includes adaptations associated with that project. Preserve its [MIT license](WorkRecorder/apps/linux_capture/licenses/MyPCBench-MIT.txt) and [NOTICE](WorkRecorder/apps/linux_capture/licenses/MyPCBench-NOTICE.txt).

## OSWorld

The Linux event collector includes adaptations associated with [OSWorld](https://github.com/xlang-ai/OSWorld). Its [Apache License 2.0](WorkRecorder/apps/linux_capture/licenses/OSWorld-Apache-2.0.txt) is retained. The task ID list identifies OSWorld-Verified tasks; it does not include the benchmark environments or redistribute their data.

The collector-specific [source attribution](WorkRecorder/apps/linux_capture/NOTICE.md) documents provenance, local additions, and modifications. Its qualifications remain applicable.

## Dependencies and external data

NexAU and other dependencies retain their respective licenses. The linked WorkDemo-350 dataset is hosted separately and is not relicensed by this source repository.

## Synthetic test material

`WorkRecorder/tests/fixtures/workbench/synthetic-inspect.json` contains original, fictional article and OCR text, example-domain URLs, and synthetic identifiers. The text is covered by the root MIT license and does not reproduce the previously used third-party article.
