# Changelog

## 3.0.0 — Desktop release

- Productized the Bazzite-validated V2.6.1/2.6.2 stable module layout.
- Introduced a user-local KDE menu launcher, packaged SVG icon and versioned application installation.
- Added preflight checks, release integrity verification and non-destructive launcher uninstall.
- Kept existing theme engine, baseline, Konsole profile, gallery and Matugen workflow intact.
- Added installer regression tests and GitHub-ready source organization (without user data).
- Preserved old `app/` and `backups/` as fallbacks, with no automatic cleanup of active data.
- Source supports manual GitHub publication under a future account; no remote repository is created automatically.

## 2.6.2 — Engineering quality candidate

- 18 offline tests plus read-only cleanup inventory, with core runtime unchanged from V2.6.1.

## 2.6.1 — Engineering refactor

- Unified package entrypoint and module names; runtime diagnosis; dynamic containment mapping; registered wallpaper folders; concurrency lock and recovery copies.
- User-validated Bazzite KDE behavior: dual wallpapers, color themes, direct switching, baseline recovery and subsequent reapplication.
