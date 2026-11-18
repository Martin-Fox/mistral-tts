# Roadmap

[Documentation](README.md) · [Project overview](../README.md)

- [x] **Integrated Translation:** Direct translation from Language A to Language B using configurable Mistral chat models (default: `ministral-8b-latest`, with support for Small, Medium, Large) before the TTS phase.
- [x] **Interactive WebUI:** A responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Containerize the application, bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Session Authentication:** One shared account with expiring session cookies. Multiple user accounts are not implemented; remote deployment requires HTTPS.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC) provided by a self-hosted Pocket ID instance for single sign-on.
- [ ] **Multi-User Login:** Support multiple user accounts and sessions, paving the way for personalized histories, settings, and task queues.
- [ ] **CLI User Management:** Add command-line interface options to create, update, and manage user accounts securely, keeping user-creation tools out of the WebUI.
- [ ] **WebUI About Modal & Current Version Display:** Add a menu item / modal for "About" that displays application metadata, current version (e.g. 1.0.2), license, and project links.
- [ ] **WebUI Help / Quick Guide:** Interactive help or documentation drawer/modal explaining parameters (chunking, temperature, voices, engines, loudnorm) and troubleshooting tips.
- [x] **Robust Task State Management:** SQLite task state, explicit restart recovery and conservative storage retention protect active/resumable jobs.
- [x] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [x] **MOBI Support:** Parse trusted local CLI/TUI files; WebUI upload/resume remains disabled until extraction is isolated.
- [x] **OpenAI TTS Integration:** Support the OpenAI TTS API as an alternative synthesis engine using preset voices.
- [x] **Audio Truncation Safeguard & Duration Verification:** Enforce end-to-end duration verification and trailing silence padding.
- [x] **Standalone Windows Packaging:** PyInstaller specification and build workflow exist; native artifact acceptance remains pending.
