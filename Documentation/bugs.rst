Bugs and caveats
================

* Header cache and volatile search path
    Cache assumes that a fixed search path and header name will always
    resolve to the same file. If you place a new header file in a directory
    on include path before the pre-existing header file with the same name,
    it is possible that the pre-existing header will still be used.
