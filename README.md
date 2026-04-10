# Auryn
[![Download](https://img.shields.io/badge/Download-.deb-blue)](https://github.com/TheZupZup/Auryn/releases/latest)
[![Docker Pulls](https://img.shields.io/docker/pulls/thezupzup/qrip)](https://hub.docker.com/r/thezupzup/qrip)
![CI](https://github.com/TheZupZup/Auryn/actions/workflows/python-app.yml/badge.svg)
![CI](https://github.com/TheZupZup/Auryn/actions/workflows/python-app.yml/badge.svg)
![License](https://img.shields.io/github/license/TheZupZup/Auryn)
![Stars](https://img.shields.io/github/stars/TheZupZup/Auryn?style=social)
![Issues](https://img.shields.io/github/issues/TheZupZup/Auryn)

Auryn is a graphical interface for an existing open-source tool. It does not provide, host, or distribute any content.

<p align="center">
  <img src="./assets/qrip.svg" width="120">
</p>

<p align="center">
  <img src="./assets/qrip_ui.png" width="900">
</p>

<p align="center">
  <b>graphical interface for an existing open-source command-line tool</b>
</p>

## Announcement
- Qrip has been rebranded to Auryn (in progress)
- .deb package available in Releases
- Flatpak support in progress

---

## Features

- Simple and intuitive GUI for managing local audio workflows
- Manage and organize local audio libraries
- Support for high-quality audio formats (FLAC, etc.)
- Real-time progress and logs
- One-click workflow (no terminal required)

---

## Why Auryn?

Building and managing a personal local audio library

It is designed for users who want:

- Full control over their music collection
- High-quality audio (FLAC / Hi-Res)
- A clean and easy workflow
- A solution that integrates with self-hosted setups

---

## Use Case

Auryn is ideal for:

- Building a local music library
- Storing music on a NAS
- Creating a self-hosted media ecosystem
- Using media servers like Jellyfin

---

## Workflow
Input Source → Qrip → Local/NAS Library → Media Server → Playback


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

Auryn is available as a Docker image for advanced users, NAS environments, or server setups.

**Docker Hub:** [thezupzup/qrip](https://hub.docker.com/r/thezupzup/qrip)

### Prerequisites

Since Auryn is a GUI application, you need to allow the container to access your X11 display server:

```bash
xhost +local:docker
```

### Option 1: Docker Run

You can start the container with a single command:

```bash
docker run -d \
  --name auryn \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/downloads:/root/Music \
  thezupzup/qrip
```

**Parameters Explained:**
- `-e DISPLAY=$DISPLAY`: Passes your host's display environment variable to the container.
- `-v /tmp/.X11-unix:/tmp/.X11-unix`: Mounts the X11 socket for GUI rendering.
- `-v $(pwd)/downloads:/root/Music`: Maps your local downloads folder to the container's output directory.

### Option 2: Docker Compose (Recommended)

For a more manageable setup, use a `docker-compose.yml` file:

```yaml
services:
  auryn:
    image: thezupzup/qrip
    container_name: auryn
    environment:
      - DISPLAY=${DISPLAY}
    volumes:
      - /tmp/.X11-unix:/tmp/.X11-unix
      - ./downloads:/root/Music
    network_mode: host
    restart: unless-stopped
```

**To run with Docker Compose:**
1. Create a `docker-compose.yml` file with the content above.
2. Run `docker-compose up -d`.
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

Auryn is a graphical interface for an existing open source audio tool and does not provide, host, or distribute any content.

This software is intended for legitimate use with content you own or are authorized to access.

Users are responsible for ensuring that their use of this tool complies with applicable laws and the terms of service of any platforms they access.

The developer of Qrip does not encourage or support misuse of this software.

---

### Limitations

This program does not include:

- Any functionality related to restricted or protected content access
- Any application IDs, secrets, or private API keys
- Any tools intended to violate platform terms of service

---

### Technical clarification

Auryn is a GUI frontend for an existing open-source command-line tool.
It does not host, distribute, or provide access to copyrighted content, and it does not directly interact with any online services.

---

### Trademarks

Qobuz, Deezer, Tidal, and SoundCloud are registered trademarks of their respective owners.  
Auryn is not affiliated with, endorsed by, or sponsored by any of these services.

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

Copyright (C) 2025 TheZupZup — Auryn  
Licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html)

