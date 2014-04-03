BuildPal Internals
==================

Client
------

The Client (:file:`bp_cl.exe`) works as a drop-in replacement for the real
compiler (:file:`cl.exe`). As you will usually run dozens of these concurrently,
it is designed to be very thin - it contains almost no compiler-specific
knowledge. It sends the command line and any other relevant environment
information to the Manager. After that, it acts as a string-puppet -- it enters
an event loop in which it processes commands sent by the Manager.

These commands are:

* ``COMPILE_LOCALLY()``
    Instructs the client to run the command locally, just as the real compiler
    executable was used.
* ``EXECUTE_AND_EXIT(cmdline_opts)``
    Spawn a compiler process from the given `cmdline_opts` command line options
    and exit with the return code from that process.
* ``EXECUTE_GET_OUTPUT(cmdline)``
    Spawn a compiler process from the given `cmdline_opts` command line options,
    capture return code, stdout, stderr and send them back to the manager. This
    is used by Manager to determine compiler version.
* ``EXIT(retcode, stdout, stderr)``
    Client prints `stdout` to standard output, `stderr` to standard
    error and exits with `retcode` return code.
* ``LOCATE_FILES(file1, file2, ...)``
    Locate specified files, first relative to the compiler executable location
    and then PATH environment variable). Return the list of absolute path
    names. Used to locate compiler files when manager needs to send them to one
    of the slaves.

.. note::

    In case of an error, :file:`bp_cl.exe` will output an error message, and
    will fallback to running the real compiler.

Manager
-------


The manager is the workhorse of the BuildPal suite.
Contains all compiler-specific knowledge.
It must be run locally, on the client machine.

.. todo::

    Add details...

Server
------

Server is the part of BuildPal which runs on slave machines.
Capable of storing files which are shared between build processes.

.. todo::

    Add details...

