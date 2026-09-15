# AUR package `omapreview`

Not live until someone with AUR SSH pushes this tree. Visitor install after that:

```bash
yay -S omapreview
```

This directory is filled after tag `v0.1.0` exists (PKGBUILD + `.SRCINFO` with the GitHub archive sha256). Until then use `../PKGBUILD`.

## Publish (on a machine with `aur@aur.archlinux.org` SSH)

```bash
git clone ssh://aur@aur.archlinux.org/omapreview.git
cd omapreview
cp /path/to/omapreview/packaging/PKGBUILD .
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "omapreview 0.1.0"
git push origin master
```

Do not clone `Skeptomenos/omapreview` as the AUR source. The PKGBUILD fetches
`https://github.com/Skeptomenos/omapreview/archive/refs/tags/v0.1.0.tar.gz`.
