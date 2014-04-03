Dependencies
============

BuildPal depends on the following projects:

`Python <http://www.python.org>`_
---------------------------------

`LLVM <http://www.llvm.org>`_
-----------------------------

A bunch of utility classes which fit in nicely in this project.

`Clang <http://clang.llvm.org>`_
--------------------------------

ClangLex is used by Manager to get a list of headers required by a source file.
Clang argument parser is used by Manager to parse the command line.

.. _boost-libs:

`Boost <http://www.boost.org>`_
-------------------------------

Used by all C++ parts of the project.
    * *Boost.ASIO* for Client's (:file:`bp_cl.exe`) IPC communication.
    * *Boost.MultiIndex* for Managers header cache.
    * *Boost.Spirit* as an alternative to ``atoi``/``itoa``/etc.
    * *Boost.Thread* for read-write mutexes.
    * ...

