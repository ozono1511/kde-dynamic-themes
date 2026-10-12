# Dependencies and update policy

- **Operating system:** Bazzite Fedora Atomic (user-tested). No root permissions or layering required.
- **KDE:** Plasma 6, `plasma-apply-colorscheme`, `plasma-apply-wallpaperimage`, `kreadconfig6`, `kwriteconfig6`, Konsole with a configured default `.profile`.
- **Python:** 3.12–3.14, user's current 3.14-based setup is the release reference.
- **PySide6:** 6.11.x, declared as an optional GUI dependency (`>=6.11,<6.12`). The release intentionally uses the working host installation, avoiding an untested `pip` download, Qt plugin mismatch or extra background services. Python/Qt binary compatibility must be checked after OS upgrades.
- **Matugen:** 4.2.x executable already in `~/Projects/kde-dynamic-themes/bin/matugen`; supplied by the user, NOT bundled here. The application validates color data before applying.
- **Test runner:** pytest (`>=8,<10`) is only needed for developers, not end users.

## Update discipline

1. Run `kde-dynamic-themes --doctor` after relevant Bazzite/Plasma upgrades. Stop theme application if desktop containment mapping is ambiguous.
2. Run the offline CI tests on supported Python versions.
3. Verify in the Bazzite session that UI, colors, direct theme switching, stable recovery and both monitors work.
4. Install future releases into separate versioned directories and update the managed `current` symlink only after successful checks. Retain a tested rollback version.
5. Upgrade PySide6 and Matugen deliberately after testing; **do not auto-upgrade runtime dependencies** as part of theme application.

Fedora KDE/Arch KDE remain intentionally untested and lower-priority. Detection exists, but support claims require their own integration tests.
