# Architecture

How ComfyUI Studio is built, how it boots, how it updates, and where everything lives.

- [System Overview](overview.md) — the big picture: Docker image, persistent volume, two services
- [Docker Image](docker-image.md) — what's baked in and what's not
- [Bootstrap Flow](bootstrap-flow.md) — first boot sequence: clone, copy, start
- [Update Mechanism](update-mechanism.md) — how Check for Updates works
- [Runtime Versioning](runtime-versioning.md) — Docker image compatibility system
- [Directory Layout](directory-layout.md) — every file and directory explained
