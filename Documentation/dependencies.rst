Dependencies
============

``BuildPal`` depends on the following projects:

`Python <http://www.python.org>`_
---------------------------------

`LLVM <http://www.llvm.org>`_
-----------------------------

`Clang <http://clang.llvm.org>`_
--------------------------------

.. _boost-libs:

`Boost <http://www.boost.org>`_
-------------------------------

Used by all C++ parts of the project.
    * *Boost.ASIO* for Client's (:file:`bp_cl.exe`) IPC communication.
    * *Boost.MultiIndex* for Managers header cache.
    * *Boost.Spirit* as an alternative to ``atoi``/``itoa``/etc.
    * *Boost.Thread* for read-write mutexes.
    * ...

`pytest <http://pytest.org>`_
-----------------------------
