# Qrip

Qrip is a simple graphical interface for Streamrip, built for Linux users who want a cleaner way to download music from Qobuz.

⚠️ I am a beginner and this is my first open-source project.

I started building Qrip to create my own high-quality FLAC music library on my NAS.

Instead of relying entirely on streaming platforms, I wanted full control over my music collection, quality, and storage.

This project was created with the help of ChatGPT as part of my learning journey.  
I am curious, motivated, and continuously improving my understanding of the codebase.

---
## Goal

Make a simple, beginner-friendly GUI for Streamrip that:

- Lets users paste a Qobuz album URL
- Choose a download folder
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

- URL input  
- Folder selection  
- Download execution  
- Basic terminal progress window  

---

## Installation

```bash
pipx install streamrip
cp src/Qrip ~/.local/bin/
chmod +x ~/.local/bin/Qrip
Qrip
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

## Disclaimer

This project is just a UI wrapper for Streamrip.  
You must own a valid Qobuz account.

---

Made with curiosity and coffee ☕


## Good First Issues

This project is beginner-friendly.

If you're new to open source, here are some ideas:
- Improve error handling
- Refactor parts of the script
- Improve the desktop entry
- Add basic tests
- Improve UI messages

Feel free to open an issue before submitting a PR.
