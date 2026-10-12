# Publish KDE Dynamic Themes under your own GitHub account

No repository has been created and no personal username is presumed. Publication is separate from installation; your Linux username does not have to equal your GitHub username.

1. Create a free account at <https://github.com/signup>, choose your preferred username and verify your email. Enable two-factor authentication when prompted.
2. Sign in and create a new repository at <https://github.com/new>. Owner: **your own account**. Name: `kde-dynamic-themes`. Visibility: **Public**, if desired. **Do not pre-populate** the repository with README, .gitignore, or license; these are managed locally.
3. Open a terminal in the extracted V3.0 release directory. Confirm no private data are present. The `.gitignore` excludes personal wallpapers, backup files, Matugen binaries, compiled caches and settings.
4. Once you have chosen the project license and are ready to publish, run:

```bash
cd "$HOME/Downloads/kde-dynamic-themes-v3.0.0"
git init -b main
git config user.name "YOUR_PUBLIC_DISPLAY_NAME"
git config user.email "YOUR_VERIFIED_OR_NOREPLY_GITHUB_EMAIL"
git add .
git status --short
git commit -m "Release KDE Dynamic Themes v3.0.0"
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/kde-dynamic-themes.git
git push -u origin main
```

Replace placeholders with your own account details. Git may open an interactive authentication flow; do not send access tokens to ChatGPT. To minimize risk, **inspect `git status --short` before committing**. Do not run these commands inside `~/Projects/kde-dynamic-themes` (which contains personal data).

The packaging does not include wallpapers, colorschemes, private Konsole profiles, baseline backups, keys, or Matugen binaries. GitHub Actions runs offline tests without KDE hardware or Qt GUI; a real dual-monitor test is still required after major Plasma changes.

A license has intentionally **not** been selected on the user's behalf. A public GitHub repo without a license is visible but not automatically open-source. Choose one deliberately before encouraging forks/reuse.

After publishing, use GitHub Releases and tags `v3.0.0`, `v3.0.1`, etc. Each release should come from tested `main`, with a separate ZIP and changelog. Keep automatic theme/OS update installs disabled in V3.
