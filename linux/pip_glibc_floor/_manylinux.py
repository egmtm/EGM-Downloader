"""Read by pip only while linux/BUILD.sh installs the hashed lock, never shipped in the app.

pip asks this module whether a manylinux wheel fits this machine (PEP 600, manylinux_compatible). It says
yes only up to glibc 2.17, the level the lock is resolved for (--python-platform x86_64-manylinux_2_17).
So pip takes each package's wheel for older systems, not the newest one the build machine accepts (on
glibc 2.39 cryptography's manylinux_2_34 wheel, which stopped the update check on older systems). The
lock's hashes cover every wheel of a version, so --require-hashes still applies."""

GLIBC_FLOOR = (2, 17)


def manylinux_compatible(major, minor, arch):
    return (major, minor) <= GLIBC_FLOOR
