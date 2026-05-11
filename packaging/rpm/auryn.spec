# RPM spec for Auryn — GTK GUI for streamrip.
#
# The package version defaults to APP_VERSION in src/Auryn.py and can be
# overridden at build time:
#   rpmbuild -bb --define "auryn_version 0.1.1" --define "_sourcedir $PWD" packaging/rpm/auryn.spec
#
# To bump the package version, update APP_VERSION in src/Auryn.py (or pass
# --define "auryn_version X.Y.Z" on the command line / via the workflow).

%{!?auryn_version: %define auryn_version 0.0.0}

# Disable noisy/unsupported automatic steps for a pure-Python noarch app.
%global debug_package %{nil}
%global __brp_mangle_shebangs %{nil}

Name:           auryn
Version:        %{auryn_version}
Release:        1%{?dist}
Summary:        GTK GUI for streamrip
License:        GPL-3.0-or-later
URL:            https://github.com/thezupzup/auryn
BuildArch:      noarch

# streamrip is not reliably packaged across Fedora/openSUSE/RHEL, so we don't
# hard-require it. Auryn detects a missing 'rip' at runtime and offers to
# install it via pip/pipx (--user). Adjust the GTK introspection package
# name per distro family if you build outside Fedora.
Requires:       python3
Requires:       python3-gobject
Requires:       gtk3
Recommends:     streamrip

%description
Auryn is a simple GTK 3 graphical front-end for the streamrip command-line
music downloader. If the streamrip package is not available on your
distribution, install it with:

    pipx install streamrip

%prep
# Sources are taken directly from %{_sourcedir} (the checked-out repo root),
# so there is nothing to unpack.

%build
# Pure-Python: nothing to compile.

%install
rm -rf %{buildroot}

install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/auryn/core
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
for size in 16 32 48 256; do
    install -d %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps
done

# Python sources
install -m 0644 %{_sourcedir}/src/Auryn.py        %{buildroot}%{_datadir}/auryn/Auryn.py
install -m 0644 %{_sourcedir}/src/Auryn.ui        %{buildroot}%{_datadir}/auryn/Auryn.ui
install -m 0644 %{_sourcedir}/src/core/__init__.py %{buildroot}%{_datadir}/auryn/core/__init__.py
install -m 0644 %{_sourcedir}/src/core/errors.py  %{buildroot}%{_datadir}/auryn/core/errors.py
install -m 0644 %{_sourcedir}/src/core/status.py  %{buildroot}%{_datadir}/auryn/core/status.py

# Desktop entry
install -m 0644 %{_sourcedir}/desktop/Auryn.desktop \
    %{buildroot}%{_datadir}/applications/Auryn.desktop

# Icons
install -m 0644 %{_sourcedir}/assets/Auryn.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/Auryn.svg
for size in 16 32 48 256; do
    install -m 0644 %{_sourcedir}/assets/Auryn_${size}.png \
        %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/Auryn.png
done

# Launcher: /usr/bin/Auryn matches Exec=Auryn in the desktop file.
cat > %{buildroot}%{_bindir}/Auryn <<'EOF'
#!/bin/sh
exec python3 /usr/share/auryn/Auryn.py "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/Auryn
ln -s Auryn %{buildroot}%{_bindir}/auryn

%files
%{_bindir}/Auryn
%{_bindir}/auryn
%dir %{_datadir}/auryn
%dir %{_datadir}/auryn/core
%{_datadir}/auryn/Auryn.py
%{_datadir}/auryn/Auryn.ui
%{_datadir}/auryn/core/__init__.py
%{_datadir}/auryn/core/errors.py
%{_datadir}/auryn/core/status.py
%{_datadir}/applications/Auryn.desktop
%{_datadir}/icons/hicolor/scalable/apps/Auryn.svg
%{_datadir}/icons/hicolor/16x16/apps/Auryn.png
%{_datadir}/icons/hicolor/32x32/apps/Auryn.png
%{_datadir}/icons/hicolor/48x48/apps/Auryn.png
%{_datadir}/icons/hicolor/256x256/apps/Auryn.png

%changelog
* Mon May 11 2026 TheZupZup <noreply@github.com> - 0.1.1-1
- Initial RPM packaging.
