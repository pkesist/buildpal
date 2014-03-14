########
BuildPal
########

.. sidebar:: Summary

    :Release: |release|
    :Date: |today|
    :Authors: **Juraj Ivancic**
    :Target: developers
    :status: alpha

Contents:

.. contents::

Motivation
==========

*BuildPal* is a tool for speeding up large C/C++ project builds. Inspired by
the `distcc <https://code.google.com/p/distcc/>`_ project, it works by
distributing parts of build process to other machines on the network.

Requirements
============

1. A C/C++ project (duh!) which uses a build system capable of running tasks
concurrently.
2. A main build machine (client machine) connected to a Local-Area Network (LAN).
3. As many as possible machines (slaves) on LAN capable of running the compiler
your C/C++ project uses.


Supported platforms and compilers
=================================

Currently, the only supported compiler is MS Visual C++ compiler

    * Visual Studio 2005
    * Visual Studio 2008
    * Visual Studio 2010
    * Visual Studio 2012

Features
========

* **Easy setup**
    No additional files, other than BuildPal Server, are needed on the
    slave machines. All required files are automatically transferred
    on-demand.

* **Node auto-detection**
    Build nodes on LAN are automatically detected and used.

* **Build consistency**
    BuildPal takes care to produce object files which are equivalent
    (for all intents and purposes) to the files which would be produced on
    local compilation.

