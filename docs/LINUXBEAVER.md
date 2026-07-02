# 🦫 LinuxBeaver GEGL Plug-ins

Installed by `features/linuxbeaver.sh` (priority 50).

Downloads the
[LinuxBeaver GEGL plug-in collection](https://github.com/LinuxBeaver/LinuxBeaver)
— dozens of text styling, render and photo effects — and installs only its
`.so` binaries into `~/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins`.

## 🖱 Where to find the effects

After restarting GIMP, look under menus such as:

- **Filters → Text Styling**
- **Filters → Render → Fun**
- **Filters → GEGL Operation**

## 📝 Notes

- The installed filenames are tracked in
  `~/.local/share/LinuxBeaver-GEGL-plugins.manifest`. On reruns, the feature
  uses this manifest to remove stale LinuxBeaver binaries without removing
  other GEGL plug-ins.
- The GEGL plug-in directory must contain only `.so` files at its top level.
  Subdirectories or other file types may prevent GIMP from starting.
