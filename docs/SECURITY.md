# Trust boundaries and rollback

This program changes wallpaper paths and color profiles only when the user explicitly clicks Apply Theme or Restore Stable Baseline. The `--doctor` mode, `scripts/verify_install.py` and the installation script do not apply themes.

- The installer owns only a versioned release folder, `current` symlink, one entrypoint, a user-local `.desktop` file and user-local SVG icon. It refuses to overwrite unrecognized launcher files.
- The live project and original KDE settings remain in their existing locations. The user may have a private wallpaper library, Konsole profile, generated KDE/terminal themes and backups; **none belong in GitHub**.
- Theme transactions acquire a process lock, record prior settings and a hashed wallpaper copy, and retain a recovery journal if automated rollback cannot finish.
- Baseline data are retained, and a black PNG asset is protected with checksum validation. Do not remove the journal to silence an error.
- KDE command execution is via argument arrays (`subprocess.run`) instead of shell pipelines. Wallpaper paths are restricted to the project library or explicitly registered image folders.
- Read-only containment detection is fail-closed when more desktops are present than expected. Different Fedora/Arch desktop layouts require specific future work.

**Limitations:** KDE/Plasma can change semantics between versions; headless CI cannot prove live Plasma behavior. The program's GUI currently runs the theme transaction in the main thread; large or slow files can briefly make the window unresponsive. This release favors preserving the user-tested behavior rather than introducing unvalidated threading changes.
