# Qrip

![CI](https://github.com/TheZupZup/Qrip/actions/workflows/CI.yml/badge.svg)

Qrip is a simple graphical interface for Streamrip, built for Linux users who want a cleaner way to download music from Qobuz.

⚠️ I am a beginner and this is my first open-source project.

I started building Qrip to create my own high-quality FLAC music library on my NAS.

Instead of relying entirely on streaming platforms, I wanted full control over my music collection, quality, and storage.

This project was created with the help of ChatGPT and Claude as part of my learning journey.  
I am curious, motivated, and continuously improving my understanding of the codebase.

---

## Disclaimer & Legal

**I will not be responsible for how you use Qrip.**

This program **DOES NOT** include:

- Code to bypass Qobuz's DRM or region restrictions
- Qobuz app IDs, secrets, or private API keys
- Any tool designed to circumvent copyright protection

Qrip is a **UI wrapper only**. It calls [Streamrip](https://github.com/nathom/streamrip) (`rip`) which is a separate, independent open-source project. Qrip does not directly interact with any streaming service — it simply provides a graphical interface around an existing command-line tool.

**You must own a valid paid subscription** to any service you download from. Qrip is intended for personal use to build your own music library from content you have legitimately paid for.

Qobuz, Deezer, Tidal, and SoundCloud are registered trademarks of their respective owners.  
Qrip has no partnership, sponsorship, or endorsement with any of these services.

By using Qrip, you agree to comply with the Terms of Service of any platform you use it with:

- [Qobuz Terms of Service](https://www.qobuz.com/us-en/info/legal/terms-of-use)
- [Deezer Terms of Service](https://www.deezer.com/legal/cgu)
- [Tidal Terms of Service](https://tidal.com/terms)
- [SoundCloud Terms of Service](https://soundcloud.com/terms-of-use)

---

## Goal

Make a simple, beginner-friendly GUI for Streamrip that:

- Lets users paste a URL (Qobuz, Deezer, Tidal, SoundCloud)
- Choose a download folder
- Select audio quality (MP3 / FLAC / Hi-Res / MQA)
- See real-time download progress
- See the current track being downloaded
- See remaining tracks
- View percentage progress

---

## Why this project?

I wanted something simple, clean, and easy to use.  
This is also my first real open-source learning experience.

If you're a developer and would like to help, you're more than welcome.

---

## Current Features

- Multi-URL support (Qobuz, Deezer, Tidal, SoundCloud)
- URL input & folder selection
- Audio quality selection (MP3 128 / MP3 320 / CD FLAC / Hi-Res FLAC / MQA)
- Real-time download progress
- Desktop notifications on completion
- Isolated config per run (avoids "Skipping" bugs)
- Automatic log cleanup (>7 days)
- Built-in HTML help & command generator

---

## Installation

Tested on Linux Mint / Debian-based systems.

install via the `.deb` package:

```bash
sudo dpkg -i qrip_0.1.1_all.deb
```

---

## Planned Features

- Real progress tracking (percentage, current track, remaining tracks)
- Better error handling
- Cleaner UI
- English-only codebase for contributors

---

## Distribution Goals

- Initial release as a `.deb` package for Debian-based distributions (Linux Mint, Ubuntu, etc.)
- Future goal: make Qrip available across multiple Linux distributions
- Long-term goal: explore cross-platform support, including Windows (.exe)

Packaging and cross-platform guidance are very welcome.

---

## Contributions

Contributions, suggestions, and improvements are welcome.

As this is my first open-source project, constructive feedback and guidance are greatly appreciated.

---

## Good First Issues

This project is beginner-friendly.

If you're new to open source, here are some ideas:

- Improve error handling
- Refactor parts of the script
- Improve the desktop entry
- Add basic tests
- Improve UI messages

Feel free to open an issue before submitting a PR.

---

## License

Copyright (C) 2025 TheZupZup — Qrip  
Licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html)

---

Made with curiosity and coffee ☕
