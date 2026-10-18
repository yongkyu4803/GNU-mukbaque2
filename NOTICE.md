# Source attribution

This repository contains an independently runnable FastAPI/web application built on the leucine-zipper research engine from:

- Upstream: https://github.com/mukbaque2/LZ-program
- Source revision: `9b72e00cfd793a27de0bf37cccabea40064f9743`
- Copyright (c) 2026 강민성 (Minsoung Kang)
- License: MIT; the original copyright and license text are preserved in [LICENSE](LICENSE).

The original checkout directory and its Git history are excluded. Runtime-required engine files (`lz/`, excluding the newly added calibration module), the default sequence library and engine regression tests are retained as source files. Changes include progress/input validation for design, complete calibration persistence, the HTTP service/worker, the web client and standalone startup tooling.

Bundled font attribution and the Pretendard OFL are retained under `client/public/fonts/` and `web/fonts/`. KIMM is used unchanged from the user's installed font. Its internal family name is KIMMBold. The source project's MIT license does not relicense third-party fonts.
