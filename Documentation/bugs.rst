.. _bugs

Bugs and caveats
================

* Debug symbols/PDB files/precompiled headers.
    It is difficult to handle PDB file generation when distributing build.
    PDB format is closed and there is no known way to merge two PDB files into a
    single one. In other words, if two objects are compiled on different
    servers, ``BuildPal`` cannot create a single PDB containing debug info for
    both objects.

    ``BuildPal`` currently avoids the issue by replacing any ``/Zi`` compiler
    switches it detects with ``/Z7``, i.e. debug info gets stored in the object
    file itself.
    
    Unfortunately ``/Zi`` and ``/Z7`` compiler options produce incompatible
    precompiled headers. Consequently - you cannot have both PCH and ``/Zi``.
    If you compile files with both PCH and ``/Zi``, BuildPal will discard PCH
    and use the above ``/Z7`` hack.

* Header cache and volatile search path
    Cache assumes that a fixed search path and header name will always
    resolve to the same file. If you place a new header file in a directory
    on include path before the pre-existing header file with the same name,
    it is possible that ``BuildPal`` will not pick up on that. This can cause
    compilation failure on the remote machine due to a missing header(s).