* **Remote preprocessing**
    BuildPal does not preprocess headers on the local machine.
    Headers used by a source file are collected and
    transfered to the slave [#f1]_ . These headers will be reused by the slave
    machines for subsequent compilations.

* **PCH support**
    BuildPal supports precompiled headers. Precompiled headers are
    created locally, on the client machine and are transferred on-demand
    to slaves.

* **Self-balancing**
    BuildPal tries to balance the work between the nodes appropriately by
    keeping track of their statistics, giving more work to faster machines.
    Additionally, if a node runs out of work, it may decide to help out a
    slower node.

Quick-start
===========

If the requirements are met, you can proceed to setting up the farm.

Setting up the Server (slave) nodes
-----------------------------------

On each slave on the network do the following:

* Install BuildPal Server.
* Run buildpal_server.py (buildpal_server.exe).

.. note:

    There is no need to explicitly specify TCP port to use. Each server is
    automatically discovered.

.. note:

    Slaves do not have to have compiler pre-installed.

Setting up the Client
---------------------

1. Install BuildPal Manager.
    * This will install a lot of files, of which 2 are interesting.
        * :file:`buildpal_manager.exe`
        * :file:`bp_cl.exe`

2. Configure the build system.
    * As mentioned, to utilize the build farm and really see the gain, a build
      system capable of concurrently running build tasks is required.
    * You must configure your build system to use BuildPal's :file:`bp_cl.exe`
      instead of MSVC-s :file:`cl.exe`.

.. note::

    Note that calling MSVC compiler setup scripts (such as ``vcvarsall.bat``)
    is still required. :file:`bp_cl.exe` uses its environment to locate the
    real compiler :file:`cl.exe`.

3. Run BuildPal Manager.
    * This will open Manager's GUI which can be used to view detected farm
      configuration. If this is satisfactory, run the Manager by pressing its
      `Start` button.

4. Run the build.
    * Number of concurrent jobs should be set to as many as possible - use as
      much your Client machine can manage.

Client
======

The Client (:file:`bp_cl.exe`) works as a drop-in replacement for the real
compiler (:file:`cl.exe`). As you will usually run dozens of these concurrently,
it is designed to be very thin - it contains almost no compiler-specific
knowledge. It sends the command line and any other relevant environment
information to the Manager. After that, it acts as a string-puppet -- it enters
an event loop in which it processes commands sent by the Manager.

These commands can be:

* ``COMPILE_LOCALLY()``
    Instructs the client to run the command locally, just as the real compiler
    executable was used.
* ``EXECUTE_AND_EXIT(cmdline_opts)``
    Spawn a compiler process from the given `cmdline_opts` command line options
    and exits with the return code from that process.
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

Server
======

Server is the part of BuildPal which runs on slave machines.
Capable of storing files which are shared between build processes.

**Workflow**

#. Start listening on TCP port as specified on the command line.
#. Receive a task, which at this point includes a list of all headers required for compiling the task.
#. Check which of these headers are missing/are out of date and send back this list.
#. Receive a bundle which contains all the missing header files, and the source file itself.
    * Header files are cached, so that they are never requested again during the lifetime of the Server process.
#. In case task requires a PCH we do not have - request PCH and cache it.
#. In case we don't have compiler - request compiler and cache it.
    * Cached compiler will, unlike headers and PCH files, be reused if server is restarted.
#. Run the command line as given by the manager, replacing the executable with the compiler we were sent.
#. Send the retcode, stdout, and stderr to the manager.
#. If retcode == 0 send the resulting object file.
#. In case there was an exception before the compiler was run, notify manager.

Manager
=======

The manager is the most complex part of the BuildPal suite.
Contains all compiler-specific knowledge.
Runs locally, on the client machine.

**Workflow**

#. Start listening on predetemined port.
#. Receive connection from Client.
#. Receive command line from Client connection.
#. Process command line and create tasks.
#. Each source file to be compiled is wrapped in a separate task.
#. Manager can decide to allow the client to run the command locally.
    * This is done when creating PCH file.
#. For each task, Manager 'preprocesses' its source file to determine headers needed for its compilation.
#. Once preprocessing is done, Manager selects a slave node it considers to be the best candidate for compiling the task.
#. Manager uses 2-way handshake with the slave to determine which of the required headers are missing on the slave.
#. Manager sends the missing headers.
#. Manager sends PCH file, if required, to the slave.
#. Manager waits for task completion.
#. In case Server failed to run the task successfully, manager will retry the task.
    * Note that failed task here means that slave did not reach phase of running the compiler.
    * Once the compiler is executed, the task is considered successful, even if the compilation fails.
#. Send the result to the Client.
    

3-rd party
==========

* `Python <http://www.python.org>`_

* `LLVM <http://www.llvm.org>`_

    A bunch of utility classes which fit in nicely in this project.

* `Clang <http://clang.llvm.org>`_

    ClangLex is used by Manager to get a list of headers required by a source file.
    Clang argument parser is used by Manager to parse command line.

* `Boost <http://www.boost.org>`_

    Used by all C++ parts of the project.
        * *Boost.ASIO* for Client's (:file:`bp_cl.exe`) IPC communication.
        * *Boost.MultiIndex* for Managers header cache.
        * *Boost.Spirit* as an alternative to ``atoi``/``itoa``/etc.
        * *Boost.Thread* for read-write mutexes.
        * ...

Benchmarks
==========

Currently BuildPal is mainly tested by building `Boost`_ libraries. Boost
libraries make heavy use of preprocessor, and are thus ideal candidates for
testing both speed and sanity.

Building Boost was done with the following command, after modifying
Boost.Build to use BuildPal's compiler instead of the native msvc
compiler executable::

    bjam stage --stagedir=. -a -j ##

The host machine was not a farm node in distributed compilation.
Tested Boost library version: 1.53.

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: HP Pavillion g7 notebook with Intel i3 processor (4 cores).
    * Slave #1. Dell notebook with i7 processor (8 cores).
    * Slave #2. Speedtest (8 cores).
    * Slave #3. Asus notebook, 4 cores.

+---------------+---------+-----------+-----------+-----------+
|               |         |           |           |           |
| type          | jobs #  |  local    |  2 nodes  |  3 nodes  |
|               |         |           |           |           |
+===============+=========+===========+===========+===========+
| regular build | 4  jobs |  8:01.02  |           |           |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 4  jobs |           |  5:11.88  |  5:29.39  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 16 jobs |           |  2:30.74  |  2:20.66  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 32 jobs |           |  2:07.34  |  2:06.61  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 40 jobs |           |  2:06.59  |  2:00.73  |
+---------------+---------+-----------+-----------+-----------+

Note that these values are just informative. There is a circa 10 second standard
deviation due to the fact that benchmarking was done in an office network.


Bugs and caveats
================

* Header cache and volatile search path
    Cache assumes that a concrete search path and header name will always
    resolve to the same file. In case a new header file is placed in a directory
    on include path before the old header file, it might be omitted due to cache
    hit.

* Visual Studio 2008
    Using BuildPal with Visual Studio 2008 can trigger a compiler bug with
    precompiled headers. To fix the issue see `KB976656 <http://archive.msdn.microsoft.com/KB976656>`_.

.. _future-dev-plans:

Future development plans
========================

* Support more platforms.
    * Support GCC on (Windows/UNIX).
    * Support Clang (Windows/UNIX).
    * ...

* Move task delegation from the Client to the farm.
    * This would make the farm 'Client-aware', providing better performance
      when multiple Clients use the same farm.

* Object file cacheing support.

.. rubric:: Footnotes

.. [#f1] Granted, for this to be done correctly, some source file
        preprocessing is required. This part has been optimized
        and is orders of magnitude faster than 'real' preprocessing.

