# Postgres on the stack's clock. The official image plus libfaketime, which the
# compose file turns on with `LD_PRELOAD` and points at the clock writer's spec -
# see `sim-clock` in the Target Environment's compose file. Argus's own copy
# rather than that repo's: the Target Environment stands up without Argus, and
# Argus's database should not be built from somebody else's directory.
FROM postgres:16

# Linked to one path whatever the architecture, because Debian files the library
# under the machine's triplet and a preload naming a path that is not there is
# ignored with a warning nobody reads - the container would run on the real
# clock on an arm64 Mac and nowhere else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends faketime \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr/lib -path '*/faketime/libfaketime.so.1' -exec ln -s {} /usr/local/lib/libfaketime.so.1 \;
