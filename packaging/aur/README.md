# AUR `omapreview` (not live until pushed)

Visitor install once this is on aur.archlinux.org:

```bash
yay -S omapreview
```

This tree is **not** on the AUR yet. This cloud agent has no `aur@aur.archlinux.org` SSH key (`Permission denied (publickey)`). Do not treat `yay -S omapreview` as working until the push below succeeds.

Files:

- `../PKGBUILD` — canonical (same as `omapreview/PKGBUILD` here after copy)
- `omapreview/PKGBUILD`
- `omapreview/.SRCINFO`

Source is the GitHub tag archive, not a clone of Skeptomenos/omapreview:

`https://github.com/Skeptomenos/omapreview/archive/refs/tags/v0.1.0.tar.gz`

sha256 `67e1aa28845b4b4e016a2d6b38a065d9c501abef53f482330c819ef0068fb8bc`

## Publish (machine with AUR SSH)

```bash
git clone ssh://aur@aur.archlinux.org/omapreview.git
cd omapreview
cp /path/to/app/packaging/PKGBUILD .
# or: cp /path/to/app/packaging/aur/omapreview/PKGBUILD .
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "omapreview 0.1.0"
git push origin master
```

Then `yay -S omapreview` on omarchy-air.
