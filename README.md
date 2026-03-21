# Qrip
[![Download](https://img.shields.io/badge/Download-.deb-blue?style=for-the-badge)](https://codeberg.org/TheZupZup/Qrip/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/thezupzup/qrip)](https://hub.docker.com/r/thezupzup/qrip)

Qrip is a clean and simple graphical interface for Streamrip, designed for Linux users who want an easier way to build and manage a high-quality music library.

<p align="center">
  <img src="assets/qrip.svg" width="120">
</p>

<p align="center">
  <img src="assets/qrip_ui.png" width="900">
</p>

<p align="center">
  <b>Modern music downloader for Qobuz, Deezer, Tidal & SoundCloud</b>
</p>

## Announcement
- .deb package available in Releases
- Flatpak support in progress

---

## Features

- Simple and intuitive UI for Streamrip
- Download music from supported services (Qobuz, etc.)
- Built for FLAC / high-quality audio
- Real-time progress and logs
- One-click experience (no terminal required)

---

## Why Qrip?

Qrip was created to simplify the process of building a personal music library without relying entirely on streaming platforms.

It is designed for users who want:

- Full control over their music collection
- High-quality audio (FLAC / Hi-Res)
- A clean and easy workflow
- A solution that integrates with self-hosted setups

---

## Use Case

Qrip is ideal for:

- Building a local music library
- Storing music on a NAS
- Creating a self-hosted media ecosystem
- Using media servers like Jellyfin

---

## Workflow
Music Link → Qrip → Local/NAS Storage → Jellyfin → Playback


---

## Installation

Tested on Linux Mint / Debian-based systems

Download the `.deb` package from the releases section:

https://codeberg.org/TheZupZup/Qrip/releases

Then install:

```bash
sudo dpkg -i qrip.deb
```

## Docker (Advanced / NAS / Server)

Available on Docker Hub:
https://hub.docker.com/r/thezupzup/qrip

```bash
docker pull thezupzup/qrip

xhost +local:docker

docker run -e DISPLAY=$DISPLAY \
-v /tmp/.X11-unix:/tmp/.X11-unix \
-v $(pwd)/downloads:/root/Music \
thezupzup/qrip
```
---

## Project Status

This is an actively developed project.

It is part of my open-source learning journey, and I am continuously improving it.

Feedback, suggestions, and contributions are welcome.

---

## Future Ideas

Better library organization

Improved UI/UX

Offline-ready workflows

Integration with self-hosted media systems

---
## Disclaimer & Legal

Qrip is a graphical interface for Streamrip and does not provide, host, or distribute any content.

This software is intended for personal use only.

Users are responsible for ensuring that their use of this tool complies with the terms of service of any platforms they access.

The developer of Qrip does not encourage or support misuse of this software.

---

### Limitations

This program does not include:

- Any functionality intended to bypass DRM or regional restrictions
- Any application IDs, secrets, or private API keys
- Any tools designed to circumvent copyright protection

---

### Technical clarification

Qrip is a user interface (UI) wrapper.

It relies on Streamrip (`rip`), which is a separate and independent open-source project.  
Qrip does not directly interact with any streaming service and only provides a graphical interface for an existing command-line tool.

---

### Trademarks

Qobuz, Deezer, Tidal, and SoundCloud are registered trademarks of their respective owners.  
Qrip is not affiliated with, endorsed by, or sponsored by any of these services.

---

### Terms of Service

Users should ensure that their usage complies with the Terms of Service of the platforms they access, including:

- [Qobuz Terms of Service](https://www.qobuz.com/us-en/info/legal/terms-of-use)
- [Deezer Terms of Service](https://www.deezer.com/legal/cgu)
- [Tidal Terms of Service](https://tidal.com/terms)
- [SoundCloud Terms of Service](https://soundcloud.com/terms-of-use)

---

## Acknowledgment

This project was created with the help of AI tools as part of my learning process.

---
## Author

Created by TheZupZup

---
## License

Copyright (C) 2025 TheZupZup — Qrip  
Licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html)

