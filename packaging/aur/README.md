# Packaging

`omarchy install app` takes a pacman package, and that is the only sanctioned
way to install an application on Omarchy — so this is what makes

```bash
omarchy install app Displaywright displaywright-git
```

work, and what lets the README stop telling people to clone a repository.

## AUR

`aur/` is the whole package: a VCS `PKGBUILD` that builds from `main`, plus the
`.SRCINFO` the AUR requires beside it. The two must agree on `pkgver`, so
regenerate the second whenever you touch the first:

```bash
cd packaging/aur
makepkg --printsrcinfo > .SRCINFO
```

To check it before publishing — this installs the build dependencies and needs
sudo, so it is not part of `make test`:

```bash
cd packaging/aur
makepkg -si          # builds, runs the test suite through check(), installs
```

Publishing is a push to the AUR's own git host, which needs an AUR account with
your SSH key registered:

```bash
git clone ssh://aur@aur.archlinux.org/displaywright-git.git
cp packaging/aur/{PKGBUILD,.SRCINFO} displaywright-git/
cd displaywright-git && git commit -am "..." && git push
```

## What the package has to carry that a wheel cannot

The QML renderer lives in `plugin/`, a *sibling* of the Python package rather
than a child of it, so a wheel leaves it behind entirely. `package()` puts it in
`/usr/share/displaywright/plugin`, which is the second place
`displaywright.wallpapers.plugin.source_dir()` looks. Move one without the other
and `displaywright renderer install` fails on every packaged install.
